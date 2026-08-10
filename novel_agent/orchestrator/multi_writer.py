"""多写手并行模式（Phase 3.4）：骨架 -> 5 专项并行 -> 整合。

移植 bishu-novel mvp 工作流的并行写手协议：
1. novel-writer（骨架写手）产出带 SLOT 标记的 JSON 骨架
2. 5 个专项写手并行填槽（dialogue/action/internal/description/transition）
3. novel-storyboard-integrator 整合为连贯正文

协议格式（与 bishu-novel 完全一致）：
- 骨架: {"skeleton": "...[SLOT_DIALOGUE_槽名]...", "slots": {"DIALOGUE": [...], ...}}
- 专项: {"DIALOGUE_槽名": "填槽内容", ...}
- 整合: {"body": "完整章节正文"}

失败策略：骨架解析失败/专项全部失败/整合失败时返回 None，
调用方（write_chapter）自动回退单写手模式，保证流水线不中断。
"""
from __future__ import annotations

import asyncio
import logging
import re
from typing import Any

from novel_agent.utils.json_parser import parse_json_strict
from novel_agent.workflows.loader import WorkflowResources

logger = logging.getLogger(__name__)

# SLOT 类型 -> 专项写手 agent_type
SPECIALIST_AGENTS: dict[str, str] = {
    "DIALOGUE": "novel-dialogue-writer",
    "ACTION": "novel-action-writer",
    "INTERNAL": "novel-internal-writer",
    "DESCRIPTION": "novel-description-writer",
    "TRANSITION": "novel-transition-writer",
}

_SLOT_RE = re.compile(r"\[SLOT_([A-Z]+)_([^\]]+)\]")


def _count_cn(text: str) -> int:
    return len(re.findall(r"[\u4e00-\u9fff]", text))


def _build_context_package(state: dict[str, Any], chapter_brief: str,
                           word_min: int, word_max: int) -> str:
    """组装写手共享的上下文包（对齐 write_chapter 的核心注入，精简版）。"""
    parts = [
        f"<task>第{state['chapter']}章《{state.get('title', '')}》正文创作。</task>",
        f"<word_limit>正文 {word_min}-{word_max} 字。{word_max} 字是硬性天花板，超过即废稿。"
        f"宁可剧情紧凑，不要注水。</word_limit>",
    ]
    context = state.get("context", "")
    if context:
        parts.append(f"<context>\n{context}\n</context>")
    if chapter_brief:
        parts.append(f"<constraints>\n{chapter_brief}\n</constraints>")
    style_analysis = state.get("style_analysis", "")
    if style_analysis:
        parts.append(
            f"<style_analysis>\n人类网文样本写法分析，创作时运用这些技巧：\n"
            f"{style_analysis}\n</style_analysis>"
        )
    return "\n\n".join(parts)


async def _call_agent(llm_client: Any, res: WorkflowResources, agent_type: str,
                      user_content: str, node_name: str) -> str:
    """按 agents.json 的参数调一个 bishu agent。"""
    params = res.model_params(agent_type)
    system = res.system_prompt(agent_type)
    return await llm_client.generate(
        user_content,
        system=system or None,
        temperature=params.get("temperature"),
        thinking=bool(params.get("thinking_enabled", True)),
        node_name=node_name,
    )


async def _gen_skeleton(state: dict[str, Any], llm_client: Any,
                        res: WorkflowResources, context_pkg: str) -> dict | None:
    """骨架写手：产出 SLOT 标记骨架 JSON。"""
    user = (
        f"{context_pkg}\n\n"
        f"<instruction>基于以上上下文，产出本章叙事骨架（带 SLOT 标记的 JSON）。"
        f"骨架本身是完整连贯的叙事流，槽位留给专项写手深化。"
        f"只输出纯 JSON，不要任何包裹。</instruction>"
    )
    raw = await _call_agent(llm_client, res, "novel-writer", user,
                            f"multi_skeleton_ch{state['chapter']}")
    data = parse_json_strict(raw, default=None)
    if not isinstance(data, dict):
        logger.warning("多写手：骨架 JSON 解析失败")
        return None
    skeleton = data.get("skeleton", "")
    slots = data.get("slots", {})
    if not skeleton or not isinstance(slots, dict):
        logger.warning("多写手：骨架缺少 skeleton/slots 字段")
        return None
    # 校验骨架中的 SLOT 标记与 slots 声明一致（不一致时以骨架标记为准重建）
    marks: dict[str, list[str]] = {}
    for m in _SLOT_RE.finditer(skeleton):
        marks.setdefault(m.group(1), []).append(m.group(2))
    for slot_type, names in marks.items():
        declared = slots.get(slot_type) or []
        if set(declared) != set(names):
            slots[slot_type] = names
    return {"skeleton": skeleton, "slots": slots}


async def _gen_specialist(slot_type: str, slot_names: list[str],
                          skeleton: str, state: dict[str, Any],
                          llm_client: Any, res: WorkflowResources,
                          context_pkg: str) -> dict[str, str]:
    """单个专项写手：填自己类型的所有槽。失败返回空 dict。"""
    agent_type = SPECIALIST_AGENTS.get(slot_type)
    if not agent_type:
        return {}
    slots_desc = "、".join(f"[SLOT_{slot_type}_{n}]" for n in slot_names)
    user = (
        f"{context_pkg}\n\n"
        f"<skeleton>\n{skeleton}\n</skeleton>\n\n"
        f"<instruction>以上是叙事骨架。你负责填充以下槽位：{slots_desc}\n"
        f"输出纯 JSON：key 为 \"{slot_type}_槽名\"，value 为填槽内容。"
        f"只输出与槽位对应的内容，不要包裹代码块。</instruction>"
    )
    try:
        raw = await _call_agent(llm_client, res, agent_type, user,
                                f"multi_{slot_type.lower()}_ch{state['chapter']}")
        data = parse_json_strict(raw, default=None)
        if isinstance(data, dict):
            return {k: str(v) for k, v in data.items()}
    except Exception as e:
        logger.warning("多写手：专项 %s 填槽失败: %s", slot_type, e)
    return {}


async def _integrate(skeleton: str, fills: dict[str, str],
                     state: dict[str, Any], llm_client: Any,
                     res: WorkflowResources, context_pkg: str) -> str | None:
    """整合写手：骨架 + 全部填槽 -> 最终正文。"""
    import json as _json
    user = (
        f"{context_pkg}\n\n"
        f"<skeleton>\n{skeleton}\n</skeleton>\n\n"
        f"<fills>\n{_json.dumps(fills, ensure_ascii=False, indent=2)}\n</fills>\n\n"
        f"<instruction>把骨架与专项填槽整合为连贯终稿。"
        f"输出纯 JSON：{{\"body\": \"完整章节正文\"}}，不要任何包裹。</instruction>"
    )
    raw = await _call_agent(llm_client, res, "novel-storyboard-integrator", user,
                            f"multi_integrate_ch{state['chapter']}")
    data = parse_json_strict(raw, default=None)
    if isinstance(data, dict) and data.get("body", "").strip():
        return data["body"]
    logger.warning("多写手：整合结果缺少 body")
    return None


def _local_fill(skeleton: str, fills: dict[str, str]) -> str:
    """确定性本地填槽：整合失败时的兜底（直接替换 SLOT 标记）。"""
    def _sub(m: re.Match[str]) -> str:
        key = f"{m.group(1)}_{m.group(2)}"
        return fills.get(key, m.group(0))
    return _SLOT_RE.sub(_sub, skeleton)


def _has_residual_slots(text: str) -> bool:
    """检测正文中是否残留未填充的 SLOT 标记。"""
    return bool(_SLOT_RE.search(text))


async def write_chapter_multi(state: dict[str, Any], llm_client: Any,
                              repo: Any = None, config: Any = None,
                              chapter_brief: str = "",
                              word_min: int = 2200, word_max: int = 3500) -> dict | None:
    """多写手并行模式写正文。

    Returns:
        与 write_chapter 相同契约的 dict；任何关键阶段失败返回 None（调用方回退单写手）。
    """
    res = WorkflowResources()
    context_pkg = _build_context_package(state, chapter_brief, word_min, word_max)

    # 1. 骨架
    skeleton_data = await _gen_skeleton(state, llm_client, res, context_pkg)
    if skeleton_data is None:
        return None
    skeleton = skeleton_data["skeleton"]
    slots = skeleton_data["slots"]
    logger.info("多写手 第%d章：骨架完成，槽位分布 %s",
                state["chapter"], {k: len(v) for k, v in slots.items()})

    # 2. 5 专项并行填槽
    tasks = {
        st: _gen_specialist(st, names, skeleton, state, llm_client, res, context_pkg)
        for st, names in slots.items() if names
    }
    results = await asyncio.gather(*tasks.values(), return_exceptions=True)
    fills: dict[str, str] = {}
    failed_types = 0
    for st, r in zip(tasks.keys(), results):
        if isinstance(r, Exception):
            logger.warning("多写手：专项 %s 异常: %s", st, r)
            failed_types += 1
            continue
        fills.update(r)
    if tasks and failed_types == len(tasks):
        logger.warning("多写手：全部专项失败，回退单写手")
        return None
    logger.info("多写手 第%d章：填槽完成，共 %d 槽", state["chapter"], len(fills))

    # 3. 整合（失败时本地确定性填槽兜底）
    body = await _integrate(skeleton, fills, state, llm_client, res, context_pkg)
    if body is None:
        body = _local_fill(skeleton, fills)
        logger.info("多写手 第%d章：整合失败，使用本地填槽兜底", state["chapter"])

    # SLOT 残留检测：本地兜底/整合产出都可能残留未填充标记，
    # clean_chapter_text 不处理 SLOT，残留标记会直接泄漏进正文 → 回退单写手
    if _has_residual_slots(body):
        residual = _SLOT_RE.findall(body)
        logger.warning("多写手 第%d章：正文残留 %d 个未填充 SLOT %s，回退单写手",
                       state["chapter"], len(residual), residual[:5])
        return None

    # 4. 清理 + 返回（契约对齐 write_chapter）
    from novel_agent.orchestrator.text_utils import clean_chapter_text
    body = clean_chapter_text(body, state["chapter"], state.get("title", ""))
    if not body.strip():
        return None
    ver = state.get("draft_version", 0) + 1
    return {
        "draft": body,
        "status": "drafted",
        "draft_version": ver,
        "drafts": [{"version": ver, "text": body, "score": 0}],
        "word_count": _count_cn(body),
        "writer_mode": "multi",
        "_beat_type": state.get("_beat_type", ""),
        "_pending_feedback_ids": list(state.get("_pending_feedback_ids") or []),
    }
