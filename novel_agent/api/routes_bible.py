"""圣经 CRUD API：角色/伏笔/大纲/摘要 + 创建/编辑/删除/导入。"""
from __future__ import annotations
import json
from fastapi import APIRouter, HTTPException, UploadFile
from pydantic import BaseModel
from novel_agent.bible.database import SessionLocal, set_config
from novel_agent.bible.models import Base, Foreshadow, Character
from novel_agent.bible.repository import BibleRepository
from novel_agent.config import load_config
from novel_agent.templates.loader import PromptLoader

router = APIRouter()


def _repo(project_id: int):
    cfg = load_config()
    set_config(cfg)
    from novel_agent.bible import database as db_mod
    Base.metadata.create_all(bind=db_mod.engine)
    db = SessionLocal()
    return db, BibleRepository(db, project_id=project_id)


# ---- 世界设定 ----
@router.get("/{project_id}/world-settings")
def list_world_settings(project_id: int):
    db, repo = _repo(project_id)
    try:
        return [{"id": w.id, "category": w.category, "title": w.title,
                 "content": w.content, "order": w.order}
                for w in repo.list_world_settings()]
    finally:
        db.close()


class WorldSettingInput(BaseModel):
    category: str = ""
    title: str = ""
    content: str = ""
    order: int = 0


class FactionInput(BaseModel):
    name: str
    alias: str = ""
    type: str = ""
    tier: str = ""
    alignment: str = ""
    description: str = ""
    history: str = ""
    goals: str = ""
    hierarchy: str = ""
    territories: str = ""
    resources: str = ""


class FactionRelationshipInput(BaseModel):
    source_faction_id: int
    target_faction_id: int
    relation_type: str = "neutral"
    strength: int = 0
    description: str = ""
    since_chapter: int = 0
    status: str = "active"


class CharacterRelationshipInput(BaseModel):
    source_character: str
    target_character: str
    relation_type: str = "other"
    relation_subtype: str = ""
    strength: int = 0
    description: str = ""
    since_chapter: int = 0
    status: str = "active"
    is_bidirectional: bool = True


class MonsterInput(BaseModel):
    name: str
    alias: str = ""
    species: str = ""
    rank: str = ""
    tier: str = ""
    attributes: str = ""
    skills: str = ""
    drops: str = ""
    habitats: str = ""
    behavior: str = ""
    weaknesses: str = ""
    lore: str = ""
    first_appearance: int = 0


@router.post("/{project_id}/world-settings")
def create_world_setting(project_id: int, data: WorldSettingInput):
    db, repo = _repo(project_id)
    try:
        w = repo.create_world_setting(**data.model_dump())
        return {"id": w.id, "category": w.category, "title": w.title,
                "content": w.content, "order": w.order}
    finally:
        db.close()


@router.put("/{project_id}/world-settings/{setting_id}")
def update_world_setting(project_id: int, setting_id: int, data: WorldSettingInput):
    db, repo = _repo(project_id)
    try:
        from novel_agent.bible.models import WorldSetting
        w = db.query(WorldSetting).filter(
            WorldSetting.project_id == project_id,
            WorldSetting.id == setting_id).first()
        if not w:
            raise HTTPException(404, "世界设定不存在")
        for k, v in data.model_dump().items():
            setattr(w, k, v)
        db.commit(); db.refresh(w)
        return {"id": w.id, "category": w.category, "title": w.title,
                "content": w.content, "order": w.order}
    finally:
        db.close()


@router.delete("/{project_id}/world-settings/{setting_id}")
def delete_world_setting(project_id: int, setting_id: int):
    db, repo = _repo(project_id)
    try:
        from novel_agent.bible.models import WorldSetting
        w = db.query(WorldSetting).filter(
            WorldSetting.project_id == project_id,
            WorldSetting.id == setting_id).first()
        if not w:
            raise HTTPException(404, "世界设定不存在")
        db.delete(w); db.commit()
        return {"deleted": True}
    finally:
        db.close()


# ---- 角色 ----
@router.get("/{project_id}/characters")
def list_characters(project_id: int):
    db, repo = _repo(project_id)
    try:
        return [_char_dict(c) for c in repo.list_characters()]
    finally:
        db.close()


def _char_dict(c):
    return {"id": c.id, "name": c.name, "role": c.role, "importance": c.importance,
            "personality": c.personality, "motivation": c.motivation,
            "current_location": c.current_location, "current_emotion": c.current_emotion,
            "known_info": c.known_info, "background": c.background, "arc": c.arc,
            "relationships": c.relationships, "secrets": c.secrets}


class CharacterInput(BaseModel):
    name: str
    role: str = ""
    importance: str = ""
    personality: str = ""
    motivation: str = ""
    current_location: str = ""
    current_emotion: str = ""
    known_info: str = ""
    background: str = ""
    arc: str = ""
    relationships: str = ""
    secrets: str = ""


@router.post("/{project_id}/characters")
def create_character(project_id: int, data: CharacterInput):
    db, repo = _repo(project_id)
    try:
        if repo.get_character(data.name):
            raise HTTPException(400, f"角色 {data.name} 已存在")
        c = repo.create_character(**data.model_dump())
        return _char_dict(c)
    finally:
        db.close()


@router.put("/{project_id}/characters/{name}")
def update_character(project_id: int, name: str, data: CharacterInput):
    db, repo = _repo(project_id)
    try:
        c = repo.update_character(name, **data.model_dump())
        if not c:
            raise HTTPException(404, "角色不存在")
        return _char_dict(c)
    finally:
        db.close()


@router.delete("/{project_id}/characters/{name}")
def delete_character(project_id: int, name: str):
    db, repo = _repo(project_id)
    try:
        if not repo.delete_character(name):
            raise HTTPException(404, "角色不存在")
        return {"deleted": True}
    finally:
        db.close()


# ---- 伏笔 ----
@router.get("/{project_id}/foreshadows")
def list_foreshadows(project_id: int):
    db, repo = _repo(project_id)
    try:
        fs = db.query(Foreshadow).filter(Foreshadow.project_id == project_id).all()
        return [{"id": f.foreshadow_id, "foreshadow_id": f.foreshadow_id, "tier": f.tier, "status": f.status,
                 "description": f.description, "plant_chapter": f.plant_chapter,
                 "planned_resolve_chapter": f.planned_resolve_chapter} for f in fs]
    finally:
        db.close()


class ForeshadowInput(BaseModel):
    foreshadow_id: str
    tier: str = ""
    description: str = ""
    plant_chapter: int = 0
    planned_resolve_chapter: int = 0
    status: str = "pending"


@router.post("/{project_id}/foreshadows")
def create_foreshadow(project_id: int, data: ForeshadowInput):
    db, repo = _repo(project_id)
    try:
        if repo.get_foreshadow(data.foreshadow_id):
            raise HTTPException(400, f"伏笔 {data.foreshadow_id} 已存在")
        f = repo.create_foreshadow(**data.model_dump())
        return {"id": f.foreshadow_id, "status": f.status, "description": f.description}
    finally:
        db.close()


@router.put("/{project_id}/foreshadows/{foreshadow_id}")
def update_foreshadow(project_id: int, foreshadow_id: str, data: ForeshadowInput):
    db, repo = _repo(project_id)
    try:
        f = repo.update_foreshadow(foreshadow_id, **data.model_dump())
        if not f:
            raise HTTPException(404, "伏笔不存在")
        return {"id": f.foreshadow_id, "status": f.status, "description": f.description}
    finally:
        db.close()


@router.delete("/{project_id}/foreshadows/{foreshadow_id}")
def delete_foreshadow(project_id: int, foreshadow_id: str):
    db, repo = _repo(project_id)
    try:
        if not repo.delete_foreshadow(foreshadow_id):
            raise HTTPException(404, "伏笔不存在")
        return {"deleted": True}
    finally:
        db.close()


# ---- 大纲 ----
@router.get("/{project_id}/outlines")
def list_outlines(project_id: int, level: str | None = None, parent_id: int | None = None):
    db, repo = _repo(project_id)
    try:
        return [{"id": o.id, "level": o.level, "parent_id": o.parent_id, "order": o.order,
                 "title": o.title, "summary": o.summary, "act": o.act, "strand": o.strand}
                for o in repo.list_outlines(level=level, parent_id=parent_id)]
    finally:
        db.close()


class OutlineInput(BaseModel):
    level: str = "chapter"
    parent_id: int | None = None
    order: int = 0
    act: str = ""
    strand: str = ""
    title: str = ""
    summary: str = ""


@router.post("/{project_id}/outlines")
def create_outline(project_id: int, data: OutlineInput):
    db, repo = _repo(project_id)
    try:
        o = repo.create_outline(**data.model_dump())
        return {"id": o.id, "level": o.level, "parent_id": o.parent_id, "order": o.order,
                "title": o.title, "summary": o.summary, "act": o.act, "strand": o.strand}
    finally:
        db.close()


@router.put("/{project_id}/outlines/{outline_id}")
def update_outline(project_id: int, outline_id: int, data: OutlineInput):
    db, repo = _repo(project_id)
    try:
        o = repo.update_outline(outline_id, **data.model_dump())
        if not o:
            raise HTTPException(404, "大纲条目不存在")
        return {"id": o.id, "level": o.level, "parent_id": o.parent_id, "order": o.order,
                "title": o.title, "summary": o.summary, "act": o.act, "strand": o.strand}
    finally:
        db.close()


@router.delete("/{project_id}/outlines/{outline_id}")
def delete_outline(project_id: int, outline_id: int):
    db, repo = _repo(project_id)
    try:
        if not repo.delete_outline(outline_id):
            raise HTTPException(404, "大纲条目不存在")
        return {"deleted": True}
    finally:
        db.close()


# ---- 摘要（只读 + 删除）----
@router.get("/{project_id}/summaries")
def list_summaries(project_id: int):
    db, repo = _repo(project_id)
    try:
        return [{"chapter": s.chapter, "title": s.title, "core_events": s.core_events,
                 "word_count": s.word_count}
                for s in repo.list_chapter_summaries(limit=100)]
    finally:
        db.close()


@router.delete("/{project_id}/summaries/{chapter}")
def delete_summary(project_id: int, chapter: int):
    db, repo = _repo(project_id)
    try:
        if not repo.delete_chapter_summary(chapter):
            raise HTTPException(404, "摘要不存在")
        return {"deleted": True}
    finally:
        db.close()


# ---- 势力 ----
@router.get("/{project_id}/factions")
def list_factions(project_id: int):
    db, repo = _repo(project_id)
    try:
        return [{"id": f.id, "name": f.name, "alias": f.alias, "type": f.type,
                 "tier": f.tier, "alignment": f.alignment, "description": f.description,
                 "history": f.history, "goals": f.goals, "hierarchy": f.hierarchy,
                 "territories": f.territories, "resources": f.resources} for f in repo.list_factions()]
    finally:
        db.close()


@router.post("/{project_id}/factions")
def create_faction(project_id: int, data: FactionInput):
    db, repo = _repo(project_id)
    try:
        if repo.get_faction_by_name(data.name):
            raise HTTPException(409, "势力名称已存在")
        f = repo.create_faction(**data.model_dump())
        return {"id": f.id, "name": f.name, "alias": f.alias, "type": f.type,
                "tier": f.tier, "alignment": f.alignment, "description": f.description,
                "history": f.history, "goals": f.goals, "hierarchy": f.hierarchy,
                "territories": f.territories, "resources": f.resources}
    finally:
        db.close()


@router.put("/{project_id}/factions/{faction_id}")
def update_faction(project_id: int, faction_id: int, data: FactionInput):
    db, repo = _repo(project_id)
    try:
        from novel_agent.bible.models import Faction
        f = db.query(Faction).filter(Faction.project_id == project_id, Faction.id == faction_id).first()
        if not f:
            raise HTTPException(404, "势力不存在")
        for k, v in data.model_dump().items():
            setattr(f, k, v)
        db.commit(); db.refresh(f)
        return {"id": f.id, "name": f.name, "alias": f.alias, "type": f.type,
                "tier": f.tier, "alignment": f.alignment, "description": f.description,
                "history": f.history, "goals": f.goals, "hierarchy": f.hierarchy,
                "territories": f.territories, "resources": f.resources}
    finally:
        db.close()


@router.delete("/{project_id}/factions/{faction_id}")
def delete_faction(project_id: int, faction_id: int):
    db, repo = _repo(project_id)
    try:
        if not repo.delete_faction(faction_id):
            raise HTTPException(404, "势力不存在")
        return {"deleted": True}
    finally:
        db.close()


# ---- 势力关系 ----
@router.get("/{project_id}/faction-relationships")
def list_faction_relationships(project_id: int):
    db, repo = _repo(project_id)
    try:
        return [{"id": r.id, "source_faction_id": r.source_faction_id, "target_faction_id": r.target_faction_id,
                 "relation_type": r.relation_type, "strength": r.strength, "description": r.description,
                 "since_chapter": r.since_chapter, "status": r.status} for r in repo.list_faction_relationships()]
    finally:
        db.close()


@router.post("/{project_id}/faction-relationships")
def create_faction_relationship(project_id: int, data: FactionRelationshipInput):
    db, repo = _repo(project_id)
    try:
        r = repo.create_faction_relationship(**data.model_dump())
        return {"id": r.id, "source_faction_id": r.source_faction_id, "target_faction_id": r.target_faction_id,
                "relation_type": r.relation_type, "strength": r.strength, "description": r.description,
                "since_chapter": r.since_chapter, "status": r.status}
    finally:
        db.close()


@router.put("/{project_id}/faction-relationships/{rel_id}")
def update_faction_relationship(project_id: int, rel_id: int, data: FactionRelationshipInput):
    db, repo = _repo(project_id)
    try:
        from novel_agent.bible.models import FactionRelationship
        r = db.query(FactionRelationship).filter(FactionRelationship.project_id == project_id, FactionRelationship.id == rel_id).first()
        if not r:
            raise HTTPException(404, "关系不存在")
        for k, v in data.model_dump().items():
            setattr(r, k, v)
        db.commit(); db.refresh(r)
        return {"id": r.id, "source_faction_id": r.source_faction_id, "target_faction_id": r.target_faction_id,
                "relation_type": r.relation_type, "strength": r.strength, "description": r.description,
                "since_chapter": r.since_chapter, "status": r.status}
    finally:
        db.close()


@router.delete("/{project_id}/faction-relationships/{rel_id}")
def delete_faction_relationship(project_id: int, rel_id: int):
    db, repo = _repo(project_id)
    try:
        if not repo.delete_faction_relationship(rel_id):
            raise HTTPException(404, "关系不存在")
        return {"deleted": True}
    finally:
        db.close()


# ---- 人物关系 ----
@router.get("/{project_id}/character-relationships")
def list_character_relationships(project_id: int):
    db, repo = _repo(project_id)
    try:
        return [{"id": r.id, "source_character": r.source_character, "target_character": r.target_character,
                 "relation_type": r.relation_type, "relation_subtype": r.relation_subtype, "strength": r.strength,
                 "description": r.description, "since_chapter": r.since_chapter, "status": r.status,
                 "is_bidirectional": r.is_bidirectional} for r in repo.list_character_relationships()]
    finally:
        db.close()


@router.post("/{project_id}/character-relationships")
def create_character_relationship(project_id: int, data: CharacterRelationshipInput):
    db, repo = _repo(project_id)
    try:
        r = repo.create_character_relationship(**data.model_dump())
        return {"id": r.id, "source_character": r.source_character, "target_character": r.target_character,
                "relation_type": r.relation_type, "relation_subtype": r.relation_subtype, "strength": r.strength,
                "description": r.description, "since_chapter": r.since_chapter, "status": r.status,
                "is_bidirectional": r.is_bidirectional}
    finally:
        db.close()


@router.put("/{project_id}/character-relationships/{rel_id}")
def update_character_relationship(project_id: int, rel_id: int, data: CharacterRelationshipInput):
    db, repo = _repo(project_id)
    try:
        from novel_agent.bible.models import CharacterRelationship
        r = db.query(CharacterRelationship).filter(CharacterRelationship.project_id == project_id, CharacterRelationship.id == rel_id).first()
        if not r:
            raise HTTPException(404, "关系不存在")
        for k, v in data.model_dump().items():
            setattr(r, k, v)
        db.commit(); db.refresh(r)
        return {"id": r.id, "source_character": r.source_character, "target_character": r.target_character,
                "relation_type": r.relation_type, "relation_subtype": r.relation_subtype, "strength": r.strength,
                "description": r.description, "since_chapter": r.since_chapter, "status": r.status,
                "is_bidirectional": r.is_bidirectional}
    finally:
        db.close()


@router.delete("/{project_id}/character-relationships/{rel_id}")
def delete_character_relationship(project_id: int, rel_id: int):
    db, repo = _repo(project_id)
    try:
        if not repo.delete_character_relationship(rel_id):
            raise HTTPException(404, "关系不存在")
        return {"deleted": True}
    finally:
        db.close()


# ---- 怪物 ----
@router.get("/{project_id}/monsters")
def list_monsters(project_id: int):
    db, repo = _repo(project_id)
    try:
        return [{"id": m.id, "name": m.name, "alias": m.alias, "species": m.species,
                 "rank": m.rank, "tier": m.tier, "attributes": m.attributes, "skills": m.skills,
                 "drops": m.drops, "habitats": m.habitats, "behavior": m.behavior,
                 "weaknesses": m.weaknesses, "lore": m.lore,
                 "first_appearance": m.first_appearance} for m in repo.list_monsters()]
    finally:
        db.close()


@router.post("/{project_id}/monsters")
def create_monster(project_id: int, data: MonsterInput):
    db, repo = _repo(project_id)
    try:
        if repo.get_monster_by_name(data.name):
            raise HTTPException(409, "怪物名称已存在")
        m = repo.create_monster(**data.model_dump())
        return {"id": m.id, "name": m.name, "alias": m.alias, "species": m.species,
                "rank": m.rank, "tier": m.tier, "attributes": m.attributes, "skills": m.skills,
                "drops": m.drops, "habitats": m.habitats, "behavior": m.behavior,
                "weaknesses": m.weaknesses, "lore": m.lore,
                "first_appearance": m.first_appearance}
    finally:
        db.close()


@router.put("/{project_id}/monsters/{monster_id}")
def update_monster(project_id: int, monster_id: int, data: MonsterInput):
    db, repo = _repo(project_id)
    try:
        from novel_agent.bible.models import Monster
        m = db.query(Monster).filter(Monster.project_id == project_id, Monster.id == monster_id).first()
        if not m:
            raise HTTPException(404, "怪物不存在")
        for k, v in data.model_dump().items():
            setattr(m, k, v)
        db.commit(); db.refresh(m)
        return {"id": m.id, "name": m.name, "alias": m.alias, "species": m.species,
                "rank": m.rank, "tier": m.tier, "attributes": m.attributes, "skills": m.skills,
                "drops": m.drops, "habitats": m.habitats, "behavior": m.behavior,
                "weaknesses": m.weaknesses, "lore": m.lore,
                "first_appearance": m.first_appearance}
    finally:
        db.close()


@router.delete("/{project_id}/monsters/{monster_id}")
def delete_monster(project_id: int, monster_id: int):
    db, repo = _repo(project_id)
    try:
        if not repo.delete_monster(monster_id):
            raise HTTPException(404, "怪物不存在")
        return {"deleted": True}
    finally:
        db.close()


# ---- 实体出场 ----
def _appearance_dict(a):
    return {
        "id": a.id,
        "project_id": a.project_id,
        "entity_type": a.entity_type,
        "entity_id": a.entity_id,
        "chapter": a.chapter,
        "role_in_chapter": a.role_in_chapter,
        "context_snippet": a.context_snippet,
        "created_at": a.created_at,
        "updated_at": a.updated_at,
    }


class EntityAppearanceInput(BaseModel):
    entity_type: str
    entity_id: str
    chapter: int
    role_in_chapter: str = "mention"
    context_snippet: str = ""


class EntityAppearanceUpdateInput(BaseModel):
    entity_type: str | None = None
    entity_id: str | None = None
    chapter: int | None = None
    role_in_chapter: str | None = None
    context_snippet: str | None = None


class RecordAppearancesInput(BaseModel):
    appearances: list[EntityAppearanceInput]


@router.get("/{project_id}/entity-appearances")
def list_entity_appearances(project_id: int, entity_type: str | None = None,
                            entity_id: str | None = None, chapter: int | None = None):
    db, repo = _repo(project_id)
    try:
        return [_appearance_dict(a) for a in repo.list_entity_appearances(
            entity_type=entity_type, entity_id=entity_id, chapter=chapter)]
    finally:
        db.close()


@router.post("/{project_id}/entity-appearances")
def create_entity_appearance(project_id: int, data: EntityAppearanceInput):
    db, repo = _repo(project_id)
    try:
        a = repo.create_entity_appearance(**data.model_dump())
        return _appearance_dict(a)
    finally:
        db.close()


@router.put("/{project_id}/entity-appearances/{appearance_id}")
def update_entity_appearance(project_id: int, appearance_id: int, data: EntityAppearanceUpdateInput):
    from novel_agent.bible.models import EntityAppearance
    db, repo = _repo(project_id)
    try:
        a = db.query(EntityAppearance).filter(
            EntityAppearance.project_id == project_id,
            EntityAppearance.id == appearance_id,
        ).first()
        if not a:
            raise HTTPException(404, "出场记录不存在")
        for k, v in data.model_dump(exclude_unset=True).items():
            if v is not None:
                setattr(a, k, v)
        db.commit(); db.refresh(a)
        return _appearance_dict(a)
    finally:
        db.close()


@router.delete("/{project_id}/entity-appearances/{appearance_id}")
def delete_entity_appearance(project_id: int, appearance_id: int):
    db, repo = _repo(project_id)
    try:
        if not repo.delete_entity_appearance(appearance_id):
            raise HTTPException(404, "出场记录不存在")
        return {"deleted": True}
    finally:
        db.close()


@router.post("/{project_id}/chapters/{chapter}/record-appearances")
def record_appearances(project_id: int, chapter: int, data: RecordAppearancesInput):
    db, repo = _repo(project_id)
    try:
        created = repo.record_appearances(chapter, [a.model_dump() for a in data.appearances])
        return {"chapter": chapter, "recorded": len(created),
                "appearances": [_appearance_dict(a) for a in created]}
    finally:
        db.close()


# ---- AI 生成 ----
class GenerateFactionRequest(BaseModel):
    name_hint: str = ""
    type: str = ""
    alignment: str = ""


class GenerateMonsterRequest(BaseModel):
    name_hint: str = ""
    rank: str = ""
    species: str = ""


class GenerateCharacterRequest(BaseModel):
    name_hint: str = ""
    role_hint: str = ""
    importance_hint: str = ""


class GenerateCharacterRelationshipRequest(BaseModel):
    source_character: str
    target_character: str
    relation_type_hint: str = ""


def _clean_text(text: Any) -> str:
    if text is None:
        return ""
    return str(text).strip()


def _extract_json(text: str) -> dict:
    import re
    m = re.search(r"```(?:json)?\s*\n?(.*?)\n?```", text, re.DOTALL)
    candidate = m.group(1) if m else text
    try:
        return json.loads(candidate)
    except json.JSONDecodeError:
        start = candidate.find("{")
        end = candidate.rfind("}")
        if start >= 0 and end > start:
            try:
                return json.loads(candidate[start:end + 1])
            except json.JSONDecodeError:
                return {}
        return {}


@router.post("/{project_id}/generate-faction")
async def generate_faction(project_id: int, req: GenerateFactionRequest):
    from novel_agent.llm.client import LLMClient

    cfg = load_config()
    db, repo = _repo(project_id)
    try:
        project = repo.get_project()
        if not project:
            raise HTTPException(404, "项目不存在")
        client = LLMClient(cfg.llm)
        context = (
            f"标题：{project.title}\n类型：{project.genre}\n简介：{project.summary}\n"
            f"文风：{project.style}\n"
        )
        existing = repo.list_factions()
        if existing:
            context += "\n已有势力：\n" + "\n".join(f"- {f.name}（{f.type or '未分类'} / {f.tier or '未分级'}）" for f in existing)
        prompt = (
            f"请基于以下小说上下文，生成一个新的势力设定。\n\n{context}\n\n"
            f"生成要求：\n- 名称提示：{req.name_hint or '无'}\n"
            f"- 类型提示：{req.type or '无'}\n- 阵营提示：{req.alignment or '无'}\n\n"
            "请输出 JSON：{\"name\":\"\",\"alias\":\"\",\"type\":\"\",\"tier\":\"\",\"alignment\":\"\",\"description\":\"\",\"history\":\"\",\"goals\":\"\",\"hierarchy\":\"\",\"territories\":\"\",\"resources\":\"\"}\n"
            "tier 建议取值：顶级势力、一流势力、二流势力、三流势力、隐世势力。只输出 JSON，不要 markdown 代码块。"
        )
        raw = await client.generate(prompt, system="你是网文设定师，擅长设计势力组织。只输出 JSON。")
        result = _extract_json(raw)
        data = {k: _clean_text(result.get(k, "")) for k in FactionInput.model_fields}
        if not data.get("name"):
            data["name"] = req.name_hint or f"生成势力{len(existing) + 1}"
        if repo.get_faction_by_name(data["name"]):
            raise HTTPException(409, "同名势力已存在")
        f = repo.create_faction(**data)
        return {"id": f.id, "name": f.name, "alias": f.alias, "type": f.type,
                "tier": f.tier, "alignment": f.alignment, "description": f.description,
                "history": f.history, "goals": f.goals, "hierarchy": f.hierarchy,
                "territories": f.territories, "resources": f.resources}
    finally:
        db.close()


@router.post("/{project_id}/generate-monster")
async def generate_monster(project_id: int, req: GenerateMonsterRequest):
    from novel_agent.llm.client import LLMClient

    cfg = load_config()
    db, repo = _repo(project_id)
    try:
        project = repo.get_project()
        if not project:
            raise HTTPException(404, "项目不存在")
        client = LLMClient(cfg.llm)
        context = (
            f"标题：{project.title}\n类型：{project.genre}\n简介：{project.summary}\n"
            f"文风：{project.style}\n"
        )
        existing = repo.list_monsters()
        if existing:
            context += "\n已有怪物：\n" + "\n".join(f"- {m.name}（{m.species or '未知'} / {m.tier or '未分级'}）" for m in existing)
        prompt = (
            f"请基于以下小说上下文，生成一个新的怪物图鉴。\n\n{context}\n\n"
            f"生成要求：\n- 名称提示：{req.name_hint or '无'}\n"
            f"- 等级提示：{req.rank or '无'}\n- 物种提示：{req.species or '无'}\n\n"
            "请输出 JSON：{\"name\":\"\",\"alias\":\"\",\"species\":\"\",\"rank\":\"\",\"tier\":\"\",\"attributes\":\"\",\"skills\":\"\",\"drops\":\"\",\"habitats\":\"\",\"behavior\":\"\",\"weaknesses\":\"\",\"lore\":\"\",\"first_appearance\":0}\n"
            "tier 建议取值：BOSS、精英、首领、小怪、普通。只输出 JSON，不要 markdown 代码块。"
        )
        raw = await client.generate(prompt, system="你是网文怪物设计师，擅长设计有特色的怪物。只输出 JSON。")
        result = _extract_json(raw)
        data = {k: _clean_text(result.get(k, "")) for k in MonsterInput.model_fields}
        if "first_appearance" in result:
            data["first_appearance"] = result.get("first_appearance", 0)
        if not data.get("name"):
            data["name"] = req.name_hint or f"生成怪物{len(existing) + 1}"
        if repo.get_monster_by_name(data["name"]):
            raise HTTPException(409, "同名怪物已存在")
        m = repo.create_monster(**data)
        return {"id": m.id, "name": m.name, "alias": m.alias, "species": m.species,
                "rank": m.rank, "tier": m.tier, "attributes": m.attributes, "skills": m.skills,
                "drops": m.drops, "habitats": m.habitats, "behavior": m.behavior,
                "weaknesses": m.weaknesses, "lore": m.lore,
                "first_appearance": m.first_appearance}
    finally:
        db.close()


@router.post("/{project_id}/generate-character-relationship")
async def generate_character_relationship(project_id: int, req: GenerateCharacterRelationshipRequest):
    from novel_agent.llm.client import LLMClient

    cfg = load_config()
    db, repo = _repo(project_id)
    try:
        project = repo.get_project()
        if not project:
            raise HTTPException(404, "项目不存在")
        source = repo.get_character(req.source_character)
        target = repo.get_character(req.target_character)
        if not source or not target:
            raise HTTPException(404, "源角色或目标角色不存在")
        client = LLMClient(cfg.llm)
        context = (
            f"标题：{project.title}\n类型：{project.genre}\n简介：{project.summary}\n"
            f"文风：{project.style}\n\n"
            f"源角色：{source.name}\n角色身份：{source.role}\n性格：{source.personality}\n"
            f"目标角色：{target.name}\n角色身份：{target.role}\n性格：{target.personality}\n"
        )
        prompt = (
            f"请基于以下角色与小说上下文，生成一段人物关系设定。\n\n{context}\n\n"
            f"关系类型提示：{req.relation_type_hint or '无'}\n\n"
            "请输出 JSON：{\"relation_type\":\"\",\"relation_subtype\":\"\",\"strength\":0,\"description\":\"\",\"since_chapter\":0,\"status\":\"active\",\"is_bidirectional\":true}\n"
            "strength 为 0-10 的整数。只输出 JSON，不要 markdown 代码块。"
        )
        raw = await client.generate(prompt, system="你是网文关系设计师，擅长设计立体的人物关系。只输出 JSON。")
        result = _extract_json(raw)
        data = {
            "source_character": source.name,
            "target_character": target.name,
            "relation_type": _clean_text(result.get("relation_type", "other")) or "other",
            "relation_subtype": _clean_text(result.get("relation_subtype", "")),
            "strength": int(result.get("strength", 0)) if str(result.get("strength", "")).isdigit() else 0,
            "description": _clean_text(result.get("description", "")),
            "since_chapter": int(result.get("since_chapter", 0)) if str(result.get("since_chapter", "")).isdigit() else 0,
            "status": _clean_text(result.get("status", "active")) or "active",
            "is_bidirectional": bool(result.get("is_bidirectional", True)),
        }
        r = repo.create_character_relationship(**data)
        return {"id": r.id, "source_character": r.source_character, "target_character": r.target_character,
                "relation_type": r.relation_type, "relation_subtype": r.relation_subtype, "strength": r.strength,
                "description": r.description, "since_chapter": r.since_chapter, "status": r.status,
                "is_bidirectional": r.is_bidirectional}
    finally:
        db.close()


@router.post("/{project_id}/generate-character")
async def generate_character(project_id: int, req: GenerateCharacterRequest):
    from novel_agent.llm.client import LLMClient

    cfg = load_config()
    db, repo = _repo(project_id)
    try:
        project = repo.get_project()
        if not project:
            raise HTTPException(404, "项目不存在")
        client = LLMClient(cfg.llm)
        context = (
            f"标题：{project.title}\n类型：{project.genre}\n简介：{project.summary}\n"
            f"文风：{project.style}\n"
        )
        existing = repo.list_characters()
        if existing:
            context += "\n已有角色：\n" + "\n".join(
                f"- {c.name}（{c.role or '无身份'} / {c.importance or '未分级'}）" for c in existing
            )
        prompt = (
            f"请基于以下小说上下文，生成一个新的角色设定。\n\n{context}\n\n"
            f"生成要求：\n- 名称提示：{req.name_hint or '无'}\n"
            f"- 身份提示：{req.role_hint or '无'}\n"
            f"- 重要性提示：{req.importance_hint or '无'}\n\n"
            "请输出 JSON：{\"name\":\"\",\"role\":\"\",\"personality\":\"\",\"background\":\"\",\"goals\":\"\",\"abilities\":\"\",\"appearance\":\"\",\"importance\":\"\"}\n"
            "importance 建议取值：主角、配角、关键人物、小人物、NPC。只输出 JSON，不要 markdown 代码块。"
        )
        raw = await client.generate(prompt, system="你是网文角色设计师，擅长设计立体角色。只输出 JSON。")
        result = _extract_json(raw)
        data = {k: _clean_text(result.get(k, "")) for k in CharacterInput.model_fields}
        if not data.get("name"):
            data["name"] = req.name_hint or f"生成角色{len(existing) + 1}"
        if repo.get_character(data["name"]):
            raise HTTPException(409, "同名角色已存在")
        c = repo.create_character(**data)
        return {"id": c.id, "name": c.name, "role": c.role, "personality": c.personality,
                "background": c.background, "goals": c.goals, "abilities": c.abilities,
                "appearance": c.appearance, "importance": c.importance}
    finally:
        db.close()


# ---- 批量导入 ----
class ImportData(BaseModel):
    """批量导入设定数据（世界观/势力/关系/角色/伏笔/大纲/怪物）。"""
    world_settings: list[WorldSettingInput] = []
    factions: list[FactionInput] = []
    faction_relationships: list[FactionRelationshipInput] = []
    character_relationships: list[CharacterRelationshipInput] = []
    characters: list[CharacterInput] = []
    foreshadows: list[ForeshadowInput] = []
    outlines: list[OutlineInput] = []
    monsters: list[MonsterInput] = []


@router.post("/{project_id}/import")
def import_settings(project_id: int, data: ImportData):
    """批量导入世界观/设定数据。已存在的跳过。"""
    db, repo = _repo(project_id)
    try:
        added = _apply_import_data(repo, data)
        return {"imported": added}
    finally:
        db.close()


def _apply_import_data(repo: BibleRepository, data: ImportData) -> dict:
    added = {"world_settings": 0, "characters": 0, "foreshadows": 0, "outlines": 0,
             "factions": 0, "faction_relationships": 0, "character_relationships": 0, "monsters": 0}
    for w in data.world_settings:
        repo.create_world_setting(**w.model_dump())
        added["world_settings"] += 1
    for f in data.factions:
        if not repo.get_faction_by_name(f.name):
            repo.create_faction(**f.model_dump())
            added["factions"] += 1
    for r in data.faction_relationships:
        repo.create_faction_relationship(**r.model_dump())
        added["faction_relationships"] += 1
    for r in data.character_relationships:
        repo.create_character_relationship(**r.model_dump())
        added["character_relationships"] += 1
    for c in data.characters:
        if not repo.get_character(c.name):
            repo.create_character(**c.model_dump())
            added["characters"] += 1
    for f in data.foreshadows:
        if not repo.get_foreshadow(f.foreshadow_id):
            repo.create_foreshadow(**f.model_dump())
            added["foreshadows"] += 1
    for o in data.outlines:
        repo.create_outline(**o.model_dump())
        added["outlines"] += 1
    for m in data.monsters:
        if not repo.get_monster_by_name(m.name):
            repo.create_monster(**m.model_dump())
            added["monsters"] += 1
    return added


# ---- 文档导入：用 LLM 从自然语言文档中提取设定 ----
class DocumentImportInput(BaseModel):
    content: str


async def _parse_text(client, text: str) -> ImportData:
    """将已提取的文本通过 LLM 解析为 ImportData，不写入数据库。"""
    import json
    import re

    prompt = PromptLoader().render("import_parse", document=text)
    try:
        raw = await client.generate(prompt, system="你是小说设定解析助手。")
    except Exception as e:
        raise HTTPException(502, f"LLM 解析失败: {e}")

    parsed = await _extract_json_with_repair(client, raw)

    return ImportData(
        world_settings=[WorldSettingInput(**w) for w in parsed.get("world_settings", [])],
        factions=[FactionInput(**x) for x in parsed.get("factions", [])],
        faction_relationships=[FactionRelationshipInput(**x) for x in parsed.get("faction_relationships", [])],
        character_relationships=[CharacterRelationshipInput(**x) for x in parsed.get("character_relationships", [])],
        characters=[CharacterInput(**c) for c in parsed.get("characters", [])],
        foreshadows=[ForeshadowInput(**f) for f in parsed.get("foreshadows", [])],
        outlines=[OutlineInput(**o) for o in parsed.get("outlines", [])],
        monsters=[MonsterInput(**x) for x in parsed.get("monsters", [])],
    )


def _try_parse_json(raw: str):
    """尝试从文本中提取并解析 JSON，成功返回 dict，失败返回 None。"""
    import json
    import re

    # 先直接尝试
    raw = raw.strip()
    if raw.startswith("```"):
        raw = re.sub(r"^```(?:json)?\s*", "", raw, flags=re.IGNORECASE)
        raw = re.sub(r"\s*```$", "", raw)
    try:
        return json.loads(raw)
    except Exception:
        pass

    # 尝试匹配最外层 { ... }
    m = re.search(r"\{[\s\S]*\}", raw)
    if m:
        try:
            return json.loads(m.group(0))
        except Exception:
            pass
    return None


async def _extract_json_with_repair(client, raw: str) -> dict:
    """解析 LLM 返回的 JSON，失败时尝试自动修复或请 LLM 自我修复。"""
    import json

    parsed = _try_parse_json(raw)
    if parsed is not None:
        return parsed

    # 第一次自我修复：请 LLM 把这段输出改成合法 JSON
    repair_prompt = (
        "下面这段内容本应是 JSON，但解析时报错。请只输出修复后的合法 JSON，不要任何解释。\n\n"
        f"{raw[:4000]}"
    )
    try:
        fixed = await client.generate(repair_prompt, system="你是 JSON 修复助手，只输出合法 JSON。")
    except Exception as e:
        raise HTTPException(400, f"LLM 返回的 JSON 格式错误，且自动修复失败: {e}")

    parsed = _try_parse_json(fixed)
    if parsed is not None:
        return parsed

    raise HTTPException(400, "LLM 返回的 JSON 格式错误，自动修复后仍无法解析。请简化文档后重试。")


async def _import_from_text(repo: BibleRepository, client, text: str) -> dict:
    """将已提取的文本通过 LLM 解析并导入圣经。"""
    import_data = await _parse_text(client, text)
    added = _apply_import_data(repo, import_data)
    return {"imported": added, "raw_summary": {"world_settings": len(import_data.world_settings),
                                               "factions": len(import_data.factions),
                                               "faction_relationships": len(import_data.faction_relationships),
                                               "character_relationships": len(import_data.character_relationships),
                                               "characters": len(import_data.characters),
                                               "foreshadows": len(import_data.foreshadows),
                                               "outlines": len(import_data.outlines),
                                               "monsters": len(import_data.monsters)}}


@router.post("/{project_id}/parse-document")
async def parse_document(project_id: int, data: DocumentImportInput):
    """从自然语言文档中提取角色/伏笔/大纲，返回结构化数据供前端预览筛选。"""
    from novel_agent.llm.client import LLMClient

    cfg = load_config()
    db, repo = _repo(project_id)
    try:
        client = LLMClient(cfg.llm)
        import_data = await _parse_text(client, data.content)
        return {
            "world_settings": [w.model_dump() for w in import_data.world_settings],
            "factions": [f.model_dump() for f in import_data.factions],
            "faction_relationships": [r.model_dump() for r in import_data.faction_relationships],
            "character_relationships": [r.model_dump() for r in import_data.character_relationships],
            "characters": [c.model_dump() for c in import_data.characters],
            "foreshadows": [f.model_dump() for f in import_data.foreshadows],
            "outlines": [o.model_dump() for o in import_data.outlines],
            "monsters": [m.model_dump() for m in import_data.monsters],
        }
    finally:
        db.close()


@router.post("/{project_id}/import-document")
async def import_document(project_id: int, data: DocumentImportInput):
    """从自然语言文档中提取角色/伏笔/大纲并导入圣经。"""
    from novel_agent.llm.client import LLMClient

    cfg = load_config()
    db, repo = _repo(project_id)
    try:
        client = LLMClient(cfg.llm)
        return await _import_from_text(repo, client, data.content)
    finally:
        db.close()


async def _parse_file_content(client, cfg, file: UploadFile) -> ImportData:
    """上传文件并解析为 ImportData，不写入数据库。"""
    from novel_agent.utils.file_extract import extract_text_or_image

    content, is_image = await extract_text_or_image(file)

    if is_image:
        if not cfg.llm.vision_enabled:
            raise HTTPException(400, "图片导入需要配置 llm.vision_enabled=true 并使用支持视觉的模型")
        vision_prompt = PromptLoader().render("import_image_parse")
        try:
            raw = await client.generate(vision_prompt, system="你是小说设定解析助手。", images=[content])
        except Exception as e:
            raise HTTPException(502, f"视觉解析失败: {e}")
        import re, json
        m = re.search(r"\{.*\}", raw, re.DOTALL)
        if not m:
            raise HTTPException(400, "LLM 未返回可解析的 JSON")
        parsed = json.loads(m.group(0))
        return ImportData(
            world_settings=[WorldSettingInput(**w) for w in parsed.get("world_settings", [])],
            factions=[FactionInput(**x) for x in parsed.get("factions", [])],
            faction_relationships=[FactionRelationshipInput(**x) for x in parsed.get("faction_relationships", [])],
            character_relationships=[CharacterRelationshipInput(**x) for x in parsed.get("character_relationships", [])],
            characters=[CharacterInput(**c) for c in parsed.get("characters", [])],
            foreshadows=[ForeshadowInput(**f) for f in parsed.get("foreshadows", [])],
            outlines=[OutlineInput(**o) for o in parsed.get("outlines", [])],
            monsters=[MonsterInput(**x) for x in parsed.get("monsters", [])],
        )

    return await _parse_text(client, content)


@router.post("/{project_id}/parse-file")
async def parse_file(project_id: int, file: UploadFile):
    """上传文件并提取角色/伏笔/大纲，返回结构化数据供前端预览筛选。"""
    from novel_agent.llm.client import LLMClient

    cfg = load_config()
    db, repo = _repo(project_id)
    try:
        client = LLMClient(cfg.llm)
        import_data = await _parse_file_content(client, cfg, file)
        return {
            "world_settings": [w.model_dump() for w in import_data.world_settings],
            "factions": [f.model_dump() for f in import_data.factions],
            "faction_relationships": [r.model_dump() for r in import_data.faction_relationships],
            "character_relationships": [r.model_dump() for r in import_data.character_relationships],
            "characters": [c.model_dump() for c in import_data.characters],
            "foreshadows": [f.model_dump() for f in import_data.foreshadows],
            "outlines": [o.model_dump() for o in import_data.outlines],
            "monsters": [m.model_dump() for m in import_data.monsters],
        }
    finally:
        db.close()


@router.post("/{project_id}/import-file")
async def import_file(project_id: int, file: UploadFile):
    """上传文件（txt/md/json/csv/html/docx/pdf/图片等）并提取内容导入圣经。

    图片需 LLM 开启 vision_enabled，否则返回错误。
    """
    from novel_agent.llm.client import LLMClient

    cfg = load_config()
    db, repo = _repo(project_id)
    try:
        client = LLMClient(cfg.llm)
        import_data = await _parse_file_content(client, cfg, file)
        added = _apply_import_data(repo, import_data)
        return {"imported": added, "raw_summary": {"world_settings": len(import_data.world_settings),
                                                   "factions": len(import_data.factions),
                                                   "faction_relationships": len(import_data.faction_relationships),
                                                   "character_relationships": len(import_data.character_relationships),
                                                   "characters": len(import_data.characters),
                                                   "foreshadows": len(import_data.foreshadows),
                                                   "outlines": len(import_data.outlines),
                                                   "monsters": len(import_data.monsters)}}
    finally:
        db.close()


@router.get("/{project_id}/consistency-dashboard")
def consistency_dashboard(project_id: int):
    """项目级一致性看板：状态变更、未回收伏笔、近期事件、冲突检测。"""
    db, repo = _repo(project_id)
    try:
        # 最近状态变更
        state_changes = repo.list_state_changes()[-20:]
        # 未回收伏笔
        foreshadows = repo.list_foreshadows()
        max_chapter = max((o.order for o in repo.list_outlines()), default=0)
        unresolved = [f for f in foreshadows if f.status not in ("resolved", "abandoned")]
        overdue = [f for f in unresolved if (f.planned_resolve_chapter or 0) > 0 and (f.planned_resolve_chapter or 0) < max_chapter]
        # 近期事件
        events = repo.list_events()[-20:]
        # 冲突检测
        conflicts = _detect_conflicts(repo, state_changes, foreshadows, max_chapter)

        factions = repo.list_factions()
        faction_relationships = repo.list_faction_relationships()
        character_relationships = repo.list_character_relationships()
        monsters = repo.list_monsters()

        return {
            "stats": {
                "characters": len(repo.list_characters()),
                "world_settings": len(repo.list_world_settings()),
                "outlines": len(repo.list_outlines()),
                "foreshadows": len(foreshadows),
                "unresolved_foreshadows": len(unresolved),
                "overdue_foreshadows": len(overdue),
                "state_changes": len(repo.list_state_changes()),
                "events": len(repo.list_events()),
                "conflicts": len(conflicts),
                "factions": len(factions),
                "faction_relationships": len(faction_relationships),
                "character_relationships": len(character_relationships),
                "monsters": len(monsters),
            },
            "recent_state_changes": [_state_change_dict(s) for s in state_changes],
            "unresolved_foreshadows": [_foreshadow_dict(f) for f in unresolved],
            "overdue_foreshadows": [_foreshadow_dict(f) for f in overdue],
            "recent_events": [_event_dict(e) for e in events],
            "conflicts": conflicts,
        }
    finally:
        db.close()


def _detect_conflicts(repo, state_changes, foreshadows, max_chapter):
    """基础冲突检测。"""
    conflicts = []

    # 1. 同一实体同一字段短时间内连续变更且链断裂
    by_entity_field: dict[tuple[str, str, str], list] = {}
    for s in state_changes:
        key = (s.entity_type or "", s.entity_id or "", s.field or "")
        by_entity_field.setdefault(key, []).append(s)
    for (etype, eid, field), changes in by_entity_field.items():
        changes_sorted = sorted(changes, key=lambda x: (x.chapter or 0, x.created_at or ""))
        for i in range(1, len(changes_sorted)):
            prev = changes_sorted[i - 1]
            curr = changes_sorted[i]
            if curr.old_value != prev.new_value:
                conflicts.append({
                    "type": "state_chain_break",
                    "severity": "high",
                    "entity_type": etype,
                    "entity_id": eid,
                    "field": field,
                    "message": f"{etype} {eid} 的 {field} 在章节 {prev.chapter}→{curr.chapter} 间链断裂：{prev.new_value} ≠ {curr.old_value}",
                })

    # 2. 伏笔超期未回收
    for f in foreshadows:
        if f.status not in ("resolved", "abandoned") and (f.planned_resolve_chapter or 0) > 0 and (f.planned_resolve_chapter or 0) < max_chapter:
            conflicts.append({
                "type": "foreshadow_overdue",
                "severity": "medium",
                "foreshadow_id": f.foreshadow_id,
                "message": f"伏笔 {f.foreshadow_id} 计划在第 {f.planned_resolve_chapter} 章回收，但当前已写到第 {max_chapter} 章仍未回收",
            })

    # 3. 大纲序号不连续
    outlines = sorted(repo.list_outlines(), key=lambda o: o.order)
    for i in range(1, len(outlines)):
        if outlines[i].order != outlines[i - 1].order + 1:
            conflicts.append({
                "type": "outline_gap",
                "severity": "low",
                "message": f"大纲序号不连续：第 {outlines[i - 1].order} 章后直接跳到第 {outlines[i].order} 章",
            })

    # 4. 势力关系指向不存在的势力
    faction_ids = {f.id for f in repo.list_factions()}
    for r in repo.list_faction_relationships():
        if r.source_faction_id not in faction_ids or r.target_faction_id not in faction_ids:
            conflicts.append({
                "type": "faction_relationship_dangling",
                "severity": "high",
                "relationship_id": r.id,
                "message": f"势力关系 #{r.id} 指向了不存在的势力",
            })

    # 5. 人物关系指向不存在的角色
    character_names = {c.name for c in repo.list_characters()}
    for r in repo.list_character_relationships():
        if r.source_character not in character_names or r.target_character not in character_names:
            conflicts.append({
                "type": "character_relationship_dangling",
                "severity": "high",
                "relationship_id": r.id,
                "message": f"人物关系 #{r.id}（{r.source_character} → {r.target_character}）指向了不存在的角色",
            })

    # 6. 怪物首次出场章节大于当前最大章节
    for m in repo.list_monsters():
        if (m.first_appearance or 0) > max_chapter:
            conflicts.append({
                "type": "monster_appearance_ahead",
                "severity": "low",
                "monster_id": m.id,
                "message": f"怪物 {m.name} 首次出场章节 {m.first_appearance} 大于当前最大章节 {max_chapter}",
            })

    return conflicts


def _state_change_dict(s):
    return {
        "id": s.id,
        "entity_type": s.entity_type,
        "entity_id": s.entity_id,
        "field": s.field,
        "old_value": s.old_value,
        "new_value": s.new_value,
        "chapter": s.chapter,
        "created_at": s.created_at.isoformat() if s.created_at else None,
    }


def _event_dict(e):
    return {
        "id": e.id,
        "event_type": e.type,
        "entity_id": e.entity_id,
        "chapter": e.chapter,
        "payload": e.payload,
        "timestamp": e.timestamp.isoformat() if e.timestamp else None,
    }
