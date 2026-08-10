"""记忆提炼回流（P0-②）：本章新信息 → 写回设定库 + 溯源日志。

思路（对照 TencentDB Agent Memory 的 L0→L1 金字塔）：
summarize 存完摘要后，再让 LLM 从正文提炼"新增/变化的设定事实"，
保守地追加到 角色 known_info / 世界观 content / 故事线 notes，
并写 MemoryRefinement 溯源日志（哪一章定的、原句是什么）。

安全策略：
- 只追加不覆盖结构化字段（追加到累积字段，不重写设定主体）
- LLM 输出非法 / 实体找不到 → 跳过该条，不中断整章
- 单实体失败不影响其他实体；整体失败降级跳过，不阻塞主流程
"""
from __future__ import annotations

import logging

logger = logging.getLogger(__name__)

_REFINE_SYSTEM = """你是小说设定提炼助手。从给定章节正文中，提炼"新增或变化的设定事实"。
只提炼确凿、明确写出的信息，宁缺毋滥，不要脑补、不要推断。
每条必须给出正文中的原句作为证据。只输出 JSON 数组，不要其他文字：
[
  {"entity_type": "character|worldsetting|storyline",
   "entity_id": "角色名或设定标题或故事线名（必须是设定库中已存在的实体名）",
   "new_value": "新事实的一句话描述",
   "source_preview": "正文中的原句（30字以内）"}
]
规则：
1. 已有信息不要重复提炼（角色已知信息/世界观已写过的不要）
2. 情绪、位置这类已由状态更新覆盖的不要提炼
3. 最多 8 条；没有新设定就输出 []"""


def _build_prompt(chapter: int, content: str, core_events: str = "") -> str:
    ev = f"\n【本章摘要】\n{core_events}" if core_events else ""
    return (
        f"【第{chapter}章正文】\n{content}\n{ev}\n\n"
        f"请提炼本章新增/变化的设定事实（角色新特质、世界观补充、故事线推进结论）。"
    )


async def refine_memories(repo, llm_client, chapter: int, content: str,
                          core_events: str = "", max_items: int = 8) -> dict:
    """提炼并写回设定库，返回 {applied, skipped, reason}。"""
    try:
        from novel_agent.utils.json_parser import parse_json_strict
        prompt = _build_prompt(chapter, content, core_events)
        raw = await llm_client.generate(prompt, system=_REFINE_SYSTEM, temperature=0.2)
        parsed = parse_json_strict(raw) or []
        # parse_json_strict 对数组返回 {"_list": [...]}，兼容两种形态
        if isinstance(parsed, dict) and isinstance(parsed.get("_list"), list):
            items = parsed["_list"]
        elif isinstance(parsed, list):
            items = parsed
        else:
            return {"applied": 0, "skipped": 0, "reason": "LLM 输出非数组"}
    except Exception as e:
        logger.warning("ch%d 记忆提炼调用失败: %s", chapter, e)
        return {"applied": 0, "skipped": 0, "reason": str(e)}

    applied = skipped = 0
    for it in items[:max_items]:
        if not isinstance(it, dict):
            continue
        etype = str(it.get("entity_type", "")).strip()
        eid = str(it.get("entity_id", "")).strip()
        new_value = str(it.get("new_value", "")).strip()
        source = str(it.get("source_preview", "")).strip()
        if not eid or not new_value or etype not in ("character", "worldsetting", "storyline"):
            skipped += 1
            continue
        try:
            if _apply_one(repo, chapter, etype, eid, new_value, source):
                applied += 1
            else:
                skipped += 1
        except Exception as e:
            logger.warning("ch%d 提炼回流「%s/%s」失败: %s", chapter, etype, eid, e)
            skipped += 1
            try:
                repo.db.rollback()
            except Exception:
                pass

    if applied:
        logger.info("ch%d 记忆提炼回流: 应用%d 跳过%d", chapter, applied, skipped)
    return {"applied": applied, "skipped": skipped}


def _apply_one(repo, chapter: int, etype: str, eid: str,
               new_value: str, source: str) -> bool:
    """把一条新事实追加到对应实体，并写溯源日志。返回是否应用成功。"""
    label = f"【第{chapter}章补充】{new_value}"
    field = "notes"
    if etype == "character":
        char = repo.get_character(eid)
        if not char:
            return False
        field = "known_info"
        old = (char.known_info or "").strip()
        updated = f"{old}；{label}" if old else label
        repo.update_character(eid, known_info=updated)
    elif etype == "worldsetting":
        ws_list = repo.list_world_settings()
        match = next((w for w in ws_list if eid in (w.title or "")), None)
        if not match:
            return False
        field = "content"
        old = (match.content or "").strip()
        updated = f"{old}\n\n{label}" if old else label
        match.content = updated
        repo.db.commit()
    elif etype == "storyline":
        from novel_agent.bible.models import Storyline
        line = repo.db.query(Storyline).filter(
            Storyline.project_id == repo.project_id,
            Storyline.name == eid,
        ).first()
        if not line:
            return False
        old = (line.notes or "").strip()
        updated = f"{old}\n{label}" if old else label
        line.notes = updated
        repo.db.commit()
    else:
        return False

    try:
        repo.record_memory_refinement(
            chapter=chapter, entity_type=etype, entity_id=eid,
            field=field, new_value=label, source_preview=source,
            method="refine",
        )
    except Exception as e:
        logger.warning("ch%d 写入溯源日志失败（不影响更新）: %s", chapter, e)
    return True
