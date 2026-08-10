"""百科卡 API（可视化融合 P5）：五类实体卡片浏览 + 出场场景索引。

前端 EncyclopediaView 通过本接口一次性拉取五类实体（角色/势力/怪物/地点/伏笔）
的摘要列表 + 出场章节索引，点击卡片后复用 EntityCardDrawer 查看全字段详情。
"""
from __future__ import annotations

import logging

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from novel_agent.bible.database import SessionLocal, set_config
from novel_agent.bible.models import (
    Base,
    Character,
    EntityAppearance,
    Faction,
    Foreshadow,
    Location,
    Monster,
)
from novel_agent.config import load_config

router = APIRouter(tags=["encyclopedia"])
logger = logging.getLogger(__name__)


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


def _appearance_counts(db: Session, project_id: int) -> dict[str, int]:
    """{entity_id: 出场次数}（character 按名字，faction/monster 按字符串 id）。"""
    rows = db.query(EntityAppearance.entity_id).filter(
        EntityAppearance.project_id == project_id,
    ).all()
    counts: dict[str, int] = {}
    for (eid,) in rows:
        counts[eid] = counts.get(eid, 0) + 1
    return counts


def _chapter_list(db: Session, project_id: int, entity_type: str, entity_id: str) -> list[int]:
    rows = db.query(EntityAppearance.chapter).filter(
        EntityAppearance.project_id == project_id,
        EntityAppearance.entity_type == entity_type,
        EntityAppearance.entity_id == entity_id,
    ).order_by(EntityAppearance.chapter).all()
    return [r[0] for r in rows]


def _character_item(c: Character, appearances: list[int]) -> dict:
    return {
        "entity_type": "character",
        "id": c.id,
        "name": c.name,
        "role": c.role or "",
        "importance": c.importance or "",
        "summary": (c.personality or c.background or c.motivation or "")[:200],
        "current_location": c.current_location or "",
        "current_emotion": c.current_emotion or "",
        "appearance_chapters": appearances,
    }


def _faction_item(f: Faction, appearances: list[int]) -> dict:
    return {
        "entity_type": "faction",
        "id": f.id,
        "name": f.name,
        "alias": f.alias or "",
        "tier": f.tier or "",
        "type": f.type or "",
        "summary": (f.description or "")[:200],
        "appearance_chapters": appearances,
    }


def _monster_item(m: Monster, appearances: list[int]) -> dict:
    return {
        "entity_type": "monster",
        "id": m.id,
        "name": m.name,
        "rank": m.rank or "",
        "tier": m.tier or "",
        "species": m.species or "",
        "summary": (m.lore or m.attributes or "")[:200],
        "appearance_chapters": appearances,
    }


def _location_item(l: Location) -> dict:
    return {
        "entity_type": "location",
        "id": l.id,
        "name": l.name,
        "type": l.type or "",
        "tier": l.tier or "",
        "layer": l.layer or "surface",
        "parent_name": l.parent_name or "",
        "importance": l.importance or "",
        "summary": (l.description or "")[:200],
    }


def _foreshadow_item(f: Foreshadow) -> dict:
    return {
        "entity_type": "foreshadow",
        "id": f.id,
        "foreshadow_id": f.foreshadow_id,
        "tier": f.tier or "",
        "status": f.status or "pending",
        "plant_chapter": f.plant_chapter or 0,
        "planned_resolve_chapter": f.planned_resolve_chapter or 0,
        "summary": (f.description or "")[:200],
    }


@router.get("/api/encyclopedia/{project_id}")
def get_encyclopedia(project_id: int, db: Session = Depends(get_db)):
    """百科卡：五类实体摘要列表（含出场章节索引）。"""
    counts = _appearance_counts(db, project_id)

    chars = db.query(Character).filter(Character.project_id == project_id).order_by(Character.id).all()
    factions = db.query(Faction).filter(Faction.project_id == project_id).order_by(Faction.id).all()
    monsters = db.query(Monster).filter(Monster.project_id == project_id).order_by(Monster.id).all()
    locations = db.query(Location).filter(Location.project_id == project_id).order_by(Location.id).all()
    foreshadows = db.query(Foreshadow).filter(Foreshadow.project_id == project_id).order_by(Foreshadow.id).all()

    # 角色/势力/怪物：appearance_chapters（character 按名字，faction/monster 按字符串 id）
    characters = []
    for c in chars:
        appearances = _chapter_list(db, project_id, "character", c.name)
        item = _character_item(c, appearances)
        item["appearance_count"] = len(appearances)
        characters.append(item)

    factions_list = []
    for f in factions:
        appearances = _chapter_list(db, project_id, "faction", str(f.id))
        item = _faction_item(f, appearances)
        item["appearance_count"] = len(appearances)
        factions_list.append(item)

    monsters_list = []
    for m in monsters:
        appearances = _chapter_list(db, project_id, "monster", str(m.id))
        item = _monster_item(m, appearances)
        item["appearance_count"] = len(appearances)
        monsters_list.append(item)

    locations_list = [_location_item(l) for l in locations]
    foreshadows_list = [_foreshadow_item(f) for f in foreshadows]

    return {
        "characters": characters,
        "factions": factions_list,
        "monsters": monsters_list,
        "locations": locations_list,
        "foreshadows": foreshadows_list,
        "counts": {
            "characters": len(characters),
            "factions": len(factions_list),
            "monsters": len(monsters_list),
            "locations": len(locations_list),
            "foreshadows": len(foreshadows_list),
        },
    }
