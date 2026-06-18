"""项目 CRUD API。"""
from __future__ import annotations
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from novel_agent.bible.database import SessionLocal, set_config
from novel_agent.bible.models import Base, Project
from novel_agent.bible.repository import BibleRepository
from novel_agent.config import load_config

router = APIRouter()


class ProjectCreate(BaseModel):
    title: str
    genre: str = ""
    summary: str = ""
    style: str = ""


def _setup_db():
    cfg = load_config()
    set_config(cfg)
    from novel_agent.bible import database as db_mod
    Base.metadata.create_all(bind=db_mod.engine)
    return SessionLocal()


@router.post("")
def create_project(data: ProjectCreate):
    db = _setup_db()
    try:
        p = Project(title=data.title, genre=data.genre, summary=data.summary, style=data.style)
        db.add(p); db.commit(); db.refresh(p)
        return {"id": p.id, "title": p.title, "genre": p.genre, "summary": p.summary}
    finally:
        db.close()


@router.get("")
def list_projects():
    db = _setup_db()
    try:
        projects = db.query(Project).order_by(Project.id.desc()).all()
        return [{"id": p.id, "title": p.title, "genre": p.genre, "summary": p.summary}
                for p in projects]
    finally:
        db.close()


@router.get("/{project_id}")
def get_project(project_id: int):
    db = _setup_db()
    try:
        p = db.query(Project).filter(Project.id == project_id).first()
        if not p:
            raise HTTPException(404, "项目不存在")
        return {"id": p.id, "title": p.title, "genre": p.genre, "summary": p.summary, "style": p.style}
    finally:
        db.close()


class ProjectUpdate(BaseModel):
    title: str | None = None
    genre: str | None = None
    summary: str | None = None
    style: str | None = None


@router.put("/{project_id}")
def update_project(project_id: int, data: ProjectUpdate):
    db = _setup_db()
    try:
        p = db.query(Project).filter(Project.id == project_id).first()
        if not p:
            raise HTTPException(404, "项目不存在")
        for k in ("title", "genre", "summary", "style"):
            v = getattr(data, k)
            if v is not None:
                setattr(p, k, v)
        db.commit(); db.refresh(p)
        return {"id": p.id, "title": p.title, "genre": p.genre, "summary": p.summary, "style": p.style}
    finally:
        db.close()


@router.delete("/{project_id}")
def delete_project(project_id: int, purge_data: bool = True):
    """删除项目。purge_data=True 同时删除其所有圣经数据。"""
    db = _setup_db()
    try:
        p = db.query(Project).filter(Project.id == project_id).first()
        if not p:
            raise HTTPException(404, "项目不存在")
        if purge_data:
            repo = BibleRepository(db, project_id=project_id)
            deleted = repo.delete_all_project_data()
        db.delete(p); db.commit()
        return {"deleted": True, "project_id": project_id,
                "data_purged": deleted if purge_data else 0}
    finally:
        db.close()
