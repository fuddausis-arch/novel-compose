"""P1-5 事实级校验：写完每章后对账正文事实与事件流/设定，输出矛盾清单。

抄 Novarrium Logic-Locking 思路：大错有章节级后验，小错（第30章角色眼睛变了
没人抓）靠本章事实对账拦截。

两层检测：
1. 规则层（零成本，确定性，可测试）：
   - 章内互斥状态（同部位互斥描述同章出现）
   - 正文 vs 已知永久状态（事件流记录"失明"，正文写"看见"）
2. LLM 层（准，调一次）：提取本章事实断言，与事件流/世界观设定对照输出矛盾清单

对账节点挂 summarize 后，失败不阻塞主流程（try/except 包裹）。
"""
from __future__ import annotations

import json
import logging
from typing import Any

logger = logging.getLogger(__name__)

# ── 规则层：章内互斥状态（同一瞬间的身体状态，同章同时出现大概率矛盾）──
_MUTEX_STATE_PAIRS = [
    (("瞳孔放大", "瞳孔骤然放大"), ("瞳孔收缩", "瞳孔缩小", "瞳孔骤缩", "收缩回去")),
    (("脸色煞白", "脸色发白", "脸白得", "脸色惨白"), ("脸色涨红", "脸色通红", "脸涨得通红")),
    (("手在抖", "手抖得", "指节发白", "手不停发抖"), ("手很稳", "手纹丝不动")),
    (("冷汗直冒", "冷汗涔涔"), ("浑身发热", "燥热难耐")),
    (("呼吸困难", "喘不上气"), ("呼吸平稳", "气息平稳")),
]

# ── 规则层：永久状态 vs 相反描述（事件流/角色卡已确认的事实被正文推翻）──
# 如事件流记录"右眼失明"，正文写"他看见" → 矛盾
_STATE_CONTRADICTIONS: dict[str, list[str]] = {
    "失明": ["看见", "看到", "盯着", "瞥见", "目不转睛"],
    "瞎了": ["看见", "看到"],
    "断臂": ["抬起手", "伸手去", "握紧拳头"],
    "瘫痪": ["站起来", "站起身", "小跑", "飞奔"],
    "哑巴": ["开口说", "说道", "喊道", "喝道"],
    "无法说话": ["说道", "喊道", "开口"],
}


def _mutex_conflicts(text: str) -> list[dict]:
    """规则层：章内同部位互斥状态 → 矛盾清单。"""
    out = []
    for group_a, group_b in _MUTEX_STATE_PAIRS:
        hit_a = next((w for w in group_a if w in text), None)
        hit_b = next((w for w in group_b if w in text), None)
        if hit_a and hit_b:
            out.append({
                "fact": f"同一部位同时出现互斥状态「{hit_a}」与「{hit_b}」",
                "evidence": f"正文同时包含：{hit_a} / {hit_b}",
                "severity": "high",
                "suggestion": "选择与当前情绪/剧情一致的一侧保留，删除另一侧。",
            })
    return out


def _state_conflicts(text: str, known_states: dict[str, list[str]]) -> list[dict]:
    """规则层：正文 vs 已知永久状态（事件流/角色卡已确认的事实）。

    Args:
        text: 本章正文
        known_states: {"角色名": ["失明", "断臂"], ...}（来自事件流/角色卡）
    """
    out = []
    for entity, states in (known_states or {}).items():
        if not entity or entity not in text:
            continue
        for state in states:
            for opposite in _STATE_CONTRADICTIONS.get(state, []):
                if opposite in text:
                    out.append({
                        "fact": f"角色「{entity}」已知状态「{state}」，但正文出现「{opposite}」",
                        "evidence": f"事件流记录 {entity} = {state}；正文含「{opposite}」",
                        "severity": "high",
                        "suggestion": f"「{entity}」的「{state}」是已确认事实，正文中「{opposite}」相关描述需删除或改为其他表达。",
                    })
    return out


def extract_known_states(repo, chapter: int) -> dict[str, list[str]]:
    """从事件流/角色卡提取本章之前的已知永久状态。

    取 TruthEvent（character_state_change）+ Character.absolute_taboos 里的
    永久身体状态词（失明/断臂/瘫痪/哑巴等）。
    """
    known: dict[str, list[str]] = {}
    try:
        from novel_agent.bible.models import TruthEvent
        events = repo.db.query(TruthEvent).filter(
            TruthEvent.project_id == repo.project_id,
            TruthEvent.chapter < chapter,
            TruthEvent.type.in_(["character_state_change", "timeline_event"]),
        ).all()
        for e in events:
            payload = e.payload or {}
            if isinstance(payload, dict):
                name = payload.get("character") or payload.get("entity") or e.entity_id
                desc = payload.get("state") or payload.get("description") or ""
            else:
                name, desc = e.entity_id, str(payload)
            for state in ("失明", "瞎了", "断臂", "瘫痪", "哑巴", "无法说话"):
                if state in str(desc):
                    known.setdefault(str(name), []).append(state)
    except Exception as e:
        logger.debug("extract_known_states 读取失败: %s", e)
    return known


def rule_fact_reconciliation(text: str, known_states: dict[str, list[str]] | None = None) -> list[dict]:
    """规则层事实对账：章内互斥 + 永久状态推翻。返回矛盾清单（空=通过）。"""
    conflicts = _mutex_conflicts(text)
    conflicts += _state_conflicts(text, known_states or {})
    return conflicts


# ── LLM 层：提取本章事实断言与事件流/设定对照 ──

_FACT_PROMPT = """你是事实对账员。以下是第 {chapter} 章的正文、事件流摘要与世界观/角色卡约束。

【本章正文】
{text}

【事件流（此前已确认的事实）】
{events}

【设定约束（角色卡/世界观/红线）】
{settings}

任务：提取本章正文中的「事实断言」（角色身体状况、所在位置、持有物品、关系状态、生死状态），
逐条与事件流和设定约束对照。发现正文与已确认事实互斥/矛盾时，输出矛盾条目。

输出纯 JSON（禁止 markdown 围栏）：
{{"conflicts": [{{"fact": "被推翻/矛盾的断言", "evidence": "正文证据", "event_ref": "事件流或设定中的对应记录", "severity": "high|low", "suggestion": "修改建议"}}]}}
无矛盾时输出 {{"conflicts": []}}。"""


async def run_fact_reconciliation(
    text: str,
    repo,
    chapter: int,
    llm_client: Any,
    max_events: int = 30,
) -> list[dict]:
    """LLM 事实对账：提取本章事实与事件流/设定对照，返回矛盾清单（失败返回空）。

    调用方（summarize 后节点）应 try/except 包裹，本函数内部也容错，绝不抛异常。
    """
    try:
        from novel_agent.bible.models import TruthEvent
        events = repo.db.query(TruthEvent).filter(
            TruthEvent.project_id == repo.project_id,
            TruthEvent.chapter < chapter,
        ).order_by(TruthEvent.chapter.desc()).limit(max_events).all()
        event_lines = []
        for e in events:
            payload = e.payload if isinstance(e.payload, dict) else {}
            event_lines.append(
                f"第{e.chapter}章 [{e.type}] {e.entity_id}: "
                f"{payload.get('description') or payload.get('state') or e.payload or ''}"
            )
        event_text = "\n".join(event_lines) or "（无历史事件）"

        settings_lines = []
        try:
            settings = repo.list_world_settings()
            for s in (settings or [])[:10]:
                settings_lines.append(f"[{s.category}] {s.title}: {s.content}")
        except Exception:
            pass
        settings_text = "\n".join(settings_lines) or "（无设定约束）"

        prompt = _FACT_PROMPT.format(
            chapter=chapter,
            text=text[:6000],
            events=event_text[:3000],
            settings=settings_text[:3000],
        )
        raw = await llm_client.generate(prompt, system="你是严谨的事实对账员，只输出 JSON。")
        data = json.loads(raw) if isinstance(raw, str) else (raw or {})
        if isinstance(data, dict):
            conflicts = data.get("conflicts") or []
            return [c for c in conflicts if isinstance(c, dict)]
        return []
    except Exception as e:
        logger.warning("run_fact_reconciliation 失败（跳过对账）: %s", e)
        return []


def save_fact_conflicts(repo, chapter: int, conflicts: list[dict]) -> None:
    """把矛盾清单落库到 PostHocResult.fact_conflicts（幂等 upsert）。"""
    try:
        from novel_agent.bible.models import PostHocResult
        row = repo.db.query(PostHocResult).filter(
            PostHocResult.project_id == repo.project_id,
            PostHocResult.chapter == chapter,
        ).first()
        if row is None:
            row = PostHocResult(project_id=repo.project_id, chapter=chapter)
            repo.db.add(row)
        row.fact_conflicts = conflicts
        repo.db.commit()
    except Exception as e:
        logger.warning("save_fact_conflicts 落库失败: %s", e)
