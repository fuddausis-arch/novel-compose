"""圣经 CRUD API：角色/伏笔/大纲/摘要 + 创建/编辑/删除/导入。"""
from __future__ import annotations
import json
import logging
from fastapi import APIRouter, HTTPException, UploadFile, Depends
from pydantic import BaseModel
from sqlalchemy.orm import Session
from novel_agent.bible.database import SessionLocal, set_config
from novel_agent.bible.models import Base, Foreshadow, Character
from novel_agent.bible.repository import BibleRepository
from novel_agent.config import load_config
from novel_agent.templates.loader import PromptLoader

router = APIRouter()
logger = logging.getLogger(__name__)

# 已执行过轻量迁移的数据库文件集合（进程内缓存，避免每次请求重复跑 DDL）
_MIGRATED_DBS: set[str] = set()


def get_db(project_id: int):
    """数据库会话依赖项：统一管理会话生命周期。"""
    cfg = load_config()
    set_config(cfg)
    from novel_agent.bible import database as db_mod
    Base.metadata.create_all(bind=db_mod.engine)
    # 轻量迁移：为已有表添加新列（SQLite 不支持 IF NOT EXISTS，用 try-except）。
    # 每次进程只执行一次（模块级缓存），避免每次请求重复跑 DDL。
    # 注意：新增模型列时，务必在这里同步补充对应的 ALTER，否则旧库会缺列报错。
    global _MIGRATED_DBS
    if db_mod.engine.url.database not in _MIGRATED_DBS:
        from sqlalchemy import text as _sa_text
        migrations = [
            # characters：角色新增字段
            "ALTER TABLE characters ADD COLUMN language_style TEXT DEFAULT ''",
            "ALTER TABLE characters ADD COLUMN combat_style TEXT DEFAULT ''",
            "ALTER TABLE characters ADD COLUMN growth_curve TEXT DEFAULT ''",
            "ALTER TABLE characters ADD COLUMN emotional_anchor TEXT DEFAULT ''",
            # foreshadows：伏笔依赖关系
            "ALTER TABLE foreshadows ADD COLUMN depends_on TEXT DEFAULT ''",
            # outlines：大纲约束载荷（必备节拍/欠账/钩子/角色约束/阶段）
            "ALTER TABLE outlines ADD COLUMN required_beats TEXT DEFAULT ''",
            "ALTER TABLE outlines ADD COLUMN owed_debts TEXT DEFAULT ''",
            "ALTER TABLE outlines ADD COLUMN required_hooks TEXT DEFAULT ''",
            "ALTER TABLE outlines ADD COLUMN character_constraints TEXT DEFAULT ''",
            "ALTER TABLE outlines ADD COLUMN phase TEXT DEFAULT 'regular'",
            # 卷纲 key_events / 细纲 key_characters、emotional_arc 落库列
            "ALTER TABLE outlines ADD COLUMN key_events TEXT DEFAULT ''",
            "ALTER TABLE outlines ADD COLUMN key_characters TEXT DEFAULT ''",
            "ALTER TABLE outlines ADD COLUMN emotional_arc TEXT DEFAULT ''",
        ]
        with db_mod.engine.connect() as conn:
            for sql in migrations:
                try:
                    conn.execute(_sa_text(sql))
                    conn.commit()
                except Exception as e:
                    logger.debug("数据库迁移ALTER跳过: %s", e)
        _MIGRATED_DBS.add(db_mod.engine.url.database)
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def get_repo(project_id: int, db: Session = Depends(get_db)) -> BibleRepository:
    """Repository 依赖项：基于数据库会话创建 repository 实例。

    统一校验项目存在性：bible 所有端点都挂在具体项目下，
    项目不存在时返回 404 而非静默空数据。
    """
    repo = BibleRepository(db, project_id=project_id)
    if not repo.get_project():
        raise HTTPException(404, "项目不存在")
    return repo


# ===== 世界设定（World Setting）=====
@router.get("/{project_id}/world-settings")
def list_world_settings(project_id: int, repo: BibleRepository = Depends(get_repo)):
    return [{"id": w.id, "project_id": w.project_id, "category": w.category, "title": w.title,
             "content": w.content, "order": w.order}
            for w in repo.list_world_settings()]


class WorldSettingInput(BaseModel):
    category: str = ""
    title: str = ""
    content: str = ""
    order: int = 0


class FactionInput(BaseModel):
    name: str = ""
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
    source_faction_id: int = 0
    target_faction_id: int = 0
    relation_type: str = "neutral"
    strength: int = 0
    description: str = ""
    since_chapter: int = 0
    status: str = "active"


class CharacterRelationshipInput(BaseModel):
    source_character: str = ""
    target_character: str = ""
    relation_type: str = "other"
    relation_subtype: str = ""
    strength: int = 0
    description: str = ""
    since_chapter: int = 0
    status: str = "active"
    is_bidirectional: bool = True


class MonsterInput(BaseModel):
    name: str = ""
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


class InstanceInput(BaseModel):
    name: str = ""
    instance_type: str = ""
    related_volume: int = 0
    chapter_range: str = ""
    objective: str = ""
    mechanism: str = ""
    tone: str = ""
    difficulty: str = ""
    rewards: str = ""
    cost: str = ""
    description: str = ""
    order: int = 0


@router.post("/{project_id}/world-settings")
def create_world_setting(project_id: int, data: WorldSettingInput, repo: BibleRepository = Depends(get_repo)):
    w = repo.create_world_setting(**data.model_dump())
    return {"id": w.id, "project_id": w.project_id, "category": w.category, "title": w.title,
            "content": w.content, "order": w.order}


@router.put("/{project_id}/world-settings/{setting_id}")
def update_world_setting(project_id: int, setting_id: int, data: WorldSettingInput,
                         db: Session = Depends(get_db), repo: BibleRepository = Depends(get_repo)):
    from novel_agent.bible.models import WorldSetting
    w = db.query(WorldSetting).filter(
        WorldSetting.project_id == project_id,
        WorldSetting.id == setting_id).first()
    if not w:
        raise HTTPException(404, "世界设定不存在")
    for k, v in data.model_dump(exclude_unset=True).items():
        setattr(w, k, v)
    db.commit(); db.refresh(w)
    return {"id": w.id, "category": w.category, "title": w.title,
            "content": w.content, "order": w.order, "project_id": w.project_id}


@router.delete("/{project_id}/world-settings/{setting_id}")
def delete_world_setting(project_id: int, setting_id: int,
                         db: Session = Depends(get_db), repo: BibleRepository = Depends(get_repo)):
    from novel_agent.bible.models import WorldSetting
    w = db.query(WorldSetting).filter(
        WorldSetting.project_id == project_id,
        WorldSetting.id == setting_id).first()
    if not w:
        raise HTTPException(404, "世界设定不存在")
    db.delete(w); db.commit()
    return {"deleted": True}


# ===== 角色（Character）=====
@router.get("/{project_id}/characters")
def list_characters(project_id: int, repo: BibleRepository = Depends(get_repo)):
    return [_char_dict(c) for c in repo.list_characters()]


def _char_dict(c):
    return {"id": c.id, "project_id": c.project_id, "name": c.name, "role": c.role,
            "importance": c.importance, "age": c.age, "gender": c.gender,
            "appearance": c.appearance, "personality": c.personality, "motivation": c.motivation,
            "current_location": c.current_location, "current_emotion": c.current_emotion,
            "known_info": c.known_info, "background": c.background, "arc": c.arc,
            "relationships": c.relationships, "secrets": c.secrets,
            "core_contradiction": getattr(c, "core_contradiction", ""),
            "sensory_memories": getattr(c, "sensory_memories", ""),
            "absolute_taboos": getattr(c, "absolute_taboos", ""),
            "language_style": getattr(c, "language_style", ""),
            "combat_style": getattr(c, "combat_style", ""),
            "growth_curve": getattr(c, "growth_curve", ""),
            "emotional_anchor": getattr(c, "emotional_anchor", "")}


class CharacterInput(BaseModel):
    name: str = ""
    role: str = ""
    importance: str = ""
    age: str = ""
    gender: str = ""
    appearance: str = ""
    personality: str = ""
    motivation: str = ""
    current_location: str = ""
    current_emotion: str = ""
    known_info: str = ""
    background: str = ""
    arc: str = ""
    relationships: str = ""
    secrets: str = ""
    core_contradiction: str = ""
    sensory_memories: str = ""
    absolute_taboos: str = ""
    language_style: str = ""
    combat_style: str = ""
    growth_curve: str = ""
    emotional_anchor: str = ""


@router.post("/{project_id}/characters")
def create_character(project_id: int, data: CharacterInput, repo: BibleRepository = Depends(get_repo)):
    if not data.name:
        raise HTTPException(400, "角色名不能为空")
    if repo.get_character(data.name):
        raise HTTPException(409, f"角色 {data.name} 已存在")
    c = repo.create_character(**data.model_dump())
    return _char_dict(c)


@router.put("/{project_id}/characters/{character_id}")
def update_character(project_id: int, character_id: int, data: CharacterInput, repo: BibleRepository = Depends(get_repo)):
    c = repo.get_character_by_id(character_id)
    if not c:
        raise HTTPException(404, "角色不存在")
    payload = data.model_dump(exclude_unset=True)
    # name 字段交给 repo.update_character 作为 kwarg 处理级联重命名
    c = repo.update_character(c.name, **payload)
    if not c:
        raise HTTPException(404, "角色不存在")
    return _char_dict(c)


@router.delete("/{project_id}/characters/{character_id}")
def delete_character(project_id: int, character_id: int, repo: BibleRepository = Depends(get_repo)):
    if not repo.delete_character_by_id(character_id):
        raise HTTPException(404, "角色不存在")
    return {"deleted": True}


# ===== 伏笔（Foreshadow）=====
@router.get("/{project_id}/foreshadows")
def list_foreshadows(project_id: int, db: Session = Depends(get_db)):
    fs = db.query(Foreshadow).filter(Foreshadow.project_id == project_id).all()
    return [_foreshadow_dict(f) for f in fs]


class ForeshadowInput(BaseModel):
    foreshadow_id: str = ""
    tier: str = ""
    description: str = ""
    plant_chapter: int = 0
    planned_resolve_chapter: int = 0
    status: str = "pending"
    depends_on: str = ""


@router.post("/{project_id}/foreshadows")
def create_foreshadow(project_id: int, data: ForeshadowInput, repo: BibleRepository = Depends(get_repo)):
    if not data.foreshadow_id:
        raise HTTPException(400, "伏笔ID不能为空")
    if repo.get_foreshadow(data.foreshadow_id):
        raise HTTPException(409, f"伏笔 {data.foreshadow_id} 已存在")
    f = repo.create_foreshadow(**data.model_dump())
    return _foreshadow_dict(f)


@router.put("/{project_id}/foreshadows/{foreshadow_id}")
def update_foreshadow(project_id: int, foreshadow_id: str, data: ForeshadowInput, repo: BibleRepository = Depends(get_repo)):
    # 注意：data 中也可能带 foreshadow_id（前端表单必填），与 URL 参数重复会导致
    # repo.update_foreshadow(foreshadow_id, **kwargs) 收到重复参数崩溃（500）。
    # 以 URL 参数为准，从 kwargs 中排除。
    payload = data.model_dump(exclude_unset=True)
    payload.pop("foreshadow_id", None)
    existing = repo.get_foreshadow(foreshadow_id)
    if not existing:
        raise HTTPException(404, "伏笔不存在")
    # P0#3：REST PUT 走状态机（禁止随意跳变；pending 可任意进入 planted）
    new_status = payload.get("status")
    if new_status and new_status != existing.status:
        allowed = {
            "pending": {"planted", "abandoned"},
            "planted": {"developing", "resolved", "abandoned"},
            "developing": {"resolved", "abandoned"},
            "resolved": set(),
            "abandoned": set(),
        }.get(existing.status, set())
        if new_status not in allowed:
            raise HTTPException(
                400,
                f"非法伏笔状态流转：{existing.status} → {new_status}"
                f"（允许：{sorted(allowed) or '无'}）",
            )
    f = repo.update_foreshadow(foreshadow_id, **payload)
    if not f:
        raise HTTPException(404, "伏笔不存在")
    return _foreshadow_dict(f)


@router.delete("/{project_id}/foreshadows/{foreshadow_id}")
def delete_foreshadow(project_id: int, foreshadow_id: str, repo: BibleRepository = Depends(get_repo)):
    if not repo.delete_foreshadow(foreshadow_id):
        raise HTTPException(404, "伏笔不存在")
    return {"deleted": True}


# ===== 剧情债（Plot Debt）=====
def _plot_debt_dict(d):
    return {"id": d.id, "debt_type": d.debt_type, "description": d.description,
            "pressure": d.pressure, "term": d.term, "status": d.status,
            "created_chapter": d.created_chapter, "resolved_chapter": d.resolved_chapter}


class PlotDebtInput(BaseModel):
    debt_type: str = "因果"
    description: str = ""
    pressure: int = 3
    term: str = "short"
    status: str = "open"
    created_chapter: int = 0


@router.get("/{project_id}/plot-debts")
def list_plot_debts(project_id: int, status: str | None = None,
                    repo: BibleRepository = Depends(get_repo)):
    return [_plot_debt_dict(d) for d in repo.list_all_debts(status=status)]


@router.post("/{project_id}/plot-debts")
def create_plot_debt(project_id: int, data: PlotDebtInput, repo: BibleRepository = Depends(get_repo)):
    if not data.description.strip():
        raise HTTPException(400, "剧情债描述不能为空")
    d = repo.create_plot_debt(**data.model_dump())
    return _plot_debt_dict(d)


@router.put("/{project_id}/plot-debts/{debt_id}")
def update_plot_debt(project_id: int, debt_id: int, data: PlotDebtInput,
                     repo: BibleRepository = Depends(get_repo)):
    d = repo.update_plot_debt(debt_id, **data.model_dump(exclude_unset=True))
    if not d:
        raise HTTPException(404, "剧情债不存在")
    return _plot_debt_dict(d)


@router.delete("/{project_id}/plot-debts/{debt_id}")
def delete_plot_debt(project_id: int, debt_id: int, repo: BibleRepository = Depends(get_repo)):
    if not repo.delete_plot_debt(debt_id):
        raise HTTPException(404, "剧情债不存在")
    return {"deleted": True}


# ---- 大纲 ----
def _outline_dict(o):
    data = {"id": o.id, "level": o.level, "parent_id": o.parent_id, "order": o.order,
            "title": o.title, "summary": o.summary, "act": o.act, "strand": o.strand,
            "required_beats": o.required_beats or "",
            "owed_debts": o.owed_debts or "",
            "required_hooks": o.required_hooks or "",
            "character_constraints": o.character_constraints or "",
            "phase": o.phase or "regular",
            "key_events": o.key_events or "",
            "key_characters": o.key_characters or "",
            "emotional_arc": o.emotional_arc or ""}
    # 卷大纲将规划章数存于 character_constraints JSON 中，解析后便于前端使用
    if o.level == "volume" and o.character_constraints:
        try:
            import json as _json
            constraints = _json.loads(o.character_constraints)
            data["planned_chapters"] = int(constraints.get("chapters", 0) or 0)
        except Exception:
            data["planned_chapters"] = 0
    return data


@router.get("/{project_id}/outlines")
def list_outlines(project_id: int, level: str | None = None, parent_id: int | None = None,
                  repo: BibleRepository = Depends(get_repo)):
    return [_outline_dict(o) for o in repo.list_outlines(level=level, parent_id=parent_id)]


class OutlineInput(BaseModel):
    level: str = "chapter"
    parent_id: int | None = None
    order: int = 0
    act: str = ""
    strand: str = ""
    title: str = ""
    summary: str = ""
    required_beats: str = ""
    owed_debts: str = ""
    required_hooks: str = ""
    character_constraints: str = ""
    phase: str = ""


@router.post("/{project_id}/outlines")
def create_outline(project_id: int, data: OutlineInput, repo: BibleRepository = Depends(get_repo)):
    o = repo.create_outline(**data.model_dump())
    return _outline_dict(o)


@router.put("/{project_id}/outlines/{outline_id}")
def update_outline(project_id: int, outline_id: int, data: OutlineInput,
                   repo: BibleRepository = Depends(get_repo)):
    try:
        o = repo.update_outline(outline_id, **data.model_dump(exclude_unset=True))
    except Exception as e:
        if "UNIQUE" in str(e) or "IntegrityError" in type(e).__name__:
            raise HTTPException(409, "编号或层级冲突，请检查 order 和 parent_id")
        raise
    if not o:
        raise HTTPException(404, "大纲条目不存在")
    return _outline_dict(o)


@router.delete("/{project_id}/outlines/{outline_id}")
def delete_outline(project_id: int, outline_id: int, repo: BibleRepository = Depends(get_repo)):
    if not repo.delete_outline(outline_id):
        raise HTTPException(404, "大纲条目不存在")
    return {"deleted": True}


@router.post("/{project_id}/outlines/batch-delete")
def batch_delete_outlines(project_id: int, outline_ids: list[int], repo: BibleRepository = Depends(get_repo)):
    """批量删除大纲条目。"""
    deleted = []
    failed = []
    for oid in outline_ids:
        if repo.delete_outline(oid):
            deleted.append(oid)
        else:
            failed.append(oid)
    return {"deleted": deleted, "failed": failed, "deleted_count": len(deleted)}


@router.post("/{project_id}/outlines/renumber")
def renumber_outlines(project_id: int, level: str = "volume",
                      parent_id: int | None = None,
                      repo: BibleRepository = Depends(get_repo)):
    """重新编号大纲，让 order 连续（1, 2, 3...），修复跳号问题。

    Args:
        level: volume/arc/chapter
        parent_id: 仅 arc/chapter 需要指定父级 ID
    """
    outlines = repo.list_outlines(level=level, parent_id=parent_id)
    # 按 order 排序后重新编号
    outlines.sort(key=lambda o: (o.order or 0, o.id))
    renumbered = 0
    for new_order, o in enumerate(outlines, start=1):
        if o.order != new_order:
            o.order = new_order
            renumbered += 1
    if renumbered > 0:
        repo.db.commit()
    return {"level": level, "total": len(outlines), "renumbered": renumbered}


# ---- 摘要（只读 + 删除）----
@router.get("/{project_id}/summaries")
def list_summaries(project_id: int, repo: BibleRepository = Depends(get_repo)):
    return [{"chapter": s.chapter, "title": s.title, "core_events": s.core_events,
             "word_count": s.word_count}
            for s in repo.list_chapter_summaries(limit=100)]


@router.delete("/{project_id}/summaries/{chapter}")
def delete_summary(project_id: int, chapter: int, repo: BibleRepository = Depends(get_repo)):
    if not repo.delete_chapter_summary(chapter):
        raise HTTPException(404, "摘要不存在")
    return {"deleted": True}


# ---- 势力 ----
def _faction_dict(f):
    return {"id": f.id, "project_id": f.project_id, "name": f.name, "alias": f.alias, "type": f.type,
            "tier": f.tier, "alignment": f.alignment, "description": f.description,
            "history": f.history, "goals": f.goals, "hierarchy": f.hierarchy,
            "territories": f.territories, "resources": f.resources,
            "created_at": f.created_at.isoformat() if f.created_at else None,
            "updated_at": f.updated_at.isoformat() if f.updated_at else None}


@router.get("/{project_id}/factions")
def list_factions(project_id: int, repo: BibleRepository = Depends(get_repo)):
    return [_faction_dict(f) for f in repo.list_factions()]


@router.post("/{project_id}/factions")
def create_faction(project_id: int, data: FactionInput, repo: BibleRepository = Depends(get_repo)):
    if not data.name:
        raise HTTPException(400, "势力名称不能为空")
    if repo.get_faction_by_name(data.name):
        raise HTTPException(409, "势力名称已存在")
    f = repo.create_faction(**data.model_dump())
    return {"id": f.id, "project_id": f.project_id, "name": f.name, "alias": f.alias, "type": f.type,
            "tier": f.tier, "alignment": f.alignment, "description": f.description,
            "history": f.history, "goals": f.goals, "hierarchy": f.hierarchy,
            "territories": f.territories, "resources": f.resources}


@router.put("/{project_id}/factions/{faction_id}")
def update_faction(project_id: int, faction_id: int, data: FactionInput,
                   db: Session = Depends(get_db)):
    from novel_agent.bible.models import Faction
    f = db.query(Faction).filter(Faction.project_id == project_id, Faction.id == faction_id).first()
    if not f:
        raise HTTPException(404, "势力不存在")
    for k, v in data.model_dump(exclude_unset=True).items():
        setattr(f, k, v)
    db.commit(); db.refresh(f)
    return {"id": f.id, "project_id": f.project_id, "name": f.name, "alias": f.alias, "type": f.type,
            "tier": f.tier, "alignment": f.alignment, "description": f.description,
            "history": f.history, "goals": f.goals, "hierarchy": f.hierarchy,
            "territories": f.territories, "resources": f.resources}


@router.delete("/{project_id}/factions/{faction_id}")
def delete_faction(project_id: int, faction_id: int, repo: BibleRepository = Depends(get_repo)):
    if not repo.delete_faction(faction_id):
        raise HTTPException(404, "势力不存在")
    return {"deleted": True}


# ===== 势力关系（Faction Relationship）=====
@router.get("/{project_id}/faction-relationships")
def list_faction_relationships(project_id: int, repo: BibleRepository = Depends(get_repo)):
    return [{"id": r.id, "project_id": r.project_id, "source_faction_id": r.source_faction_id, "target_faction_id": r.target_faction_id,
             "relation_type": r.relation_type, "strength": r.strength, "description": r.description,
             "since_chapter": r.since_chapter, "status": r.status} for r in repo.list_faction_relationships()]


@router.post("/{project_id}/faction-relationships")
def create_faction_relationship(project_id: int, data: FactionRelationshipInput,
                                repo: BibleRepository = Depends(get_repo)):
    if not data.source_faction_id or not data.target_faction_id:
        raise HTTPException(400, "源势力和目标势力ID不能为空")
    r = repo.create_faction_relationship(**data.model_dump())
    return {"id": r.id, "project_id": r.project_id, "source_faction_id": r.source_faction_id, "target_faction_id": r.target_faction_id,
            "relation_type": r.relation_type, "strength": r.strength, "description": r.description,
            "since_chapter": r.since_chapter, "status": r.status}


@router.put("/{project_id}/faction-relationships/{rel_id}")
def update_faction_relationship(project_id: int, rel_id: int, data: FactionRelationshipInput,
                                db: Session = Depends(get_db)):
    from novel_agent.bible.models import FactionRelationship
    r = db.query(FactionRelationship).filter(FactionRelationship.project_id == project_id, FactionRelationship.id == rel_id).first()
    if not r:
        raise HTTPException(404, "关系不存在")
    for k, v in data.model_dump(exclude_unset=True).items():
        setattr(r, k, v)
    db.commit(); db.refresh(r)
    return {"id": r.id, "project_id": r.project_id, "source_faction_id": r.source_faction_id, "target_faction_id": r.target_faction_id,
            "relation_type": r.relation_type, "strength": r.strength, "description": r.description,
            "since_chapter": r.since_chapter, "status": r.status}


@router.delete("/{project_id}/faction-relationships/{rel_id}")
def delete_faction_relationship(project_id: int, rel_id: int, repo: BibleRepository = Depends(get_repo)):
    if not repo.delete_faction_relationship(rel_id):
        raise HTTPException(404, "关系不存在")
    return {"deleted": True}


# ---- 人物关系 ----
@router.get("/{project_id}/character-relationships")
def list_character_relationships(project_id: int, repo: BibleRepository = Depends(get_repo)):
    return [{"id": r.id, "project_id": r.project_id, "source_character": r.source_character, "target_character": r.target_character,
             "relation_type": r.relation_type, "relation_subtype": r.relation_subtype, "strength": r.strength,
             "description": r.description, "since_chapter": r.since_chapter, "status": r.status,
             "is_bidirectional": r.is_bidirectional} for r in repo.list_character_relationships()]


@router.post("/{project_id}/character-relationships")
def create_character_relationship(project_id: int, data: CharacterRelationshipInput,
                                  repo: BibleRepository = Depends(get_repo)):
    if not data.source_character or not data.target_character:
        raise HTTPException(400, "源角色和目标角色不能为空")
    r = repo.create_character_relationship(**data.model_dump())
    return {"id": r.id, "project_id": r.project_id, "source_character": r.source_character, "target_character": r.target_character,
            "relation_type": r.relation_type, "relation_subtype": r.relation_subtype, "strength": r.strength,
            "description": r.description, "since_chapter": r.since_chapter, "status": r.status,
            "is_bidirectional": r.is_bidirectional}


@router.put("/{project_id}/character-relationships/{rel_id}")
def update_character_relationship(project_id: int, rel_id: int, data: CharacterRelationshipInput,
                                  db: Session = Depends(get_db)):
    from novel_agent.bible.models import CharacterRelationship
    r = db.query(CharacterRelationship).filter(CharacterRelationship.project_id == project_id, CharacterRelationship.id == rel_id).first()
    if not r:
        raise HTTPException(404, "关系不存在")
    for k, v in data.model_dump(exclude_unset=True).items():
        setattr(r, k, v)
    db.commit(); db.refresh(r)
    return {"id": r.id, "project_id": r.project_id, "source_character": r.source_character, "target_character": r.target_character,
            "relation_type": r.relation_type, "relation_subtype": r.relation_subtype, "strength": r.strength,
            "description": r.description, "since_chapter": r.since_chapter, "status": r.status,
            "is_bidirectional": r.is_bidirectional}


@router.delete("/{project_id}/character-relationships/{rel_id}")
def delete_character_relationship(project_id: int, rel_id: int, repo: BibleRepository = Depends(get_repo)):
    if not repo.delete_character_relationship(rel_id):
        raise HTTPException(404, "关系不存在")
    return {"deleted": True}


# ---- 怪物 ----
def _monster_dict(m):
    return {"id": m.id, "project_id": m.project_id, "name": m.name, "alias": m.alias, "species": m.species,
            "rank": m.rank, "tier": m.tier, "attributes": m.attributes, "skills": m.skills,
            "drops": m.drops, "habitats": m.habitats, "behavior": m.behavior,
            "weaknesses": m.weaknesses, "lore": m.lore,
            "first_appearance": m.first_appearance}


@router.get("/{project_id}/monsters")
def list_monsters(project_id: int, repo: BibleRepository = Depends(get_repo)):
    return [_monster_dict(m) for m in repo.list_monsters()]


@router.post("/{project_id}/monsters")
def create_monster(project_id: int, data: MonsterInput, repo: BibleRepository = Depends(get_repo)):
    if not data.name:
        raise HTTPException(400, "怪物名称不能为空")
    if repo.get_monster_by_name(data.name):
        raise HTTPException(409, "怪物名称已存在")
    m = repo.create_monster(**data.model_dump())
    return _monster_dict(m)


@router.put("/{project_id}/monsters/{monster_id}")
def update_monster(project_id: int, monster_id: int, data: MonsterInput,
                   db: Session = Depends(get_db)):
    from novel_agent.bible.models import Monster
    m = db.query(Monster).filter(Monster.project_id == project_id, Monster.id == monster_id).first()
    if not m:
        raise HTTPException(404, "怪物不存在")
    for k, v in data.model_dump(exclude_unset=True).items():
        setattr(m, k, v)
    db.commit(); db.refresh(m)
    return _monster_dict(m)


@router.delete("/{project_id}/monsters/{monster_id}")
def delete_monster(project_id: int, monster_id: int, repo: BibleRepository = Depends(get_repo)):
    if not repo.delete_monster(monster_id):
        raise HTTPException(404, "怪物不存在")
    return {"deleted": True}


# ===== 副本/特殊场景（Instance）=====
def _instance_dict(i):
    return {"id": i.id, "project_id": i.project_id, "name": i.name,
            "instance_type": i.instance_type, "related_volume": i.related_volume,
            "chapter_range": i.chapter_range, "objective": i.objective,
            "mechanism": i.mechanism, "tone": i.tone, "difficulty": i.difficulty,
            "rewards": i.rewards, "cost": i.cost, "description": i.description,
            "order": i.order}


@router.get("/{project_id}/instances")
def list_instances(project_id: int, repo: BibleRepository = Depends(get_repo)):
    return [_instance_dict(i) for i in repo.list_instances()]


@router.post("/{project_id}/instances")
def create_instance(project_id: int, data: InstanceInput, repo: BibleRepository = Depends(get_repo)):
    if not data.name:
        raise HTTPException(400, "副本名称不能为空")
    if repo.get_instance_by_name(data.name):
        raise HTTPException(409, "副本名称已存在")
    i = repo.create_instance(**data.model_dump())
    return _instance_dict(i)


@router.put("/{project_id}/instances/{instance_id}")
def update_instance(project_id: int, instance_id: int, data: InstanceInput,
                    db: Session = Depends(get_db)):
    from novel_agent.bible.models import Instance
    i = db.query(Instance).filter(Instance.project_id == project_id, Instance.id == instance_id).first()
    if not i:
        raise HTTPException(404, "副本不存在")
    for k, v in data.model_dump(exclude_unset=True).items():
        setattr(i, k, v)
    db.commit(); db.refresh(i)
    return _instance_dict(i)


@router.delete("/{project_id}/instances/{instance_id}")
def delete_instance(project_id: int, instance_id: int, repo: BibleRepository = Depends(get_repo)):
    if not repo.delete_instance(instance_id):
        raise HTTPException(404, "副本不存在")
    return {"deleted": True}


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
        "created_at": a.created_at.isoformat() if a.created_at else None,
        "updated_at": a.updated_at.isoformat() if a.updated_at else None,
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
                            entity_id: str | None = None, chapter: int | None = None,
                            repo: BibleRepository = Depends(get_repo)):
    return [_appearance_dict(a) for a in repo.list_entity_appearances(
        entity_type=entity_type, entity_id=entity_id, chapter=chapter)]


@router.post("/{project_id}/entity-appearances")
def create_entity_appearance(project_id: int, data: EntityAppearanceInput,
                             repo: BibleRepository = Depends(get_repo)):
    try:
        a = repo.create_entity_appearance(**data.model_dump())
    except Exception as e:
        if "UNIQUE" in str(e) or "IntegrityError" in type(e).__name__:
            raise HTTPException(409, "该实体在本章的出场记录已存在")
        raise
    return _appearance_dict(a)


@router.put("/{project_id}/entity-appearances/{appearance_id}")
def update_entity_appearance(project_id: int, appearance_id: int, data: EntityAppearanceUpdateInput,
                             db: Session = Depends(get_db)):
    from novel_agent.bible.models import EntityAppearance
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


@router.delete("/{project_id}/entity-appearances/{appearance_id}")
def delete_entity_appearance(project_id: int, appearance_id: int,
                             repo: BibleRepository = Depends(get_repo)):
    if not repo.delete_entity_appearance(appearance_id):
        raise HTTPException(404, "出场记录不存在")
    return {"deleted": True}


@router.post("/{project_id}/chapters/{chapter}/record-appearances")
def record_appearances(project_id: int, chapter: int, data: RecordAppearancesInput,
                       repo: BibleRepository = Depends(get_repo)):
    created = repo.record_appearances(chapter, [a.model_dump() for a in data.appearances])
    return {"chapter": chapter, "recorded": len(created),
            "appearances": [_appearance_dict(a) for a in created]}


# ===== 关系变化（Relationship Change）=====
class RelationshipChangeInput(BaseModel):
    chapter: int
    entity_type: str
    source_id: str
    target_id: str
    field: str
    old_value: str = ""
    new_value: str = ""
    reason: str = ""


def _relationship_change_dict(rc):
    return {
        "id": rc.id,
        "project_id": rc.project_id,
        "chapter": rc.chapter,
        "entity_type": rc.entity_type,
        "source_id": rc.source_id,
        "target_id": rc.target_id,
        "field": rc.field,
        "old_value": rc.old_value,
        "new_value": rc.new_value,
        "reason": rc.reason,
        "created_at": rc.created_at.isoformat() if rc.created_at else None,
    }


@router.get("/{project_id}/relationship-changes")
def list_relationship_changes(project_id: int,
                              chapter: int | None = None,
                              source_id: str | None = None,
                              target_id: str | None = None,
                              repo: BibleRepository = Depends(get_repo)):
    return [_relationship_change_dict(rc) for rc in repo.list_relationship_changes(
        chapter=chapter, source_id=source_id, target_id=target_id)]


@router.post("/{project_id}/relationship-changes")
def create_relationship_change(project_id: int, data: RelationshipChangeInput,
                               repo: BibleRepository = Depends(get_repo)):
    rc = repo.create_relationship_change(**data.model_dump())
    return _relationship_change_dict(rc)


# ===== AI 生成（AI Generation）=====
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
    source_character: str = ""
    target_character: str = ""
    relation_type_hint: str = ""


def _clean_text(text: Any) -> str:
    if text is None:
        return ""
    return str(text).strip()


def _extract_json(text: str) -> dict:
    from novel_agent.utils.json_parser import parse_json_strict
    return parse_json_strict(text)


@router.post("/{project_id}/generate-faction")
async def generate_faction(project_id: int, req: GenerateFactionRequest,
                           repo: BibleRepository = Depends(get_repo)):
    from novel_agent.llm.client import LLMClient

    cfg = load_config()
    project = repo.get_project()
    if not project:
        raise HTTPException(404, "项目不存在")
    client = LLMClient(cfg.get_agent_llm("architect"))
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
    raw = await client.generate(prompt, system="你是网文设定师，擅长设计势力组织。只输出 JSON。", max_tokens=128000)
    result = await _extract_json_with_repair(client, raw)
    data = {k: _clean_text(result.get(k, "")) for k in FactionInput.model_fields}
    if not data.get("name"):
        data["name"] = req.name_hint or f"生成势力{len(existing) + 1}"
    if repo.get_faction_by_name(data["name"]):
        raise HTTPException(409, "同名势力已存在")
    f = repo.create_faction(**data)
    return {"id": f.id, "project_id": f.project_id, "name": f.name, "alias": f.alias, "type": f.type,
            "tier": f.tier, "alignment": f.alignment, "description": f.description,
            "history": f.history, "goals": f.goals, "hierarchy": f.hierarchy,
            "territories": f.territories, "resources": f.resources}


@router.post("/{project_id}/generate-monster")
async def generate_monster(project_id: int, req: GenerateMonsterRequest,
                           repo: BibleRepository = Depends(get_repo)):
    from novel_agent.llm.client import LLMClient

    cfg = load_config()
    project = repo.get_project()
    if not project:
        raise HTTPException(404, "项目不存在")
    client = LLMClient(cfg.get_agent_llm("architect"))
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
    raw = await client.generate(prompt, system="你是网文怪物设计师，擅长设计有特色的怪物。只输出 JSON。", max_tokens=128000)
    result = await _extract_json_with_repair(client, raw)
    data = {k: _clean_text(result.get(k, "")) for k in MonsterInput.model_fields}
    if "first_appearance" in result:
        data["first_appearance"] = result.get("first_appearance", 0)
    if not data.get("name"):
        data["name"] = req.name_hint or f"生成怪物{len(existing) + 1}"
    if repo.get_monster_by_name(data["name"]):
        raise HTTPException(409, "同名怪物已存在")
    m = repo.create_monster(**data)
    return _monster_dict(m)


@router.post("/{project_id}/generate-character-relationship")
async def generate_character_relationship(project_id: int, req: GenerateCharacterRelationshipRequest,
                                          repo: BibleRepository = Depends(get_repo)):
    from novel_agent.llm.client import LLMClient

    cfg = load_config()
    project = repo.get_project()
    if not project:
        raise HTTPException(404, "项目不存在")
    # 自动选角色：前端不传seed时，取前两个角色
    all_chars = repo.list_characters()
    src_name = req.source_character
    tgt_name = req.target_character
    if not src_name and len(all_chars) >= 1:
        src_name = all_chars[0].name
    if not tgt_name and len(all_chars) >= 2:
        tgt_name = all_chars[1].name
    if not src_name or not tgt_name:
        raise HTTPException(400, "需要至少2个角色才能生成关系")
    source = repo.get_character(src_name)
    target = repo.get_character(tgt_name)
    if not source or not target:
        raise HTTPException(404, f"角色不存在：{src_name} 或 {tgt_name}")
    client = LLMClient(cfg.get_agent_llm("architect"))
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
    raw = await client.generate(prompt, system="你是网文关系设计师，擅长设计立体的人物关系。只输出 JSON。", max_tokens=128000)
    result = await _extract_json_with_repair(client, raw)
    def _safe_int(val, default=0):
        try:
            return int(val)
        except (ValueError, TypeError):
            return default

    data = {
        "source_character": source.name,
        "target_character": target.name,
        "relation_type": _clean_text(result.get("relation_type", "其他")) or "其他",
        "relation_subtype": _clean_text(result.get("relation_subtype", "")),
        "strength": _safe_int(result.get("strength", 0), 0),
        "description": _clean_text(result.get("description", "")),
        "since_chapter": _safe_int(result.get("since_chapter", 0), 0),
        "status": _clean_text(result.get("status", "active")) or "active",
        "is_bidirectional": bool(result.get("is_bidirectional", True)),
    }
    r = repo.create_character_relationship(**data)
    return {"id": r.id, "project_id": r.project_id, "source_character": r.source_character, "target_character": r.target_character,
            "relation_type": r.relation_type, "relation_subtype": r.relation_subtype, "strength": r.strength,
            "description": r.description, "since_chapter": r.since_chapter, "status": r.status,
            "is_bidirectional": r.is_bidirectional}


@router.post("/{project_id}/generate-character")
async def generate_character(project_id: int, req: GenerateCharacterRequest,
                             repo: BibleRepository = Depends(get_repo)):
    from novel_agent.llm.client import LLMClient

    cfg = load_config()
    project = repo.get_project()
    if not project:
        raise HTTPException(404, "项目不存在")
    client = LLMClient(cfg.get_agent_llm("architect"))
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
        "请输出 JSON：{\"name\":\"\",\"role\":\"\",\"personality\":\"\",\"background\":\"\",\"motivation\":\"\",\"appearance\":\"\",\"importance\":\"\",\"core_contradiction\":\"\",\"sensory_memories\":\"\",\"absolute_taboos\":\"\"}\n"
        "importance 建议取值：主角、配角、关键人物、小人物、NPC。core_contradiction 是承重矛盾（\"他是___的人，但同时___\"），sensory_memories 是 3-4 个第一人称关键记忆片段，absolute_taboos 是 2-3 条绝对禁令。只输出 JSON，不要 markdown 代码块。"
    )
    raw = await client.generate(prompt, system="你是网文角色设计师，擅长设计立体角色。只输出 JSON。", max_tokens=128000)
    result = await _extract_json_with_repair(client, raw)
    data = {k: _clean_text(result.get(k, "")) for k in CharacterInput.model_fields}
    if not data.get("name"):
        data["name"] = req.name_hint or f"生成角色{len(existing) + 1}"
    if repo.get_character(data["name"]):
        raise HTTPException(409, "同名角色已存在")
    c = repo.create_character(**data)
    return _char_dict(c)


# ===== 批量导入（Batch Import）=====
class GoldenFingerInput(BaseModel):
    """金手指设定（写入 Project.golden_finger）。"""
    name: str = ""
    type: str = ""           # 辅助型/战斗型/成长型/系统型/血脉型
    core_ability: str = ""   # 核心能力
    limitation: str = ""      # 限制/代价
    growth: str = ""         # 成长路径
    origin: str = ""         # 来历


class ImportData(BaseModel):
    """批量导入设定数据（世界观/势力/关系/角色/伏笔/大纲/怪物/副本/金手指）。"""
    world_settings: list[WorldSettingInput] = []
    factions: list[FactionInput] = []
    faction_relationships: list[FactionRelationshipInput] = []
    character_relationships: list[CharacterRelationshipInput] = []
    characters: list[CharacterInput] = []
    foreshadows: list[ForeshadowInput] = []
    outlines: list[OutlineInput] = []
    monsters: list[MonsterInput] = []
    instances: list[InstanceInput] = []
    golden_finger: GoldenFingerInput | None = None


def _merge_import_data(a: ImportData, b: ImportData) -> ImportData:
    """合并两份解析结果（用于超大文件夹分批解析后的汇总），逐类拼接。"""
    return ImportData(
        world_settings=a.world_settings + b.world_settings,
        factions=a.factions + b.factions,
        faction_relationships=a.faction_relationships + b.faction_relationships,
        character_relationships=a.character_relationships + b.character_relationships,
        characters=a.characters + b.characters,
        foreshadows=a.foreshadows + b.foreshadows,
        outlines=a.outlines + b.outlines,
        monsters=a.monsters + b.monsters,
        instances=a.instances + b.instances,
        golden_finger=a.golden_finger or b.golden_finger,
    )


@router.post("/{project_id}/import")
def import_settings(project_id: int, data: ImportData, repo: BibleRepository = Depends(get_repo)):
    """批量导入世界观/设定数据。已存在的跳过。"""
    added = _apply_import_data(repo, data)
    # P1#9：导入的章级大纲索引进向量库（记忆写入闭环），失败不阻塞主流程
    try:
        import re as _re
        from novel_agent.memory.archival import ArchivalMemory
        archival = ArchivalMemory(load_config(), project_id=project_id)
        for o in data.outlines:
            if o.level != "chapter":
                continue
            m = _re.match(r"^第?\s*(\d+)\s*章", o.title or "")
            if not m:
                continue
            ch = int(m.group(1))
            archival.index_chapter(chapter=ch, title=o.title or f"第{ch}章",
                                   content=o.summary or "")
    except Exception as e:
        logger.warning("导入章节向量索引失败: %s", e)
    return {"imported": added}


def _apply_import_data(repo: BibleRepository, data: ImportData, overwrite: bool = False) -> dict:
    added = {"world_settings": 0, "characters": 0, "foreshadows": 0, "outlines": 0,
             "factions": 0, "faction_relationships": 0, "character_relationships": 0,
             "monsters": 0, "instances": 0, "golden_finger": 0}
    for w in data.world_settings:
        repo.create_world_setting(**w.model_dump())
        added["world_settings"] += 1
    # 先创建所有势力，记录名称到 DB id 的映射
    faction_name_to_id: dict[str, int] = {}
    for f in data.factions:
        existing = repo.get_faction_by_name(f.name)
        if existing:
            faction_name_to_id[f.name] = existing.id
        else:
            created = repo.create_faction(**f.model_dump())
            faction_name_to_id[f.name] = created.id
            added["factions"] += 1
    # 势力关系：LLM 提取的 source/target_faction_id 是文档序号，
    # 需要按势力列表顺序映射到真实 DB id
    faction_list = [f.name for f in data.factions]
    for r in data.faction_relationships:
        rd = r.model_dump()
        src_idx = rd.get("source_faction_id", 0)
        tgt_idx = rd.get("target_faction_id", 0)
        # 尝试按序号映射（LLM 提取的序号从1开始）
        src_name = faction_list[src_idx - 1] if 0 < src_idx <= len(faction_list) else None
        tgt_name = faction_list[tgt_idx - 1] if 0 < tgt_idx <= len(faction_list) else None
        if src_name and tgt_name and src_name in faction_name_to_id and tgt_name in faction_name_to_id:
            rd["source_faction_id"] = faction_name_to_id[src_name]
            rd["target_faction_id"] = faction_name_to_id[tgt_name]
            repo.create_faction_relationship(**rd)
            added["faction_relationships"] += 1
    # 角色关系：先查已有的去重，避免 UNIQUE 约束冲突导致整个导入失败
    existing_rels = set()
    try:
        for er in repo.list_character_relationships():
            existing_rels.add((er.source_character, er.target_character, er.relation_type))
    except Exception as e:
        logger.warning("加载已有角色关系失败: %s", e)
    for r in data.character_relationships:
        rd = r.model_dump()
        key = (rd.get("source_character", ""), rd.get("target_character", ""), rd.get("relation_type", ""))
        if key in existing_rels:
            continue  # 已存在，跳过
        try:
            repo.create_character_relationship(**rd)
            existing_rels.add(key)
            added["character_relationships"] += 1
        except Exception:
            # 单条失败不阻塞其他条目
            continue
    for c in data.characters:
        existing_ch = repo.get_character(c.name)
        if existing_ch:
            if overwrite:
                # 覆盖模式：更新空字段（ability 是旧版字段名，Character 无此列，映射到 combat_style）
                cd = c.model_dump()
                changed = False
                for field in ["background", "personality", "motivation", "arc", "appearance", "secrets", "combat_style"]:
                    val = cd.get(field)
                    if field == "combat_style" and not val:
                        val = cd.get("ability")
                    if val and not getattr(existing_ch, field, None):
                        setattr(existing_ch, field, val)
                        changed = True
                if changed:
                    repo.db.commit()
                    added["characters"] += 1
        else:
            repo.create_character(**c.model_dump())
            added["characters"] += 1
    for f in data.foreshadows:
        if not repo.get_foreshadow(f.foreshadow_id):
            repo.create_foreshadow(**f.model_dump())
            added["foreshadows"] += 1
    from novel_agent.bible.models import Outline as _Outline
    import re as _re

    _CN_NUM = {"一": 1, "二": 2, "三": 3, "四": 4, "五": 5, "六": 6,
               "七": 7, "八": 8, "九": 9, "十": 10, "十一": 11, "十二": 12}

    def _cn_int(s: str) -> int:
        """中文数字转 int，支持任意大小（十三=13, 二十=20, 二十五=25）。"""
        v = _cn_to_int(s)
        return v if v is not None else _CN_NUM.get(s, 0)

    def _vol_key(title: str):
        """卷的规范化标识：优先章节范围，其次卷号（兼容中文/阿拉伯数字）。"""
        m = _re.search(r'（\s*(\d+)\s*[-~]\s*(\d+)\s*章）', title or "")
        if m:
            return ("range", int(m.group(1)), int(m.group(2)))
        m = _re.search(r'第\s*(\d+)\s*卷', title or "")
        if m:
            return ("num", int(m.group(1)), None)
        m = _re.search(r'第\s*([一二三四五六七八九十]+)\s*卷', title or "")
        if m:
            return ("num", _cn_int(m.group(1)), None)
        return None

    def _arc_key(title: str):
        """细纲的规范化标识：章节范围优先，其次 X.Y 编号。"""
        m = _re.search(r'（\s*(\d+)\s*[-~]\s*(\d+)\s*章）', title or "")
        if m:
            return ("range", int(m.group(1)), int(m.group(2)))
        # 结构化细纲标题格式："第501-515章 锚点危机延续+准备原始文明副本"
        m = _re.search(r'^第\s*(\d+)\s*[-~]\s*(\d+)\s*章', title or "")
        if m:
            return ("range", int(m.group(1)), int(m.group(2)))
        m = _re.search(r'^\s*(\d+)\s*[-~]\s*(\d+)\s*章', title or "")
        if m:
            return ("range", int(m.group(1)), int(m.group(2)))
        m = _re.search(r'^\s*(\d+)\.(\d+)\s', title or "")
        if m:
            return ("xy", int(m.group(1)), int(m.group(2)))
        return None

    def _ch_num(title: str):
        # 从行首匹配"第N章"或"N章"，排除"第N-M章"范围格式
        m = _re.match(r'^第?\s*(\d+)\s*章', title or "")
        return int(m.group(1)) if m else None

    # 按 level 排序：volume -> arc -> chapter，确保父级先导入
    sorted_outlines = sorted(data.outlines, key=lambda o: {"volume": 0, "arc": 1, "chapter": 2}.get(o.level, 3))

    # ---- 建立已有卷/细纲的规范化索引（用于去重与关联）----
    vol_by_range: dict[tuple, int] = {}     # (start, end) -> id
    vol_by_seq: dict[int, int] = {}         # 卷序 -> id（第N卷的N）
    vol_ranges: list[tuple] = []            # (start, end, id) 供细纲挂卷
    _range_items: list[tuple] = []          # (start, id) 用于推算卷序
    for v in repo.list_outlines(level="volume"):
        k = _vol_key(v.title)
        if k and k[0] == "range":
            vol_by_range[(k[1], k[2])] = v.id
            vol_ranges.append((k[1], k[2], v.id))
            _range_items.append((k[1], v.id))
        elif k and k[0] == "num":
            vol_by_seq[k[1]] = v.id
            vol_ranges.append((k[1], k[1], v.id))
        else:
            # 无范围卷不加入 vol_ranges，避免吸附所有未匹配细纲
            pass
    for i, (_s, vid) in enumerate(sorted(_range_items), 1):
        vol_by_seq.setdefault(i, vid)  # 范围版卷按范围起点排序推算卷序，供卷号版去重
    arc_by_range: dict[tuple, int] = {}  # (start, end) -> id
    arc_by_xy: dict[tuple, int] = {}     # (卷序, 段序) -> id
    arc_ranges: list[tuple] = []         # (start, end, id) 供章纲挂细纲
    for a in repo.list_outlines(level="arc"):
        k = _arc_key(a.title)
        if k and k[0] == "range":
            arc_by_range[(k[1], k[2])] = a.id
            arc_ranges.append((k[1], k[2], a.id))
        elif k and k[0] == "xy":
            arc_by_xy[(k[1], k[2])] = a.id

    for o in sorted_outlines:
        od = o.model_dump()
        title = od.get("title", "")

        # ---- 自动关联 parent_id ----
        if od.get("parent_id") is None:
            if o.level == "arc":
                k = _arc_key(title)
                if k and k[0] == "range":
                    start = k[1]
                    for vs, ve, vid in vol_ranges:
                        if vs <= start <= ve:
                            od["parent_id"] = vid
                            break
                elif k and k[0] == "xy":
                    # xy 格式：用卷序查找 vol_by_seq
                    vid = vol_by_seq.get(k[1])
                    if vid:
                        od["parent_id"] = vid
            elif o.level == "chapter":
                ch = _ch_num(title)
                if ch:
                    for s, e, aid in arc_ranges:
                        if s <= ch <= e:
                            od["parent_id"] = aid
                            break

        # ---- 规范化去重：同一卷/细纲/章号视为同一条 ----
        # 避免"第一卷"与"第1卷"、"1.1 xxx（1-15章）"与"1-15章 xxx"重复入库
        exists = None
        if o.level == "volume":
            k = _vol_key(title)
            eid = None
            if k and k[0] == "range":
                eid = vol_by_range.get((k[1], k[2]))
                if eid is None:
                    # 范围重叠检查
                    for (s, e), vid in vol_by_range.items():
                        if k[1] <= e and s <= k[2]:
                            eid = vid
                            break
                if eid is None:
                    # 无范围命中时按卷序兜底：仅按"范围版卷"的起点排序推算，
                    # 排除卷号版卷（(N,N)）和无范围卷（(0,10**9)）的干扰
                    start = k[1]
                    seq = sum(1 for vs, _ in _range_items if vs < start) + 1
                    eid = vol_by_seq.get(seq)
            elif k and k[0] == "num":
                eid = vol_by_seq.get(k[1])
            if eid:
                exists = repo.db.query(_Outline).filter(
                    _Outline.project_id == repo.project_id, _Outline.id == eid).first()
        elif o.level == "arc":
            k = _arc_key(title)
            eid = None
            if k and k[0] == "range":
                eid = arc_by_range.get((k[1], k[2]))
                # 精确匹配失败时，检查范围重叠（AI 提取的范围可能不准，
                # 如结构化是 101-115 章，AI 提取是 101-120 章，应视为同一条）
                if eid is None:
                    new_start, new_end = k[1], k[2]
                    for (s, e), aid in arc_by_range.items():
                        if new_start <= e and s <= new_end:
                            eid = aid
                            break
            elif k and k[0] == "xy":
                eid = arc_by_xy.get((k[1], k[2]))
            if eid:
                exists = repo.db.query(_Outline).filter(
                    _Outline.project_id == repo.project_id, _Outline.id == eid).first()
        elif o.level == "chapter":
            ch = _ch_num(title)
            if ch:
                exists = repo.db.query(_Outline).filter(
                    _Outline.project_id == repo.project_id,
                    _Outline.level == "chapter",
                    _Outline.title.like(f"第{ch}章%") | _Outline.title.like(f"{ch}章%"),
                ).first()
        if exists is None and (o.level == "volume" and _vol_key(title) is None
                               or o.level == "arc" and _arc_key(title) is None
                               or o.level == "chapter" and _ch_num(title) is None):
            # 无规范化标识：回退到标题精确匹配
            exists = repo.db.query(_Outline).filter(
                _Outline.project_id == repo.project_id,
                _Outline.level == od.get("level"),
                _Outline.parent_id == od.get("parent_id"),
                _Outline.title == title,
            ).first()

        if exists:
            # 卷：若新标题带章节范围而旧标题没有，升级标题（否则细纲无法按范围挂卷）
            if o.level == "volume":
                nk = _vol_key(title)
                ok = _vol_key(exists.title)
                if nk and nk[0] == "range" and (ok is None or ok[0] != "range"):
                    exists.title = title
                    if od.get("summary"):
                        exists.summary = od["summary"]
                    repo.db.commit()
                    added["outlines"] += 1
                    vol_by_range[(nk[1], nk[2])] = exists.id
                    vol_ranges.append((nk[1], nk[2], exists.id))
                    _range_items.append((nk[1], exists.id))
                    continue
            # 细纲：已存在但未挂卷时，补上父级（结构化解析算出的 parent）
            if o.level == "arc" and exists.parent_id is None and od.get("parent_id"):
                exists.parent_id = od["parent_id"]
                repo.db.commit()
                added["outlines"] += 1
                continue
            if overwrite and od.get("summary"):
                # 覆盖模式：更新 summary/act/strand
                exists.summary = od["summary"]
                if od.get("act"):
                    exists.act = od["act"]
                if od.get("strand"):
                    exists.strand = od["strand"]
                repo.db.commit()
                added["outlines"] += 1
            continue  # 已存在，跳过创建
        created = repo.create_outline(**od)
        added["outlines"] += 1
        # 记录新导入的卷/细纲，供后续章纲关联
        if o.level == "volume":
            k = _vol_key(title)
            if k and k[0] == "range":
                vol_by_range[(k[1], k[2])] = created.id
                vol_ranges.append((k[1], k[2], created.id))
                _range_items.append((k[1], created.id))
            elif k and k[0] == "num":
                vol_by_seq.setdefault(k[1], created.id)
                vol_ranges.append((k[1], k[1], created.id))
            else:
                # 无范围卷不加入 vol_ranges，避免吸附所有未匹配细纲
                pass
        elif o.level == "arc":
            k = _arc_key(title)
            if k and k[0] == "range":
                arc_by_range[(k[1], k[2])] = created.id
                arc_ranges.append((k[1], k[2], created.id))
            elif k and k[0] == "xy":
                arc_by_xy[(k[1], k[2])] = created.id
    for m in data.monsters:
        if not repo.get_monster_by_name(m.name):
            repo.create_monster(**m.model_dump())
            added["monsters"] += 1
    # 副本
    from novel_agent.bible.models import Instance as _Instance
    for inst in data.instances:
        if not inst.name:
            continue
        exists = repo.db.query(_Instance).filter(
            _Instance.project_id == repo.project_id,
            _Instance.name == inst.name,
        ).first()
        if exists:
            if overwrite:
                id_data = inst.model_dump()
                for field in ["objective", "mechanism", "rewards", "cost", "description"]:
                    val = id_data.get(field)
                    if val and not getattr(exists, field, None):
                        setattr(exists, field, val)
                repo.db.commit()
                added["instances"] = added.get("instances", 0) + 1
            continue
        repo.db.add(_Instance(project_id=repo.project_id, **inst.model_dump()))
        repo.db.commit()
        added["instances"] = added.get("instances", 0) + 1
    # 金手指：写入 Project.golden_finger（JSON 字符串）
    if data.golden_finger and data.golden_finger.name:
        import json as _json
        repo.update_project(golden_finger=_json.dumps(
            data.golden_finger.model_dump(), ensure_ascii=False))
        added["golden_finger"] = 1
    return added


# ---- 文档导入：用 LLM 从自然语言文档中提取设定 ----
class DocumentImportInput(BaseModel):
    content: str


_CN_DIGITS = {"一": 1, "二": 2, "三": 3, "四": 4, "五": 5, "六": 6, "七": 7, "八": 8, "九": 9, "零": 0}

def _cn_to_int(s: str) -> int | None:
    """通用中文数字解析，支持一到九十九、一百零一等。"""
    s = s.strip()
    if not s:
        return None
    if s.isdigit():
        return int(s)
    # "十" = 10, "十一" = 11, "二十" = 20, "二十三" = 23, "一百零一" = 101
    total = 0
    current = 0
    has_num = False
    for ch in s:
        if ch in _CN_DIGITS:
            current = current * 10 + _CN_DIGITS[ch] if has_num and current > 0 else _CN_DIGITS[ch]
            has_num = True
        elif ch == "十":
            total += (current if current > 0 else 1) * 10
            current = 0
            has_num = True
        elif ch == "百":
            total += (current if current > 0 else 1) * 100
            current = 0
            has_num = True
    return total + current if has_num else None
_STRUCT_DIMS = ["剧情", "信息增量", "角色决策", "爽点设计", "章末钩子", "梗运用"]


def _parse_structured_outlines(text: str, rel_path: str) -> list[OutlineInput]:
    """直接解析规整/半规整的细纲、章纲文件（照搬原文），不依赖 LLM。

    识别特征：文件含章标题行（`第N章 xxx`，可带 `**` 或 `#`）+ 维度行
    （`剧情：`、`信息增量：`、`章末钩子：` 等，可带 `- **` 前缀）。
    文件名或正文可提供卷信息：第X卷_卷名（A-B章）。
    返回：卷（带章节范围标题）+ 细纲（段落）+ 章纲（6 维度照搬 summary）。
    """
    import re as _re

    outlines: list[OutlineInput] = []
    base = str(rel_path).replace("\\", "/").split("/")[-1]

    # ---- 卷：文件名解析（第X卷_卷名（A-B章））----
    vol_num, vol_range, vol_name = None, None, ""
    m = _re.search(r"第\s*([一二三四五六七八九十\d]+)\s*卷", base)
    if m:
        t = m.group(1)
        vol_num = _cn_to_int(t)
    m2 = _re.search(r"（\s*(\d+)\s*[-~]\s*(\d+)\s*章）", base)
    if m2:
        vol_range = (int(m2.group(1)), int(m2.group(2)))
    m3 = _re.search(r"卷[_（( ]*([^（(]+)", base)
    if m3:
        name = m3.group(1).strip().strip("_- -")
        # 排除垃圾内容（含"章"或文件扩展名的不是卷名）
        if name and "章" not in name and ".txt" not in name and ".md" not in name and len(name) <= 20:
            vol_name = name

    # ---- 卷兜底：文件名没解析到时，从正文第一处卷标题行提取 ----
    if not vol_range:
        m = _re.search(
            r"^#{1,4}\s*第\s*([一二三四五六七八九十\d]+)\s*卷[^\n]*?（\s*(\d+)\s*[-~]\s*(\d+)\s*章）",
            text, _re.M)
        if m:
            t = m.group(1)
            vol_num = _cn_to_int(t)
            vol_range = (int(m.group(2)), int(m.group(3)))
            seg = m.group(0)
            name_part = seg.split("卷", 1)[-1].split("（")[0]
            if not vol_name:
                vol_name = name_part.strip().strip("_— -")

    vol_core = ""
    for line in text.splitlines():
        if line.lstrip().startswith(">") and "卷核心" in line:
            vol_core = line.lstrip("> ").strip()
            break
    if vol_num and vol_range:
        outlines.append(OutlineInput(
            level="volume", order=vol_num,
            title=f"第{vol_num}卷 {vol_name}（{vol_range[0]}-{vol_range[1]}章）",
            summary=vol_core,
        ))

    # ---- 细纲（段落）+ 章纲 ----
    # 段落标题："### 第1-15章 xxx" / "第1-15章 xxx"（无 #）
    # 章纲标题："**第1章 xxx**" / "第1章 xxx"（无 **）
    # 维度行："- **剧情**：xxx" / "剧情：xxx" / "- 剧情：xxx"
    cur_arc: dict | None = None
    cur_ch: dict | None = None

    def _flush_arc():
        nonlocal cur_arc, cur_ch
        if cur_arc is not None:
            arc_input, chapter_inputs = _arc_to_input(cur_arc)
            outlines.append(arc_input)
            outlines.extend(chapter_inputs)
        cur_arc = None
        cur_ch = None

    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue
        mp = (_re.match(r"^#{2,4}\s*第(\d+)-(\d+)章\s*(.+)$", line)
              or _re.match(r"^第(\d+)-(\d+)章\s*(.+)$", line))
        if mp:
            _flush_arc()
            cur_arc = {
                "range": (int(mp.group(1)), int(mp.group(2))),
                "title": mp.group(3).strip(" *#*"),
                "core": "",
                "chapters": [],
            }
            cur_ch = None
            continue
        mc = _re.match(r"^\*{0,2}第([一二三四五六七八九十百零\d]+)章\s*(.+?)\*{0,2}\s*$", line)
        # 章标题必须是短行（避免把正文长句当标题），且仅在细纲段落内收集
        if mc and cur_arc is not None and len(mc.group(2)) <= 60:
            ch_num_str = mc.group(1)
            ch_num = int(ch_num_str) if ch_num_str.isdigit() else _cn_to_int(ch_num_str)
            if ch_num is None:
                continue  # 无法解析的章号，跳过
            cur_ch = {"num": ch_num, "title": mc.group(2).replace("*", "").strip(), "dims": []}
            cur_arc["chapters"].append(cur_ch)
            continue
        md = _re.match(r"^[-*\s]*([^：:]{1,12}?)\s*\*{0,2}[：:]\s*(.+)$", line)
        if md and cur_ch is not None:
            dim_name = md.group(1).replace("*", "").strip()
            if dim_name in _STRUCT_DIMS:
                cur_ch["dims"].append((dim_name, md.group(2).strip()))
            continue
        # 段落核心（位于段落标题之后、首个章纲之前）
        if cur_arc is not None and not cur_arc["chapters"] and "段落核心" in line:
            cur_arc["core"] = line.split("段落核心", 1)[-1].strip()
    _flush_arc()
    return outlines


def _arc_to_input(arc: dict) -> tuple[OutlineInput, list[OutlineInput]]:
    """返回 (细纲 OutlineInput, 章纲 OutlineInput 列表)。"""
    rng = arc["range"]
    chs = []
    for ch in arc["chapters"]:
        order = {d: i for i, d in enumerate(_STRUCT_DIMS)}
        dims = sorted(ch["dims"], key=lambda x: order.get(x[0], 99))
        summary = "\n".join(f"{k}：{v}" for k, v in dims)
        chs.append(OutlineInput(
            level="chapter",
            order=ch["num"],  # 全局章节号（与 AI 生成路径一致，get_outline_by_chapter 依赖此值）
            title=f"第{ch['num']}章 {ch['title']}",
            summary=summary,
        ))
    return OutlineInput(
        level="arc",
        title=f"第{rng[0]}-{rng[1]}章 {arc['title']}",
        summary=arc.get("core") or "",
        required_beats="",
    ), chs



async def _parse_text(client, text: str) -> ImportData:
    """将已提取的文本通过 LLM 逐类解析为 ImportData，不写入数据库。

    每类设定单独一个 LLM 调用（8 路并发），每次只专注提取一类，
    确保完整提取该类所有设定，不遗漏。
    单类失败不阻塞其他类，已提取的结果仍返回。
    """
    import asyncio
    import json
    import re
    import logging

    logger = logging.getLogger(__name__)

    # 每类的提取说明（字段格式 + 专项指令）
    category_specs = {
        "world_settings": {
            "label": "世界观设定",
            "format": '{"world_settings":[{"category":"分类","title":"标题","content":"内容","order":0}]}',
            "instruction": (
                "提取所有世界观设定。世界观设定是指小说世界里的规则、背景、体系等非角色非势力的设定，包括但不限于："
                "世界背景、地理环境、历史时代、力量体系（如魔法/修仙/异能/序列体系）、"
                "修炼等级、社会结构、文化风俗、科技水平、经济体系、种族、禁忌规则、"
                "世界法则、时空规则、阵营分布格局、重要地点、历史事件、传说神话。"
                "每条设定都要单独提取，不可合并或省略。"
                "特别注意：力量体系/修炼等级/能力分类等属于世界观设定，不要归到角色或势力里。"
                "如果文档提到了世界的总体规则、时代背景、地理环境，必须提取为世界观设定。"
            ),
        },
        "characters": {
            "label": "角色",
            "format": '{"characters":[{"name":"姓名","role":"身份","importance":"主角/配角/关键人物/小人物/NPC","personality":"性格","motivation":"动机","background":"背景","arc":"角色弧线","language_style":"语言风格与经典台词","combat_style":"战斗风格与战术","growth_curve":"成长曲线","emotional_anchor":"情感锚点","secrets":"秘密"}]}',
            "instruction": "提取所有出现的角色，包括主角、配角、反派、路人。每个角色都要提取，不可遗漏。"
            "language_style：提取角色的语言风格特点 and 经典台词示例（如有）。"
            "combat_style：提取角色的战斗风格、战术体系、擅长策略（如有）。"
            "growth_curve：提取角色的成长阶段、能力进化路径、心理变化（如有）。"
            "emotional_anchor：提取角色的情感锚点（重要的人、事物或信念）（如有）。",
        },
        "foreshadows": {
            "label": "伏笔",
            "format": '{"foreshadows":[{"foreshadow_id":"ID","tier":"层级","description":"描述","plant_chapter":0,"planned_resolve_chapter":0,"status":"pending"}]}',
            "instruction": "提取所有伏笔、悬念、暗线。包括已埋下的伏笔、未解之谜、隐藏线索等。",
        },
        "outlines": {
            "label": "大纲",
            "format": '{"outlines":[{"order":1,"title":"标题","summary":"详细摘要","level":"chapter","act":"发展","strand":"quest"}]}',
            "instruction": (
                "提取所有大纲，包括卷大纲、细纲（弧线）、章纲。根据内容判断 level：volume=卷、arc=弧线/细纲、chapter=章节。\n"
                "【summary 字段铁律：直接照搬原文，禁止改写】\n"
                "summary 必须逐字照搬原文对应条目的完整内容，禁止任何概括、压缩、改写、润色、省略。\n"
                "原文怎么写的就怎么放进去，包括编号、层级、括号标注（如（1-15章））、冒号分隔的多个维度、多行内容。\n"
                "如果原文条目里包含：剧情/事件链、信息增量/新设定、角色决策与动机、爽点设计、章末钩子、梗运用、副本机制、奖励代价等内容，全部原样保留，一个维度都不要丢。\n"
                "原文有多长，summary 就写多长，禁止用一句话总结原文。宁可照搬全文，不要自己重写。\n"
                "【照搬示例】\n"
                "原文：「1.1 末日降临与觉醒（1-15章）：主角陈默在废土醒来，发现自己拥有时间回溯能力。爽点：开局装逼打脸。钩子：手腕上的倒计时纹身。新设定：辐射能量结晶。」\n"
                "正确 summary：「主角陈默在废土醒来，发现自己拥有时间回溯能力。爽点：开局装逼打脸。钩子：手腕上的倒计时纹身。新设定：辐射能量结晶。」\n"
                "错误 summary（禁止）：「末日降临，主角觉醒能力」\n"
                "order 按原文编号/章节号。act 取值：开端/发展/高潮/转折/收束。strand 取值：quest（主线）/fire（战斗）/constellation（角色关系）。"
            ),
        },
        "factions": {
            "label": "势力",
            "format": '{"factions":[{"name":"势力名","alias":"别名","type":"类型","tier":"顶级势力/一流势力/二流势力/三流势力/隐世势力","alignment":"阵营","description":"描述","history":"历史","goals":"目标","hierarchy":"架构","territories":"领地","resources":"资源"}]}',
            "instruction": "提取所有势力、组织、门派、国家、家族。每个势力都要提取，包括描述、目标、架构等。",
        },
        "faction_relationships": {
            "label": "势力关系",
            "format": '{"faction_relationships":[{"source_faction_id":1,"target_faction_id":2,"relation_type":"敌对/同盟/中立等","strength":5,"description":"关系描述","since_chapter":0,"status":"active"}]}',
            "instruction": "提取所有势力之间的关系，包括同盟、敌对、从属、合作等。source_faction_id 和 target_faction_id 用势力在文档中出现的序号（从1开始）。",
        },
        "character_relationships": {
            "label": "人物关系",
            "format": '{"character_relationships":[{"source_character":"角色A","target_character":"角色B","relation_type":"友情","relation_subtype":"挚友","strength":5,"description":"关系描述","since_chapter":0,"status":"active","is_bidirectional":true}]}',
            "instruction": "提取所有角色之间的关系，包括亲情、友情、爱情、敌对、师徒、主仆等。",
        },
        "monsters": {
            "label": "怪物",
            "format": '{"monsters":[{"name":"怪物名","alias":"别名","species":"物种","rank":"等级","tier":"BOSS/精英/首领/小怪/普通","attributes":"属性","skills":"技能","drops":"掉落","habitats":"栖息地","behavior":"行为","weaknesses":"弱点","lore":"背景","first_appearance":0,"appearances":[]}]}',
            "instruction": "提取所有怪物、异兽、魔物图鉴。如果没有怪物相关内容则返回空数组。",
        },
        "instances": {
            "label": "副本/特殊场景",
            "format": '{"instances":[{"name":"副本名","instance_type":"文明副本/量子隧穿/迷宫/试炼/其他","chapter_range":"86-100","objective":"目的","mechanism":"机制","tone":"悲壮/轻松/紧张/悬疑","difficulty":"数值/机制/混合","rewards":"奖励","cost":"代价","description":"详细描述","order":1}]}',
            "instruction": "提取所有副本、特殊场景、试炼关卡等。包括副本名称、类型、机制、目的、代价、奖励等。如果没有副本相关内容则返回空数组。",
        },
        "golden_finger": {
            "label": "金手指",
            "format": '{"golden_finger":[{"name":"金手指名称","type":"辅助型/战斗型/成长型/系统型/血脉型","core_ability":"核心能力","limitation":"限制或代价","growth":"成长路径","origin":"来历"}]}',
            "instruction": (
                "提取主角的金手指设定（外挂/特殊能力/系统/神器等）。"
                "一本书通常只有一个主金手指，如果文档提到多个，只提取最主要的一个。"
                "如果文档没有明确提到金手指，返回空数组。"
                "核心能力、限制、成长路径、来历都要尽量完整。"
            ),
        },
    }

    # 限制并发数，避免同时打太多请求触发 API 限流
    sem = asyncio.Semaphore(3)

    async def _extract_one(cat_key: str) -> tuple[str, list]:
        spec = category_specs[cat_key]
        prompt = (
            f"请从以下小说设定文档中提取【{spec['label']}】，只输出 JSON，不要任何解释。\n\n"
            f"{spec['instruction']}\n\n"
            f"输出格式（只输出这个 JSON 结构，key 必须是 {cat_key}）：\n{spec['format']}\n\n"
            f"如果文档中没有{spec['label']}相关内容，返回 {cat_key}: []。\n"
            f"必须逐段扫描文档，完整提取所有{spec['label']}，不可遗漏。\n\n"
            f"文档如下：\n{text}"
        )
        async with sem:
            try:
                raw = await client.generate(
                    prompt,
                    system=f"你是小说设定解析助手。本次只负责提取【{spec['label']}】，必须完整提取，逐段扫描，不可遗漏。输出 JSON 的 key 必须是 {cat_key}。",
                    max_tokens=128000,
                )
            except Exception as e:
                err_msg = str(e)
                logger.warning("LLM 解析%s失败: %s", spec["label"], e)
                # 配额超限/鉴权错误：向上抛出，不让前端得到空结果
                if any(kw in err_msg.lower() for kw in ["配额", "quota", "余额不足", "insufficient", "exceeded", "401", "403", "unauthorized"]):
                    raise
                return cat_key, []
        try:
            parsed = await _extract_json_with_repair(client, raw)
            items = parsed.get(cat_key, [])
            # 兜底：如果指定 key 为空，尝试从 parsed 里找任意非空 list 值
            # （LLM 可能用了错误的 key，如 "world_setting" 单数或中文 "世界观设定"）
            if not items:
                logger.warning("提取%s: key=%s 未命中，parsed keys=%s，尝试兜底",
                               spec["label"], cat_key, list(parsed.keys()))
                for k, v in parsed.items():
                    if isinstance(v, list) and len(v) > 0:
                        items = v
                        logger.info("提取%s: 兜底命中 key=%s, %d 条", spec["label"], k, len(v))
                        break
            if isinstance(items, list):
                logger.info("提取%s: %d 条", spec["label"], len(items))
                return cat_key, items
            return cat_key, []
        except Exception as e:
            logger.warning("JSON 修复%s失败: %s", spec["label"], e)
            return cat_key, []

    # 8 路并发，每类单独提取
    results = await asyncio.gather(
        *[_extract_one(k) for k in category_specs.keys()],
        return_exceptions=True,
    )
    merged: dict[str, list] = {}
    for r in results:
        if isinstance(r, BaseException):
            # 配额/鉴权等致命错误：直接抛出，让前端看到明确提示
            raise r
        if isinstance(r, tuple) and len(r) == 2:
            merged[r[0]] = r[1]
        else:
            logger.warning("解析结果异常: %s", r)

    # 类型清洗：LLM 可能返回 list/dict 而非 str，统一转为 str
    def _clean_str_fields(items: list, str_fields: set[str]) -> list:
        cleaned = []
        for item in items:
            if not isinstance(item, dict):
                continue
            for k, v in list(item.items()):
                if k in str_fields and not isinstance(v, str):
                    item[k] = ", ".join(str(x) for x in v) if isinstance(v, list) else str(v) if v is not None else ""
            cleaned.append(item)
        return cleaned

    char_str_fields = {"name", "role", "importance", "age", "gender", "appearance",
                       "personality", "motivation", "current_location", "current_emotion",
                       "known_info", "background", "arc", "relationships", "secrets",
                       "core_contradiction", "sensory_memories", "absolute_taboos",
                       "language_style", "combat_style", "growth_curve", "emotional_anchor"}
    merged["characters"] = _clean_str_fields(merged.get("characters", []), char_str_fields)

    ws_str_fields = {"category", "title", "content", "source"}
    merged["world_settings"] = _clean_str_fields(merged.get("world_settings", []), ws_str_fields)

    fs_str_fields = {"foreshadow_id", "description", "tier", "status", "planned_resolve_chapter"}
    merged["foreshadows"] = _clean_str_fields(merged.get("foreshadows", []), fs_str_fields)

    # 金手指：取列表第一项作为单对象（一本书通常只有一个主金手指）
    gf_list = merged.get("golden_finger", [])
    gf_obj = GoldenFingerInput(**gf_list[0]) if gf_list and isinstance(gf_list[0], dict) else None

    return ImportData(
        world_settings=[WorldSettingInput(**w) for w in merged.get("world_settings", [])],
        factions=[FactionInput(**x) for x in merged.get("factions", [])],
        faction_relationships=[FactionRelationshipInput(**x) for x in merged.get("faction_relationships", [])],
        character_relationships=[CharacterRelationshipInput(**x) for x in merged.get("character_relationships", [])],
        characters=[CharacterInput(**c) for c in merged.get("characters", [])],
        foreshadows=[ForeshadowInput(**f) for f in merged.get("foreshadows", [])],
        outlines=[OutlineInput(**o) for o in merged.get("outlines", [])],
        monsters=[MonsterInput(**x) for x in merged.get("monsters", [])],
        instances=[InstanceInput(**x) for x in merged.get("instances", [])],
        golden_finger=gf_obj,
    )


def _try_parse_json(raw: str):
    """尝试从文本中提取并解析 JSON，成功返回 dict，失败返回 None。

    处理常见 LLM 输出问题：markdown 代码块包裹、前后多余文本、
    JSON 被截断（末尾缺少 } 括号）。
    """
    import json
    import re

    # 先直接尝试
    raw = raw.strip()
    if raw.startswith("```"):
        raw = re.sub(r"^```(?:json)?\s*", "", raw, flags=re.IGNORECASE)
        raw = re.sub(r"\s*```$", "", raw)
    try:
        return json.loads(raw)
    except Exception as e:
        logger.debug("JSON直接解析失败: %s", e)

    # 尝试匹配最外层 { ... }
    m = re.search(r"\{[\s\S]*\}", raw)
    if m:
        try:
            return json.loads(m.group(0))
        except Exception as e:
            logger.debug("JSON正则匹配解析失败: %s", e)

    # 尝试修复被截断的 JSON：从第一个 { 开始，补全缺失的右括号
    start = raw.find("{")
    if start >= 0:
        fragment = raw[start:]
        # 计算括号深度，补全缺失的 }
        depth = 0
        in_string = False
        escape = False
        for ch in fragment:
            if escape:
                escape = False
                continue
            if ch == "\\":
                escape = True
                continue
            if ch == '"':
                in_string = not in_string
                continue
            if in_string:
                continue
            if ch == "{":
                depth += 1
            elif ch == "}":
                depth -= 1
        if depth > 0:
            # 补全缺失的右括号
            repaired = fragment + "}" * depth
            try:
                return json.loads(repaired)
            except Exception as e:
                logger.debug("JSON修复后解析失败: %s", e)
    return None


async def _extract_json_with_repair(client, raw: str) -> dict:
    """解析 LLM 返回的 JSON，失败时尝试自动修复或请 LLM 自我修复。"""
    import json

    parsed = _try_parse_json(raw)
    if parsed is not None:
        return parsed

    # 第一次自我修复：请 LLM 把这段输出改成合法 JSON
    # 不截断 raw，避免丢失后半部分数据（分批解析后每批输出已可控）
    repair_prompt = (
        "下面这段内容本应是 JSON，但解析时报错。请只输出修复后的合法 JSON，不要任何解释。\n\n"
        f"{raw}"
    )
    try:
        fixed = await client.generate(repair_prompt, system="你是 JSON 修复助手，只输出合法 JSON。",
                                      max_tokens=128000)
    except Exception as e:
        raise HTTPException(400, f"LLM 返回的 JSON 格式错误，且自动修复失败: {e}")

    parsed = _try_parse_json(fixed)
    if parsed is not None:
        return parsed

    # 最后兜底：返回空 dict，让调用方继续（不阻塞整体导入）
    return {}


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
                                               "monsters": len(import_data.monsters),
                                               "instances": len(import_data.instances)}}


@router.post("/{project_id}/parse-document")
async def parse_document(project_id: int, data: DocumentImportInput):
    """从自然语言文档中提取角色/伏笔/大纲，返回结构化数据供前端预览筛选。"""
    from novel_agent.llm.client import LLMClient

    cfg = load_config()
    client = LLMClient(cfg.get_agent_llm("outliner"))
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
        "instances": [i.model_dump() for i in import_data.instances],
    }


@router.post("/{project_id}/import-document")
async def import_document(project_id: int, data: DocumentImportInput,
                          repo: BibleRepository = Depends(get_repo)):
    """从自然语言文档中提取角色/伏笔/大纲并导入圣经。"""
    from novel_agent.llm.client import LLMClient

    cfg = load_config()
    client = LLMClient(cfg.get_agent_llm("outliner"))
    return await _import_from_text(repo, client, data.content)


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
        parsed = _try_parse_json(raw)
        if not parsed:
            raise HTTPException(400, "LLM 未返回可解析的 JSON")
        return ImportData(
            world_settings=[WorldSettingInput(**w) for w in parsed.get("world_settings", [])],
            factions=[FactionInput(**x) for x in parsed.get("factions", [])],
            faction_relationships=[FactionRelationshipInput(**x) for x in parsed.get("faction_relationships", [])],
            character_relationships=[CharacterRelationshipInput(**x) for x in parsed.get("character_relationships", [])],
            characters=[CharacterInput(**c) for c in parsed.get("characters", [])],
            foreshadows=[ForeshadowInput(**f) for f in parsed.get("foreshadows", [])],
            outlines=[OutlineInput(**o) for o in parsed.get("outlines", [])],
            monsters=[MonsterInput(**x) for x in parsed.get("monsters", [])],
            instances=[InstanceInput(**x) for x in parsed.get("instances", [])],
        )

    return await _parse_text(client, content)


@router.post("/{project_id}/parse-file")
async def parse_file(project_id: int, file: UploadFile):
    """上传文件并提取角色/伏笔/大纲，返回结构化数据供前端预览筛选。"""
    from novel_agent.llm.client import LLMClient

    cfg = load_config()
    client = LLMClient(cfg.get_agent_llm("outliner"))
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
        "instances": [i.model_dump() for i in import_data.instances],
    }


@router.post("/{project_id}/import-file")
async def import_file(project_id: int, file: UploadFile,
                      repo: BibleRepository = Depends(get_repo)):
    """上传文件（txt/md/json/csv/html/docx/pdf/图片等）并提取内容导入圣经。

    图片需 LLM 开启 vision_enabled，否则返回错误。
    """
    from novel_agent.llm.client import LLMClient

    cfg = load_config()
    client = LLMClient(cfg.get_agent_llm("outliner"))
    import_data = await _parse_file_content(client, cfg, file)
    added = _apply_import_data(repo, import_data)
    return {"imported": added, "raw_summary": {"world_settings": len(import_data.world_settings),
                                               "factions": len(import_data.factions),
                                               "faction_relationships": len(import_data.faction_relationships),
                                               "character_relationships": len(import_data.character_relationships),
                                               "characters": len(import_data.characters),
                                               "foreshadows": len(import_data.foreshadows),
                                               "outlines": len(import_data.outlines),
                                               "monsters": len(import_data.monsters),
                                               "instances": len(import_data.instances)}}


@router.get("/{project_id}/consistency-dashboard")
def consistency_dashboard(project_id: int, repo: BibleRepository = Depends(get_repo)):
    """项目级一致性看板：状态变更、未回收伏笔、近期事件、冲突检测。"""
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
            "instances": len(repo.list_instances()),
        },
        "recent_state_changes": [_state_change_dict(s) for s in state_changes],
        "unresolved_foreshadows": [_foreshadow_dict(f) for f in unresolved],
        "overdue_foreshadows": [_foreshadow_dict(f) for f in overdue],
        "recent_events": [_event_dict(e) for e in events],
        "conflicts": conflicts,
    }


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

    # 3. 大纲序号不连续（按 level 分组检查：卷/弧/章各自独立编号）
    outlines_by_level: dict[str, list] = {}
    for o in repo.list_outlines():
        outlines_by_level.setdefault(o.level or "", []).append(o)
    for level, outlines in outlines_by_level.items():
        outlines = sorted(outlines, key=lambda o: o.order)
        for i in range(1, len(outlines)):
            if outlines[i].order != outlines[i - 1].order + 1:
                conflicts.append({
                    "type": "outline_gap",
                    "severity": "low",
                    "message": f"{level} 级大纲序号不连续：第 {outlines[i - 1].order} 个后直接跳到第 {outlines[i].order} 个",
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
        "project_id": s.project_id,
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
        "project_id": e.project_id,
        "event_type": e.type,
        "entity_id": e.entity_id,
        "chapter": e.chapter,
        "payload": e.payload,
        "timestamp": e.timestamp.isoformat() if e.timestamp else None,
    }


def _foreshadow_dict(f):
    return {
        "id": f.foreshadow_id,
        "project_id": f.project_id,
        "foreshadow_id": f.foreshadow_id,
        "tier": f.tier,
        "status": f.status,
        "description": f.description,
        "plant_chapter": f.plant_chapter,
        "planned_resolve_chapter": f.planned_resolve_chapter,
        "depends_on": f.depends_on,
        "created_at": f.created_at.isoformat() if f.created_at else None,
        "updated_at": f.updated_at.isoformat() if f.updated_at else None,
    }


# ---- 状态变更（StateChange）----
@router.get("/{project_id}/states")
def list_states(project_id: int, repo: BibleRepository = Depends(get_repo)):
    return [_state_change_dict(s) for s in repo.list_state_changes()]


# ---- 事件流（TruthEvent）----
@router.get("/{project_id}/events")
def list_events(project_id: int, repo: BibleRepository = Depends(get_repo)):
    return [_event_dict(e) for e in repo.list_events()]


# ---- 项目级 Bible 导出 ----
@router.get("/{project_id}/export")
def export_bible(project_id: int, repo: BibleRepository = Depends(get_repo)):
    project = repo.get_project()
    if not project:
        raise HTTPException(404, "项目不存在")
    from novel_agent.bible.models import StateSnapshot, ChatSession, ChatMessage, PostHocResult

    # 阶段4补全：摘要/快照/聊天记录/后验裁决（各块独立容错，不影响导出主结构）
    def _safe_query(loader):
        try:
            return loader() or []
        except Exception as e:
            logger.warning("导出 %s 失败: %s", loader.__name__ if hasattr(loader, "__name__") else "数据块", e)
            return []

    chapter_summaries = _safe_query(lambda: [
        {"chapter": s.chapter, "title": s.title, "time_location": s.time_location,
         "core_events": s.core_events, "characters_present": s.characters_present,
         "emotion_changes": s.emotion_changes, "foreshadow_dynamics": s.foreshadow_dynamics,
         "subplot_progress": s.subplot_progress, "chapter_hook": s.chapter_hook,
         "word_count": s.word_count}
        for s in repo.list_chapter_summaries(limit=10000)
    ])

    snapshots = _safe_query(lambda: [
        {"chapter": s.chapter, "snapshot_data": s.snapshot_data or {},
         "drift_score": s.drift_score, "is_full_resummary": s.is_full_resummary,
         "created_at": s.created_at.isoformat() if s.created_at else None}
        for s in repo.db.query(StateSnapshot)
        .filter(StateSnapshot.project_id == repo.project_id)
        .order_by(StateSnapshot.chapter).all()
    ])

    chat_sessions = _safe_query(lambda: [
        {"id": s.id, "session_type": s.session_type, "object_type": s.object_type,
         "object_id": s.object_id, "title": s.title,
         "created_at": s.created_at.isoformat() if s.created_at else None}
        for s in repo.db.query(ChatSession)
        .filter(ChatSession.project_id == repo.project_id)
        .order_by(ChatSession.created_at).all()
    ])

    chat_messages = _safe_query(lambda: [
        {"id": m.id, "session_id": m.session_id, "role": m.role, "content": m.content,
         "actions": m.actions or [],
         "created_at": m.created_at.isoformat() if m.created_at else None}
        for m in repo.db.query(ChatMessage)
        .filter(ChatMessage.session_id.in_([s["id"] for s in chat_sessions]))
        .order_by(ChatMessage.created_at).all()
    ])

    post_hoc_results = _safe_query(lambda: [
        {"chapter": p.chapter, "world_diff": p.world_diff or [], "story_diff": p.story_diff or [],
         "character_diff": p.character_diff or [], "unplanned_events": p.unplanned_events or [],
         "world_adjudication": p.world_adjudication or [], "story_adjudication": p.story_adjudication or [],
         "event_classification": p.event_classification or [], "summary": p.summary or {},
         "created_at": p.created_at.isoformat() if p.created_at else None}
        for p in repo.db.query(PostHocResult)
        .filter(PostHocResult.project_id == repo.project_id)
        .order_by(PostHocResult.chapter).all()
    ])

    return {
        "project": {
            "id": project.id,
            "title": project.title,
            "genre": project.genre,
            "summary": project.summary,
            "style": project.style,
        },
        "world_settings": [{"id": w.id, "category": w.category, "title": w.title, "content": w.content, "order": w.order}
                           for w in repo.list_world_settings()],
        "characters": [_char_dict(c) for c in repo.list_characters()],
        "factions": [{"id": f.id, "name": f.name, "alias": f.alias, "type": f.type,
                      "tier": f.tier, "alignment": f.alignment, "description": f.description,
                      "history": f.history, "goals": f.goals, "hierarchy": f.hierarchy,
                      "territories": f.territories, "resources": f.resources}
                     for f in repo.list_factions()],
        "faction_relationships": [{"id": r.id, "source_faction_id": r.source_faction_id,
                                   "target_faction_id": r.target_faction_id, "relation_type": r.relation_type,
                                   "strength": r.strength, "description": r.description,
                                   "since_chapter": r.since_chapter, "status": r.status}
                                  for r in repo.list_faction_relationships()],
        "character_relationships": [{"id": r.id, "source_character": r.source_character,
                                     "target_character": r.target_character, "relation_type": r.relation_type,
                                     "relation_subtype": r.relation_subtype, "strength": r.strength,
                                     "description": r.description, "since_chapter": r.since_chapter,
                                     "status": r.status, "is_bidirectional": r.is_bidirectional}
                                    for r in repo.list_character_relationships()],
        "monsters": [{"id": m.id, "name": m.name, "alias": m.alias, "species": m.species,
                      "rank": m.rank, "tier": m.tier, "attributes": m.attributes, "skills": m.skills,
                      "drops": m.drops, "habitats": m.habitats, "behavior": m.behavior,
                      "weaknesses": m.weaknesses, "lore": m.lore, "first_appearance": m.first_appearance}
                     for m in repo.list_monsters()],
        "instances": [_instance_dict(i) for i in repo.list_instances()],
        "foreshadows": [_foreshadow_dict(f) for f in repo.list_foreshadows()],
        "outlines": [{"id": o.id, "level": o.level, "parent_id": o.parent_id, "order": o.order,
                      "title": o.title, "summary": o.summary, "act": o.act, "strand": o.strand,
                      "required_beats": o.required_beats or "", "owed_debts": o.owed_debts or "",
                      "required_hooks": o.required_hooks or "", "character_constraints": o.character_constraints or "",
                      "phase": o.phase or "regular"}
                     for o in repo.list_outlines()],
        "state_changes": [_state_change_dict(s) for s in repo.list_state_changes()],
        "events": [_event_dict(e) for e in repo.list_events()],
        # ---- 阶段4补全：摘要/快照/聊天记录/后验裁决（新增 key，不破坏旧结构）----
        "chapter_summaries": chapter_summaries,
        "snapshots": snapshots,
        "chat_sessions": chat_sessions,
        "chat_messages": chat_messages,
        "post_hoc_results": post_hoc_results,
    }


# ===== 红线（RedLine）=====
class RedLineInput(BaseModel):
    scope: str = "project"          # "project" | "chapter"
    chapter_num: int | None = None  # scope=chapter 时必填
    content: str = ""
    severity: str = "hard"          # "hard" | "soft"
    enabled: bool = True


def _red_line_dict(r):
    return {
        "id": r.id,
        "project_id": r.project_id,
        "scope": r.scope,
        "chapter_num": r.chapter_num,
        "content": r.content,
        "severity": r.severity,
        "enabled": r.enabled,
        "created_at": r.created_at.isoformat() if r.created_at else None,
    }


@router.get("/{project_id}/red-lines")
def list_red_lines(project_id: int, scope: str | None = None,
                   chapter_num: int | None = None,
                   repo: BibleRepository = Depends(get_repo)):
    """列出红线，可按 scope=project/chapter 或 chapter_num=N 过滤。"""
    return [_red_line_dict(r) for r in repo.list_red_lines(scope=scope, chapter_num=chapter_num)]


@router.post("/{project_id}/red-lines")
def create_red_line(project_id: int, data: RedLineInput,
                    repo: BibleRepository = Depends(get_repo)):
    if not data.content:
        raise HTTPException(400, "红线内容不能为空")
    if data.scope == "chapter" and data.chapter_num is None:
        raise HTTPException(400, "章级红线必须指定 chapter_num")
    r = repo.create_red_line(**data.model_dump())
    return _red_line_dict(r)


@router.put("/{project_id}/red-lines/{red_line_id}")
def update_red_line(project_id: int, red_line_id: int, data: RedLineInput,
                    repo: BibleRepository = Depends(get_repo)):
    r = repo.update_red_line(red_line_id, **data.model_dump(exclude_unset=True))
    if not r:
        raise HTTPException(404, "红线不存在")
    return _red_line_dict(r)


@router.delete("/{project_id}/red-lines/{red_line_id}")
def delete_red_line(project_id: int, red_line_id: int,
                    repo: BibleRepository = Depends(get_repo)):
    if not repo.delete_red_line(red_line_id):
        raise HTTPException(404, "红线不存在")
    return {"deleted": True}


# ===== 梗（Gag）=====
class GagInput(BaseModel):
    name: str = ""
    description: str = ""
    category: str = "笑点"          # "笑点" | "桥段" | "彩蛋"
    status: str = "待用"            # "待用" | "使用中" | "已用"
    first_chapter: int | None = None
    usage_notes: str = ""


def _gag_dict(g):
    return {
        "id": g.id,
        "project_id": g.project_id,
        "name": g.name,
        "description": g.description,
        "category": g.category,
        "status": g.status,
        "first_chapter": g.first_chapter,
        "usage_notes": g.usage_notes,
        "created_at": g.created_at.isoformat() if g.created_at else None,
    }


@router.get("/{project_id}/gags")
def list_gags(project_id: int, category: str | None = None,
              status: str | None = None,
              repo: BibleRepository = Depends(get_repo)):
    """列出梗，可按 category/status 过滤。"""
    return [_gag_dict(g) for g in repo.list_gags(category=category, status=status)]


@router.post("/{project_id}/gags")
def create_gag(project_id: int, data: GagInput,
               repo: BibleRepository = Depends(get_repo)):
    if not data.name:
        raise HTTPException(400, "梗名称不能为空")
    g = repo.create_gag(**data.model_dump())
    return _gag_dict(g)


@router.put("/{project_id}/gags/{gag_id}")
def update_gag(project_id: int, gag_id: int, data: GagInput,
               repo: BibleRepository = Depends(get_repo)):
    g = repo.update_gag(gag_id, **data.model_dump(exclude_unset=True))
    if not g:
        raise HTTPException(404, "梗不存在")
    return _gag_dict(g)


@router.delete("/{project_id}/gags/{gag_id}")
def delete_gag(project_id: int, gag_id: int,
               repo: BibleRepository = Depends(get_repo)):
    if not repo.delete_gag(gag_id):
        raise HTTPException(404, "梗不存在")
    return {"deleted": True}


# ===== 命名权威：别名修正（EntityNameOverride）=====
class NameOverrideInput(BaseModel):
    entity_type: str = "character"   # character/faction/monster/location
    canonical_name: str = ""         # 规范名（Bible 实体名）
    alias: str = ""                  # 被合并的别名/称呼
    note: str = ""


def _name_override_dict(o):
    return {
        "id": o.id,
        "project_id": o.project_id,
        "entity_type": o.entity_type,
        "canonical_name": o.canonical_name,
        "alias": o.alias,
        "note": o.note,
        "created_at": o.created_at.isoformat() if o.created_at else None,
    }


@router.get("/{project_id}/name-overrides")
def list_name_overrides(project_id: int, entity_type: str | None = None,
                        canonical_name: str | None = None,
                        repo: BibleRepository = Depends(get_repo)):
    """列出"我的修正"（别名合并记录），可按 entity_type/canonical_name 过滤。"""
    return [_name_override_dict(o) for o in repo.list_name_overrides(
        entity_type=entity_type, canonical_name=canonical_name)]


@router.post("/{project_id}/name-overrides")
def create_name_override(project_id: int, data: NameOverrideInput,
                         repo: BibleRepository = Depends(get_repo)):
    """新增别名合并：alias 归并到 canonical_name 下。"""
    data.entity_type = (data.entity_type or "").strip().lower()
    data.canonical_name = (data.canonical_name or "").strip()
    data.alias = (data.alias or "").strip()
    if data.entity_type not in ("character", "faction", "monster", "location"):
        raise HTTPException(400, "entity_type 仅支持 character/faction/monster/location")
    if not data.canonical_name or not data.alias:
        raise HTTPException(400, "canonical_name 与 alias 不能为空")
    if data.alias == data.canonical_name:
        raise HTTPException(400, "别名不能与规范名相同")
    try:
        o = repo.create_name_override(**data.model_dump())
    except Exception:
        raise HTTPException(409, "该别名修正记录已存在")
    return _name_override_dict(o)


@router.delete("/{project_id}/name-overrides/{override_id}")
def delete_name_override(project_id: int, override_id: int,
                         repo: BibleRepository = Depends(get_repo)):
    """删除别名修正记录（回滚合并）。"""
    if not repo.delete_name_override(override_id):
        raise HTTPException(404, "别名修正记录不存在")
    return {"deleted": True}


# ===== 文件夹导入（Folder Import）=====
# 独立路由器，注册到 /api/references 前缀（见 app.py）。
references_router = APIRouter()


def get_db_session():
    """获取数据库会话（不带 project_id 参数，用于 references_router）。"""
    cfg = load_config()
    set_config(cfg)
    from novel_agent.bible import database as db_mod
    Base.metadata.create_all(bind=db_mod.engine)
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


class ImportFolderInput(BaseModel):
    project_id: int
    folder_path: str


def _imported_chapter_dict(ic):
    return {
        "id": ic.id,
        "project_id": ic.project_id,
        "source_filename": ic.source_filename,
        "chapter_order": ic.chapter_order,
        "title": ic.title,
        "meta_info": ic.meta_info,
        "chapter_outline": ic.chapter_outline,
        "detail_outline": ic.detail_outline,
        "pleasure_hooks": ic.pleasure_hooks,
        "shell_annotation": ic.shell_annotation,
        "raw_content": ic.raw_content,
        "created_at": ic.created_at.isoformat() if ic.created_at else None,
    }


def _extract_chapter_num(filename: str) -> int:
    """从文件名中提取章节序号，如 '第001章_xxx.md' -> 1。

    支持的模式：
    - "第001章_xxx.md" / "第1章 xxx.md" -> 1
    - "001_xxx.md" / "1-xxx.md" -> 1
    解析失败返回 0。
    """
    import re
    m = re.search(r"第\s*0*(\d+)\s*章", filename)
    if m:
        return int(m.group(1))
    m = re.match(r"^\s*0*(\d+)", filename)
    if m:
        return int(m.group(1))
    return 0


def _parse_md_sections(content: str) -> dict:
    """解析 md 内容中的各个 ## section，返回 {section_name: section_content}。"""
    import re
    sections: dict[str, str] = {}
    pattern = r"^##\s+(.+?)\s*$"
    current_section: str | None = None
    current_lines: list[str] = []
    for line in content.split("\n"):
        m = re.match(pattern, line)
        if m:
            if current_section is not None:
                sections[current_section] = "\n".join(current_lines).strip()
            current_section = m.group(1).strip()
            current_lines = []
        else:
            current_lines.append(line)
    if current_section is not None:
        sections[current_section] = "\n".join(current_lines).strip()
    return sections


def _parse_gags_file(db, project_id: int, filename: str, raw_content: str) -> int:
    """解析梗分析文件，提取 markdown 表格中的梗，写入 gags 表。

    返回导入的梗数量。
    """
    from novel_agent.bible.models import Gag
    import re

    # 分类映射：根据章节标题关键词判断梗类别
    def _category_from_heading(heading: str) -> str:
        h = heading.lower()
        if "对话" in heading or "吐槽" in heading or "金句" in heading:
            return "笑点"
        if "动漫" in heading or "影视" in heading or "二次元" in heading or "流行文化" in heading:
            return "彩蛋"
        if "角色" in heading or "人设" in heading or "关系" in heading:
            return "彩蛋"
        return "桥段"  # 默认

    # 严重度/使用备注：根据套壳指南章节判断
    def _usage_notes_from_heading(heading: str) -> str:
        if "骨级" in heading or "必留" in heading:
            return "骨级-必留"
        if "中级" in heading or "换皮" in heading:
            return "中级-换皮"
        if "皮级" in heading or "必换" in heading:
            return "皮级-必换"
        return ""

    lines = raw_content.split("\n")
    current_heading = ""
    current_category = "桥段"
    current_notes = ""
    count = 0
    in_table = False
    table_header_passed = False

    for line in lines:
        stripped = line.strip()

        # 检测标题
        if stripped.startswith("## ") or stripped.startswith("### "):
            current_heading = stripped.lstrip("#").strip()
            current_category = _category_from_heading(current_heading)
            current_notes = _usage_notes_from_heading(current_heading)
            in_table = False
            table_header_passed = False
            continue

        # 检测表格行
        if stripped.startswith("|") and stripped.endswith("|"):
            cells = [c.strip() for c in stripped.split("|")[1:-1]]

            # 分隔行 |---|---|
            if all(re.match(r'^[-:]+$', c) for c in cells if c):
                table_header_passed = True
                continue

            # 表头行（第一次遇到表格行）
            if not table_header_passed:
                # 检查是否是表头（包含"梗"字）
                if any("梗" in c or "用法" in c or "原型" in c for c in cells):
                    table_header_passed = True
                    continue

            # 数据行
            if table_header_passed and len(cells) >= 2:
                name = cells[0].strip()
                # 去掉 ** 标记
                name = re.sub(r'\*\*', '', name).strip()
                # 去掉引号
                name = name.strip('"\'""''')

                if not name or len(name) > 200:
                    continue

                # 描述 = 其余列拼接
                desc_parts = []
                for c in cells[1:]:
                    c_clean = re.sub(r'\*\*', '', c).strip()
                    if c_clean:
                        desc_parts.append(c_clean)
                description = " | ".join(desc_parts)

                # 跳过空描述
                if not description:
                    description = name

                # 检查是否已存在同名梗
                existing = db.query(Gag).filter(
                    Gag.project_id == project_id,
                    Gag.name == name
                ).first()
                if existing:
                    continue

                gag = Gag(
                    project_id=project_id,
                    name=name,
                    description=description,
                    category=current_category,
                    status="待用",
                    first_chapter=None,
                    usage_notes=current_notes,
                )
                db.add(gag)
                count += 1
        else:
            if in_table and not stripped.startswith("|"):
                in_table = False
                table_header_passed = False

    if count > 0:
        db.commit()
    return count


def _parse_folder_file(filename: str, raw_content: str) -> dict:
    """解析单个文件内容，返回 {title, meta_info, chapter_outline, ...}。

    - md 文件：首行 `# 标题` 作为标题，其余作为内容
    - txt 文件：首行作为标题（或文件名），其余作为内容
    - 解析内容中的 ## 元信息 / ## 章纲 / ## 细纲 / ## 爽点/钩子 / ## 套壳标注
    """
    from pathlib import Path
    suffix = Path(filename).suffix.lower()
    title = ""
    content = raw_content

    if suffix == ".md":
        lines = raw_content.split("\n", 1)
        first_line = lines[0].strip() if lines else ""
        if first_line.startswith("#"):
            title = first_line.lstrip("#").strip()
            content = lines[1] if len(lines) > 1 else ""
        else:
            title = Path(filename).stem
            content = raw_content
    else:
        # txt 文件：首行作为标题（或文件名），其余作为内容
        lines = raw_content.split("\n", 1)
        first_line = lines[0].strip() if lines else ""
        title = first_line if first_line else Path(filename).stem
        content = lines[1] if len(lines) > 1 else ""

    sections = _parse_md_sections(content)

    def _get_section(*keys: str) -> str:
        for sec_name, sec_content in sections.items():
            for k in keys:
                if k in sec_name:
                    return sec_content
        return ""

    return {
        "title": title,
        "meta_info": _get_section("元信息"),
        "chapter_outline": _get_section("章纲"),
        "detail_outline": _get_section("细纲"),
        "pleasure_hooks": _get_section("爽点", "钩子"),
        "shell_annotation": _get_section("套壳标注"),
    }


@references_router.post("/import-folder")
def import_folder(data: ImportFolderInput, db: Session = Depends(get_db_session)):
    """从文件夹导入章节大纲 + 梗库。

    递归扫描 folder_path 下的 .md 和 .txt 文件：
    - 章纲文件（文件名含"第N章"或位于03_章纲目录）-> imported_chapters
    - 梗文件（文件名含"梗"）-> 解析markdown表格 -> gags
    - 其他文件跳过
    """
    from pathlib import Path
    import re as _re

    folder = Path(data.folder_path)
    if not folder.exists() or not folder.is_dir():
        raise HTTPException(400, f"文件夹不存在或不是目录: {data.folder_path}")

    # 递归扫描所有 md/txt 文件
    all_files = sorted(
        [f for f in folder.rglob("*")
         if f.is_file() and f.suffix.lower() in (".md", ".txt")],
        key=lambda f: f.name,
    )

    repo = BibleRepository(db, data.project_id)
    imported = []
    failed = []
    gags_imported = 0

    # 向量库（惰性初始化一次，供各章正文索引复用；初始化失败则跳过索引）
    _archival = None
    try:
        from novel_agent.bible.database import get_config
        from novel_agent.memory.archival import ArchivalMemory
        _archival = ArchivalMemory(get_config(), project_id=data.project_id)
    except Exception as e:
        logger.warning("向量库初始化失败，导入章节将跳过向量索引: %s", e)
        _archival = None

    for f in all_files:
        try:
            raw_content = f.read_text(encoding="utf-8", errors="replace")
            fname_lower = f.name.lower()

            # 梗文件 -> 解析为 gags
            if "梗" in f.name:
                gags_imported += _parse_gags_file(db, data.project_id, f.name, raw_content)
                continue

            # 章纲文件（文件名含"第N章"或位于章纲目录）
            chapter_num = _extract_chapter_num(f.name)
            if chapter_num <= 0:
                continue  # 跳过无法解析章号的文件（避免 order=0 脏数据）

            parsed = _parse_folder_file(f.name, raw_content)

            # 同章旧记录覆盖（避免重复导入）
            existing = repo.get_imported_chapter_by_chapter(chapter_num)
            if existing:
                repo.delete_imported_chapter(existing.id)

            ic = repo.create_imported_chapter(
                source_filename=f.name,
                chapter_order=chapter_num,
                title=parsed["title"],
                meta_info=parsed["meta_info"],
                chapter_outline=parsed["chapter_outline"],
                detail_outline=parsed["detail_outline"],
                pleasure_hooks=parsed["pleasure_hooks"],
                shell_annotation=parsed["shell_annotation"],
                raw_content=raw_content,
            )

            # 向量化索引该章正文（导入进向量库，供检索/记忆召回；失败不影响导入）
            if _archival is not None:
                try:
                    if _archival.is_available():
                        _archival.index_chapter(
                            chapter=chapter_num,
                            title=parsed["title"] or f"第{chapter_num}章",
                            content=raw_content,
                        )
                except Exception as e:
                    logger.warning("导入章节 %d 向量化索引失败: %s", chapter_num, e)

            # 章纲同步写入 Outline 表（level=chapter），供大纲视图与生成流程使用
            try:
                from novel_agent.bible.models import Outline as _OutlineModel
                exists_outline = repo.db.query(_OutlineModel).filter(
                    _OutlineModel.project_id == data.project_id,
                    _OutlineModel.level == "chapter",
                    _OutlineModel.title.like(f"第{chapter_num}章%"),
                ).first()
                if exists_outline is None:
                    repo.create_outline(
                        level="chapter",
                        order=chapter_num,
                        title=parsed["title"] or f"第{chapter_num}章",
                        summary=parsed["chapter_outline"] or "",
                    )
            except Exception as e:
                logger.warning("导入章节 %d 章纲写入 Outline 失败: %s", chapter_num, e)

            imported.append({
                "id": ic.id,
                "filename": f.name,
                "chapter_order": chapter_num,
                "title": parsed["title"],
            })
        except Exception as e:
            failed.append({"filename": f.name, "error": str(e)})

    # 把梗库文件复制到项目数据目录（像CSV一样自动注入，不走用户参考文件机制）
    gag_file_copied = ""
    try:
        from novel_agent.config import load_config
        cfg = load_config()
        project_data_dir = cfg.project_dir(data.project_id)
        for f in all_files:
            if "梗" in f.name and f.suffix.lower() in (".md", ".txt"):
                dest = project_data_dir / "gag_library.md"
                dest.write_text(f.read_text(encoding="utf-8", errors="replace"), encoding="utf-8")
                gag_file_copied = f.name
                break
    except Exception as e:
        failed.append({"filename": "梗库复制", "error": str(e)})

    # 导入成功后，自动创建套壳改写红线（如果尚未存在）
    if imported or gags_imported > 0:
        from novel_agent.bible.models import RedLine
        existing_redlines = db.query(RedLine).filter(
            RedLine.project_id == data.project_id,
            RedLine.scope == "project",
            RedLine.content.like("%相似度%"),
        ).first()
        if not existing_redlines:
            # 写入调研得到的红线值
            default_red_lines = [
                ("文字相似度不得超过30%（原创度≥70%），连续相同字数不得超过13字（知网CNKI标准）", "hard"),
                ("关键情节节点与原文一一对应不得超过5个（司法实践：琼瑶诉于正案标准）", "hard"),
                ("主角团人设配置不得照搬原文（姓名/外貌/性格/关系可换，但核心人设组合不可完全复制）", "hard"),
                ("正文不得出现原文连续20字以上的逐字复制（含标点）", "hard"),
                ("套壳标注中【骨】保留的剧情骨架必须保留，但表达方式（文字/对话/场景）必须完全重写", "soft"),
            ]
            for content, severity in default_red_lines:
                rl = RedLine(
                    project_id=data.project_id,
                    scope="project",
                    chapter_num=None,
                    content=content,
                    severity=severity,
                    enabled=True,
                )
                db.add(rl)
            db.commit()

    return {
        "project_id": data.project_id,
        "folder_path": data.folder_path,
        "total_files": len(all_files),
        "imported_count": len(imported),
        "gags_imported": gags_imported,
        "failed_count": len(failed),
        "imported": imported,
        "failed": failed,
    }


class ScanFolderInput(BaseModel):
    folder_path: str
    overwrite: bool = False


@router.post("/{project_id}/scan-folder")
async def scan_folder(project_id: int, data: ScanFolderInput,
                      repo: BibleRepository = Depends(get_repo)):
    """AI 扫描文件夹：递归读取所有文件内容，用 AI 识别设定并导入设定库。

    支持 txt/md/json/csv/html/docx/pdf 等格式。
    自动提取角色/世界观/势力/伏笔/大纲/怪物/金手指等设定，去重后写入数据库。
    """
    import asyncio
    import logging
    import re
    from pathlib import Path
    from novel_agent.llm.client import LLMClient
    from novel_agent.utils.file_extract import _extract_text_plain, _extract_docx, _extract_pdf

    logger = logging.getLogger(__name__)

    folder = Path(data.folder_path)
    if not folder.exists() or not folder.is_dir():
        raise HTTPException(400, f"文件夹不存在或不是目录: {data.folder_path}")

    # 递归扫描所有支持的文件
    supported_exts = {".txt", ".md", ".json", ".csv", ".html", ".htm", ".docx", ".pdf", ".rst", ".log"}
    all_files = sorted(
        [f for f in folder.rglob("*") if f.is_file() and f.suffix.lower() in supported_exts],
        key=lambda f: str(f.relative_to(folder)),
    )
    if not all_files:
        raise HTTPException(400, "文件夹中未找到支持的文件（txt/md/json/csv/html/docx/pdf）")

    # 提取每个文件的文本
    extracted = []
    failed = []
    for f in all_files:
        try:
            content_bytes = f.read_bytes()
            suffix = f.suffix.lower()
            if suffix == ".docx":
                text = _extract_docx(content_bytes)
            elif suffix == ".pdf":
                text = _extract_pdf(content_bytes)
            else:
                text = _extract_text_plain(content_bytes)
            if text and text.strip():
                rel_path = str(f.relative_to(folder))
                extracted.append({"path": rel_path, "text": text})
            else:
                failed.append({"path": str(f.relative_to(folder)), "error": "文件内容为空"})
        except Exception as e:
            failed.append({"path": str(f.relative_to(folder)), "error": str(e)})

    if not extracted:
        raise HTTPException(400, "所有文件提取失败或内容为空")

    # 合并文件内容：按文件边界分批（每批 ≤ 25 万字），避免超大文件夹被截断、
    # 也避免单次 LLM 输出超限导致细纲/章纲丢失。每批内仍按文件夹分组标注。
    batch_max_chars = 250000
    batches: list[list[dict]] = []
    cur_batch: list[dict] = []
    cur_chars = 0
    for item in extracted:
        if cur_batch and cur_chars + len(item["text"]) > batch_max_chars:
            batches.append(cur_batch)
            cur_batch, cur_chars = [], 0
        cur_batch.append(item)
        cur_chars += len(item["text"])
    if cur_batch:
        batches.append(cur_batch)

    def _build_merged_text(batch: list[dict]) -> str:
        """把一批文件合并为文本，按文件夹分组标注，帮 AI 理解组织结构（不截断）。"""
        parts = []
        current_dir = None
        for item in batch:
            item_dir = str(Path(item["path"]).parent)
            if item_dir != current_dir:
                current_dir = item_dir
                if item_dir and item_dir != ".":
                    parts.append(f"\n===== 文件夹：{item_dir}/ =====\n")
            parts.append(f"--- 文件：{item['path']} ---\n")
            parts.append(item["text"])
            parts.append("\n\n")
        return "".join(parts)

    # 结构化解析（快，不依赖 LLM）：对规整/半规整的细纲、章纲文件
    # （含章标题行 + 剧情/信息增量等维度行）直接照搬原文解析，先立即落库，
    # 保证细纲/章纲最先可见。避免超大文档被截断/输出超限。
    structured: list[OutlineInput] = []
    for item in extracted:
        # gate：文件含"第N章"标题行 + 含"剧情/信息增量/章末钩子/爽点设计"维度行
        # 章标题可能有 ** 前缀（**第N章 xxx**），维度行可能有 - **剧情**：/ **剧情**：/ - 剧情：/ 剧情： 等变体
        if (re.search(r"^\*{0,2}第\s*\d+\s*章", item["text"], re.M)
                and re.search(r"^[-*\s]*\*{0,2}(?:剧情|信息增量|章末钩子|爽点设计)\*{0,2}\s*[：:]", item["text"], re.M)):
            try:
                structured.extend(_parse_structured_outlines(item["text"], item["path"]))
            except Exception as e:
                logger.warning("结构化解析失败 %s: %s", item["path"], e)
    struct_added: dict = {}
    if structured:
        logger.info("scan-folder: 结构化解析出 %d 条大纲（卷/细纲/章纲照搬原文），先落库", len(structured))
        struct_added = _apply_import_data(repo, ImportData(outlines=structured), overwrite=data.overwrite)

    # AI 解析提取设定（分批串行，每批内部 8 类并发；此步较慢）
    cfg = load_config()
    client = LLMClient(cfg.get_agent_llm("architect"))
    import_data = ImportData()
    try:
        for i, batch in enumerate(batches, 1):
            merged_text = _build_merged_text(batch)
            logger.info("scan-folder: 分批 %d/%d, %d 个文件, %d 字符, 开始 AI 解析",
                        i, len(batches), len(batch), len(merged_text))
            try:
                batch_data = await _parse_text(client, merged_text)
                import_data = _merge_import_data(import_data, batch_data)
            except Exception as e:
                logger.warning("scan-folder: 分批 %d/%d 解析失败，跳过此批: %s", i, len(batches), e)
    finally:
        await client.close()

    total_merged_chars = sum(len(_build_merged_text(b)) for b in batches)
    logger.info("scan-folder: %d 个文件共 %d 字符, 分 %d 批解析完成",
                len(extracted), total_merged_chars, len(batches))

    # 导入 AI 提取的设定（不含结构化大纲--已在前面先落库了）
    added = _apply_import_data(repo, import_data, overwrite=data.overwrite)

    # 构建完整提取内容（所有字段都返回，前端完整展示）
    imported_items = {
        "world_settings": [w.model_dump() for w in import_data.world_settings],
        "characters": [c.model_dump() for c in import_data.characters],
        "factions": [f.model_dump() for f in import_data.factions],
        "foreshadows": [f.model_dump() for f in import_data.foreshadows],
        "outlines": [o.model_dump() for o in import_data.outlines],
        "monsters": [m.model_dump() for m in import_data.monsters],
        "instances": [i.model_dump() for i in import_data.instances],
        "character_relationships": [r.model_dump() for r in import_data.character_relationships],
        "faction_relationships": [r.model_dump() for r in import_data.faction_relationships],
    }

    return {
        "project_id": project_id,
        "folder_path": data.folder_path,
        "total_files": len(all_files),
        "extracted_files": len(extracted),
        "failed_files": len(failed),
        "merged_chars": total_merged_chars,
        "imported": added,
        "imported_items": imported_items,
        "extracted_file_list": [{"path": e["path"], "chars": len(e["text"])} for e in extracted],
        "failed": failed,
    }


@references_router.get("/imported-chapters/{project_id}")
def list_imported_chapters(project_id: int, db: Session = Depends(get_db_session)):
    """列出已导入的章节大纲。"""
    repo = BibleRepository(db, project_id)
    return [_imported_chapter_dict(ic) for ic in repo.list_imported_chapters()]


@references_router.delete("/imported-chapters/{imported_id}")
def delete_imported_chapter(imported_id: int, db: Session = Depends(get_db_session)):
    """删除单个导入章节。"""
    from novel_agent.bible.models import ImportedChapter
    ic = db.query(ImportedChapter).filter(ImportedChapter.id == imported_id).first()
    if not ic:
        raise HTTPException(404, "导入章节不存在")
    db.delete(ic)
    db.commit()
    return {"deleted": True}


@references_router.get("/imported-chapters/{project_id}/chapter/{chapter_num}")
def get_imported_chapter_by_chapter(project_id: int, chapter_num: int,
                                    db: Session = Depends(get_db_session)):
    """获取指定章节的导入大纲（用于生成时注入）。"""
    repo = BibleRepository(db, project_id)
    ic = repo.get_imported_chapter_by_chapter(chapter_num)
    if not ic:
        raise HTTPException(404, f"章节 {chapter_num} 的导入大纲不存在")
    return _imported_chapter_dict(ic)
