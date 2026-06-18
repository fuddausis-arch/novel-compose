"""圣经 CRUD API：角色/伏笔/大纲/摘要 + 创建/编辑/删除/导入。"""
from __future__ import annotations
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from novel_agent.bible.database import SessionLocal, set_config
from novel_agent.bible.models import Base, Foreshadow, Character
from novel_agent.bible.repository import BibleRepository
from novel_agent.config import load_config

router = APIRouter()


def _repo(project_id: int):
    cfg = load_config()
    set_config(cfg)
    from novel_agent.bible import database as db_mod
    Base.metadata.create_all(bind=db_mod.engine)
    db = SessionLocal()
    return db, BibleRepository(db, project_id=project_id)


# ---- 角色 ----
@router.get("/{project_id}/characters")
def list_characters(project_id: int):
    db, repo = _repo(project_id)
    try:
        return [_char_dict(c) for c in repo.list_characters()]
    finally:
        db.close()


def _char_dict(c):
    return {"id": c.id, "name": c.name, "role": c.role, "personality": c.personality,
            "motivation": c.motivation, "current_location": c.current_location,
            "current_emotion": c.current_emotion, "known_info": c.known_info,
            "background": c.background, "arc": c.arc, "relationships": c.relationships,
            "secrets": c.secrets}


class CharacterInput(BaseModel):
    name: str
    role: str = ""
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
        return [{"id": f.foreshadow_id, "tier": f.tier, "status": f.status,
                 "description": f.description, "plant_chapter": f.plant_chapter,
                 "resolve_chapter": f.planned_resolve_chapter} for f in fs]
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
def list_outlines(project_id: int):
    db, repo = _repo(project_id)
    try:
        return [{"id": o.id, "level": o.level, "order": o.order,
                 "title": o.title, "summary": o.summary}
                for o in repo.list_outlines()]
    finally:
        db.close()


class OutlineInput(BaseModel):
    level: str = "chapter"
    order: int = 0
    act: str = ""
    title: str = ""
    summary: str = ""


@router.post("/{project_id}/outlines")
def create_outline(project_id: int, data: OutlineInput):
    db, repo = _repo(project_id)
    try:
        o = repo.create_outline(**data.model_dump())
        return {"id": o.id, "order": o.order, "title": o.title, "summary": o.summary}
    finally:
        db.close()


@router.put("/{project_id}/outlines/{order}")
def update_outline(project_id: int, order: int, data: OutlineInput):
    db, repo = _repo(project_id)
    try:
        o = repo.update_outline(order, **data.model_dump())
        if not o:
            raise HTTPException(404, "大纲条目不存在")
        return {"id": o.id, "order": o.order, "title": o.title, "summary": o.summary}
    finally:
        db.close()


@router.delete("/{project_id}/outlines/{order}")
def delete_outline(project_id: int, order: int):
    db, repo = _repo(project_id)
    try:
        if not repo.delete_outline(order):
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


# ---- 批量导入 ----
class ImportData(BaseModel):
    """批量导入设定数据（角色/伏笔/大纲）。"""
    characters: list[CharacterInput] = []
    foreshadows: list[ForeshadowInput] = []
    outlines: list[OutlineInput] = []


@router.post("/{project_id}/import")
def import_settings(project_id: int, data: ImportData):
    """批量导入世界观/设定数据。已存在的跳过。"""
    db, repo = _repo(project_id)
    try:
        added = {"characters": 0, "foreshadows": 0, "outlines": 0}
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
        return {"imported": added}
    finally:
        db.close()
