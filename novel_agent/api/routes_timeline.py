"""故事时间线 API：聚合圣经表，输出按章节组织的多泳道时间线。

数据源：
- EntityAppearance   -> 角色/势力/怪物出场泳道
- RelationshipChange -> 关系变更泳道
- Foreshadow         -> 伏笔埋设/回收泳道
- StateChange        -> 状态变更泳道
- EmotionArc         -> 情感弧线泳道
- TruthEvent         -> 通用事件流
- ChapterSummary     -> 章节摘要（标题/时间地点/钩子/字数）
"""
from __future__ import annotations

import logging
from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from novel_agent.bible.database import SessionLocal, set_config
from novel_agent.bible.models import (
    Base,
    ChapterSummary,
    EmotionArc,
    EntityAppearance,
    Foreshadow,
    RelationshipChange,
    StateChange,
    TruthEvent,
)
from novel_agent.config import load_config

router = APIRouter(tags=["timeline"])
logger = logging.getLogger(__name__)

# 情感标签映射（中文情绪词 -> 标签颜色）
EMOTION_LABELS: dict[str, str] = {
    "愤怒": "danger",
    "怒火": "danger",
    "狂怒": "danger",
    "悲伤": "sad",
    "悲痛": "sad",
    "绝望": "sad",
    "喜悦": "happy",
    "高兴": "happy",
    "兴奋": "happy",
    "激动": "happy",
    "紧张": "tense",
    "焦虑": "tense",
    "不安": "tense",
    "平静": "calm",
    "淡然": "calm",
    "冷静": "calm",
    "恐惧": "fear",
    "惊恐": "fear",
    "震惊": "shock",
    "惊讶": "shock",
    "疑惑": "puzzle",
    "困惑": "puzzle",
    "仇恨": "hate",
    "憎恨": "hate",
    "柔情": "love",
    "心动": "love",
    "温情": "love",
}


def _emotion_label(emotion: str) -> str:
    """根据情绪词返回标签类型（用于前端着色）。"""
    if not emotion:
        return "neutral"
    for word, label in EMOTION_LABELS.items():
        if word in emotion:
            return label
    return "neutral"


def get_db():
    cfg = load_config()
    set_config(cfg)
    from novel_agent.bible import database as db_mod
    Base.metadata.create_all(bind=db_mod.engine)
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


@router.get("/{project_id}")
def get_timeline(project_id: int, db: Session = Depends(get_db)):
    """获取项目的完整故事时间线（多泳道）。"""
    # ---- 章节摘要 ----
    summaries = db.query(ChapterSummary).filter(
        ChapterSummary.project_id == project_id
    ).order_by(ChapterSummary.chapter).all()
    summary_map: dict[int, dict] = {}
    for s in summaries:
        summary_map[s.chapter] = {
            "title": s.title or "",
            "time_location": s.time_location or "",
            "core_events": s.core_events or "",
            "chapter_hook": s.chapter_hook or "",
            "word_count": s.word_count or 0,
        }

    chapters = [{"chapter": c, **data} for c, data in sorted(summary_map.items())]

    # ---- 角色/势力/怪物出场泳道 ----
    appearances = db.query(EntityAppearance).filter(
        EntityAppearance.project_id == project_id
    ).order_by(EntityAppearance.chapter).all()
    character_lane: list[dict] = []
    for a in appearances:
        character_lane.append({
            "chapter": a.chapter,
            "entity": a.entity_id,
            "entity_type": a.entity_type,
            "role": a.role_in_chapter or "mention",
            "snippet": (a.context_snippet or "")[:120],
        })

    # ---- 关系变更泳道 ----
    rel_changes = db.query(RelationshipChange).filter(
        RelationshipChange.project_id == project_id
    ).order_by(RelationshipChange.chapter).all()
    relationship_lane: list[dict] = []
    for rc in rel_changes:
        relationship_lane.append({
            "chapter": rc.chapter,
            "source": rc.source_id or "",
            "target": rc.target_id or "",
            "field": rc.field or "",
            "old_value": rc.old_value or "",
            "new_value": rc.new_value or "",
            "reason": rc.reason or "",
        })

    # ---- 伏笔泳道（按伏笔 ID 聚合章节事件）----
    foreshadows = db.query(Foreshadow).filter(
        Foreshadow.project_id == project_id
    ).order_by(Foreshadow.plant_chapter).all()
    foreshadow_lane: list[dict] = []
    for f in foreshadows:
        # 埋设事件
        if f.plant_chapter and f.plant_chapter > 0:
            foreshadow_lane.append({
                "chapter": f.plant_chapter,
                "foreshadow_id": f.foreshadow_id,
                "tier": f.tier or "",
                "event": "planted",
                "description": (f.description or "")[:120],
            })
        # 回收事件
        if f.status == "resolved" and f.planned_resolve_chapter and f.planned_resolve_chapter > 0:
            foreshadow_lane.append({
                "chapter": f.planned_resolve_chapter,
                "foreshadow_id": f.foreshadow_id,
                "tier": f.tier or "",
                "event": "resolved",
                "description": (f.description or "")[:120],
            })
        elif f.status == "developing":
            foreshadow_lane.append({
                "chapter": f.plant_chapter,
                "foreshadow_id": f.foreshadow_id,
                "tier": f.tier or "",
                "event": "developing",
                "description": (f.description or "")[:120],
            })
    foreshadow_lane.sort(key=lambda x: x["chapter"])

    # ---- 状态变更泳道 ----
    state_changes = db.query(StateChange).filter(
        StateChange.project_id == project_id
    ).order_by(StateChange.chapter).all()
    state_lane: list[dict] = []
    for sc in state_changes:
        state_lane.append({
            "chapter": sc.chapter,
            "entity_type": sc.entity_type or "",
            "entity_id": sc.entity_id or "",
            "field": sc.field or "",
            "old_value": sc.old_value or "",
            "new_value": sc.new_value or "",
        })

    # ---- 情感弧线泳道 ----
    emotion_arcs = db.query(EmotionArc).filter(
        EmotionArc.project_id == project_id
    ).order_by(EmotionArc.chapter).all()
    emotion_lane: list[dict] = []
    for e in emotion_arcs:
        emotion_lane.append({
            "chapter": e.chapter,
            "character": e.character_name or "",
            "emotion_before": e.emotion_before or "",
            "emotion_after": e.emotion_after or "",
            "event": (e.event or "")[:120],
            "label": _emotion_label(e.emotion_after or ""),
        })

    # ---- 通用事件流 ----
    truth_events = db.query(TruthEvent).filter(
        TruthEvent.project_id == project_id
    ).order_by(TruthEvent.chapter).all()
    events: list[dict] = []
    for te in truth_events:
        payload = te.payload or {}
        detail = ""
        if isinstance(payload, dict):
            detail = str(payload.get("detail") or payload.get("summary") or "")[:150]
        events.append({
            "chapter": te.chapter,
            "type": te.type or "",
            "entity_id": te.entity_id or "",
            "detail": detail,
            "payload": payload if isinstance(payload, dict) else {},
        })

    # ---- 章节数汇总 ----
    all_chapters = sorted(set(
        [c["chapter"] for c in chapters]
        + [a["chapter"] for a in character_lane]
        + [r["chapter"] for r in relationship_lane]
        + [f["chapter"] for f in foreshadow_lane]
        + [s["chapter"] for s in state_lane]
        + [e["chapter"] for e in emotion_lane]
        + [ev["chapter"] for ev in events]
    ))

    return {
        "project_id": project_id,
        "chapters": chapters,
        "chapter_range": (min(all_chapters), max(all_chapters)) if all_chapters else (0, 0),
        "lanes": {
            "characters": character_lane,
            "relationships": relationship_lane,
            "foreshadows": foreshadow_lane,
            "states": state_lane,
            "emotions": emotion_lane,
        },
        "events": events,
        "counts": {
            "characters": len(character_lane),
            "relationships": len(relationship_lane),
            "foreshadows": len(foreshadow_lane),
            "states": len(state_lane),
            "emotions": len(emotion_lane),
            "events": len(events),
        },
    }
