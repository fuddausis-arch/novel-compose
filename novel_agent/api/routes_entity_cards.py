"""实体卡片聚合 API：为卡片抽屉系统提供单个实体的完整详情。

数据源：直接查圣经表全字段（不反推，天然准确）。
支持实体类型：character / faction / monster / foreshadow / location

每个响应包含：
- entity: 实体全字段
- relations: 关联关系（角色关系/势力关系/地点关系）
- appearances: 出场章节记录（角色/怪物）
- related: 相关数据（伏笔依赖、子地点等）
"""
from __future__ import annotations

import logging
import re
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from novel_agent.audit.name_authority import classify_name
from novel_agent.bible.database import SessionLocal, set_config
from novel_agent.bible.models import (
    Base,
    Character,
    CharacterRelationship,
    EntityAppearance,
    EntityNameOverride,
    Faction,
    FactionRelationship,
    Foreshadow,
    Location,
    LocationRelationship,
    Monster,
)
from novel_agent.config import load_config

router = APIRouter(tags=["entity-cards"])
logger = logging.getLogger(__name__)

# 说话词中的情绪/语气字（与 validator 一致）："林晚笑道"→"林晚"
_SPEAKER_RE = re.compile(r'([\u4e00-\u9fff]{2,6})(?:说|道|问|答|喊|骂|叹|笑|怒|惊)(?=[：:])')
_SPEAKER_SUFFIX = set("说问道答喊骂叹笑怒惊")


def _extract_alias_candidates(db: Session, project_id: int, entity_type: str,
                              entity_id: str, appearances: list[EntityAppearance],
                              already_merged: set[str]) -> list[str]:
    """从出场片段中提取"安全别名候选"。

    只保留 name_authority 判定为称呼/别名（kinship/generic_alias/unknown）的词，
    排除疑似人名（person，可能是真实未注册角色，不能乱合并），
    排除规范名本身与已合并别名。
    """
    candidates: set[str] = set()
    for a in appearances:
        snippet = a.context_snippet or ""
        for m in _SPEAKER_RE.finditer(snippet):
            name = m.group(1)
            while name and name[-1] in _SPEAKER_SUFFIX:
                name = name[:-1]
            name = name.strip()
            if len(name) < 2 or name == entity_id:
                continue
            if classify_name(name) == "person":
                continue  # 疑似人名，不列为安全别名候选
            if name in already_merged:
                continue
            candidates.add(name)
    return sorted(candidates)


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


# ==================== 序列化辅助 ====================

def _char_card(c: Character) -> dict:
    return {
        "id": c.id,
        "name": c.name,
        "role": c.role,
        "age": c.age,
        "gender": c.gender,
        "appearance": c.appearance,
        "background": c.background,
        "personality": c.personality,
        "motivation": c.motivation,
        "core_contradiction": c.core_contradiction,
        "sensory_memories": c.sensory_memories,
        "absolute_taboos": c.absolute_taboos,
        "importance": c.importance,
        "current_location": c.current_location,
        "current_emotion": c.current_emotion,
        "known_info": c.known_info,
        "arc": c.arc,
        "relationships": c.relationships,
        "secrets": c.secrets,
        "language_style": c.language_style,
        "combat_style": c.combat_style,
        "growth_curve": getattr(c, "growth_curve", ""),
        "emotional_anchor": getattr(c, "emotional_anchor", ""),
    }


def _faction_card(f: Faction) -> dict:
    return {
        "id": f.id,
        "name": f.name,
        "alias": f.alias,
        "type": f.type,
        "tier": f.tier,
        "alignment": f.alignment,
        "description": f.description,
        "history": f.history,
        "goals": f.goals,
        "hierarchy": f.hierarchy,
        "territories": f.territories,
        "resources": f.resources,
    }


def _monster_card(m: Monster) -> dict:
    return {
        "id": m.id,
        "name": m.name,
        "alias": m.alias,
        "species": m.species,
        "rank": m.rank,
        "tier": m.tier,
        "attributes": m.attributes,
        "skills": m.skills,
        "drops": m.drops,
        "habitats": m.habitats,
        "behavior": m.behavior,
        "weaknesses": m.weaknesses,
        "lore": m.lore,
        "first_appearance": m.first_appearance,
    }


def _foreshadow_card(f: Foreshadow) -> dict:
    return {
        "id": f.id,
        "foreshadow_id": f.foreshadow_id,
        "tier": f.tier,
        "plant_chapter": f.plant_chapter,
        "description": f.description,
        "depends_on": f.depends_on,
        "status": f.status,
        "planned_resolve_chapter": f.planned_resolve_chapter,
    }


def _location_card(l: Location) -> dict:
    return {
        "id": l.id,
        "name": l.name,
        "type": l.type,
        "description": l.description,
        "parent_name": l.parent_name,
        "coord_x": l.coord_x,
        "coord_y": l.coord_y,
        "importance": l.importance,
        "tier": l.tier,
        "layer": l.layer,
        "ruler": l.ruler or "",
        "plot_role": l.plot_role or "",
        "unlocked_chapter": l.unlocked_chapter or 0,
    }


# ==================== 聚合端点 ====================

@router.get("/api/entity-cards/{project_id}/{entity_type}/{entity_id}")
def get_entity_card(project_id: int, entity_type: str, entity_id: str, db: Session = Depends(get_db)):
    """获取单个实体的完整卡片数据（全字段 + 关系 + 出场记录）。"""
    result: dict = {"entity_type": entity_type, "entity_id": entity_id}
    entity_type = entity_type.lower()

    if entity_type == "character":
        c = db.query(Character).filter(
            Character.project_id == project_id, Character.name == entity_id
        ).first()
        if not c:
            raise HTTPException(404, "角色不存在")
        result["entity"] = _char_card(c)
        # 关系列表
        rels = db.query(CharacterRelationship).filter(
            CharacterRelationship.project_id == project_id,
            (CharacterRelationship.source_character == entity_id) |
            (CharacterRelationship.target_character == entity_id),
        ).all()
        result["relations"] = [
            {
                "id": r.id,
                "source": r.source_character,
                "target": r.target_character,
                "relation_type": r.relation_type,
                "relation_subtype": r.relation_subtype,
                "strength": r.strength,
                "description": r.description,
                "since_chapter": r.since_chapter,
                "status": r.status,
                "is_bidirectional": r.is_bidirectional,
            }
            for r in rels
        ]
        # 相关伏笔（伏笔描述中提到该角色）
        fs = db.query(Foreshadow).filter(Foreshadow.project_id == project_id).all()
        result["foreshadows"] = [
            {
                "foreshadow_id": f.foreshadow_id,
                "tier": f.tier,
                "status": f.status,
                "description": f.description,
                "plant_chapter": f.plant_chapter,
            }
            for f in fs if entity_id in (f.description or "")
        ]
        # 已合并的别名（"我的修正"，可回滚）
        overrides = db.query(EntityNameOverride).filter(
            EntityNameOverride.project_id == project_id,
            EntityNameOverride.entity_type == "character",
            EntityNameOverride.canonical_name == entity_id,
        ).all()
        result["name_overrides"] = [
            {"id": o.id, "alias": o.alias, "note": o.note}
            for o in overrides
        ]
        result["alias_candidates"] = []

    elif entity_type == "faction":
        f = db.query(Faction).filter(
            Faction.project_id == project_id, Faction.name == entity_id
        ).first()
        if not f:
            raise HTTPException(404, "势力不存在")
        result["entity"] = _faction_card(f)
        rels = db.query(FactionRelationship).filter(
            FactionRelationship.project_id == project_id,
            (FactionRelationship.source_faction_id == f.id) |
            (FactionRelationship.target_faction_id == f.id),
        ).all()
        faction_map = {x.id: x.name for x in db.query(Faction).filter(Faction.project_id == project_id).all()}
        result["relations"] = [
            {
                "id": r.id,
                "source": faction_map.get(r.source_faction_id, str(r.source_faction_id)),
                "target": faction_map.get(r.target_faction_id, str(r.target_faction_id)),
                "relation_type": r.relation_type,
                "strength": r.strength,
                "description": r.description,
                "since_chapter": r.since_chapter,
                "status": r.status,
            }
            for r in rels
        ]

    elif entity_type == "monster":
        m = db.query(Monster).filter(
            Monster.project_id == project_id, Monster.name == entity_id
        ).first()
        if not m:
            raise HTTPException(404, "怪物不存在")
        result["entity"] = _monster_card(m)

    elif entity_type == "foreshadow":
        f = db.query(Foreshadow).filter(
            Foreshadow.project_id == project_id, Foreshadow.foreshadow_id == entity_id
        ).first()
        if not f:
            raise HTTPException(404, "伏笔不存在")
        result["entity"] = _foreshadow_card(f)

    elif entity_type == "location":
        l = db.query(Location).filter(
            Location.project_id == project_id, Location.name == entity_id
        ).first()
        if not l:
            raise HTTPException(404, "地点不存在")
        result["entity"] = _location_card(l)
        # 子地点
        children = db.query(Location).filter(
            Location.project_id == project_id, Location.parent_name == entity_id
        ).all()
        result["children"] = [_location_card(x) for x in children]
        # 地点关系
        rels = db.query(LocationRelationship).filter(
            LocationRelationship.project_id == project_id,
            (LocationRelationship.source_location == entity_id) |
            (LocationRelationship.target_location == entity_id),
        ).all()
        result["relations"] = [
            {
                "id": r.id,
                "source": r.source_location,
                "target": r.target_location,
                "relation_type": r.relation_type,
                "distance": r.distance,
                "description": r.description,
            }
            for r in rels
        ]

    else:
        raise HTTPException(400, f"不支持的实体类型: {entity_type}")

    # 出场记录（character / monster / faction）
    if entity_type in ("character", "monster", "faction"):
        appearances = db.query(EntityAppearance).filter(
            EntityAppearance.project_id == project_id,
            EntityAppearance.entity_type == entity_type,
            EntityAppearance.entity_id == entity_id,
        ).order_by(EntityAppearance.chapter).all()
        result["appearances"] = [
            {
                "chapter": a.chapter,
                "role_in_chapter": a.role_in_chapter,
                "context_snippet": a.context_snippet,
            }
            for a in appearances
        ]
        # 角色卡：补充"安全别名候选"（命名权威词表判定为称呼/别名的词）
        if entity_type == "character":
            already_merged = {o["alias"] for o in result.get("name_overrides", [])}
            result["alias_candidates"] = _extract_alias_candidates(
                db, project_id, entity_type, entity_id, appearances, already_merged)
    else:
        result["appearances"] = []

    return result
