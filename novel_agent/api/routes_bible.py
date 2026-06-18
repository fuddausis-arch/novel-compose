"""圣经浏览 API：角色/伏笔/大纲/摘要。"""
from __future__ import annotations
from fastapi import APIRouter, HTTPException
from novel_agent.bible.database import SessionLocal, set_config
from novel_agent.bible.models import Base, Foreshadow
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


@router.get("/{project_id}/characters")
def list_characters(project_id: int):
    db, repo = _repo(project_id)
    try:
        return [{"name": c.name, "role": c.role, "personality": c.personality,
                 "current_location": c.current_location, "current_emotion": c.current_emotion}
                for c in repo.list_characters()]
    finally:
        db.close()


@router.get("/{project_id}/foreshadows")
def list_foreshadows(project_id: int):
    db, repo = _repo(project_id)
    try:
        fs = db.query(Foreshadow).filter(Foreshadow.project_id == project_id).all()
        return [{"id": f.foreshadow_id, "status": f.status, "description": f.description,
                 "plant_chapter": f.plant_chapter, "resolve_chapter": f.planned_resolve_chapter}
                for f in fs]
    finally:
        db.close()


@router.get("/{project_id}/outlines")
def list_outlines(project_id: int):
    db, repo = _repo(project_id)
    try:
        return [{"level": o.level, "order": o.order, "title": o.title, "summary": o.summary}
                for o in repo.list_outlines()]
    finally:
        db.close()


@router.get("/{project_id}/summaries")
def list_summaries(project_id: int):
    db, repo = _repo(project_id)
    try:
        return [{"chapter": s.chapter, "title": s.title, "core_events": s.core_events,
                 "word_count": s.word_count}
                for s in repo.list_chapter_summaries(limit=100)]
    finally:
        db.close()
