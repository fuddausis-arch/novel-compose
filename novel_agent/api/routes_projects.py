"""项目 CRUD API。"""
from __future__ import annotations
import shutil
from pathlib import Path
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
    template_key: str | None = None


def _setup_db():
    cfg = load_config()
    set_config(cfg)
    from novel_agent.bible import database as db_mod
    Base.metadata.create_all(bind=db_mod.engine)
    return SessionLocal()


def _template_dir() -> Path:
    return Path(__file__).resolve().parent.parent / "templates" / "genres"


def _load_template_text(template_key: str | None) -> str | None:
    if not template_key:
        return None
    template_path = _template_dir() / f"{template_key}.md"
    if not template_path.exists():
        return None
    return template_path.read_text(encoding="utf-8")


@router.get("/templates/genres")
def list_genre_templates():
    """列出内置小说题材模板。"""
    d = _template_dir()
    if not d.exists():
        return []
    templates = []
    for p in sorted(d.glob("*.md")):
        key = p.stem
        templates.append({"key": key, "title": key, "description": ""})
    return templates


@router.post("")
def create_project(data: ProjectCreate):
    cfg = load_config()
    db = _setup_db()
    try:
        style = data.style
        # 如果选择了模板且没填自定义风格，把模板内容追加到 style
        template_text = _load_template_text(data.template_key)
        if template_text:
            style = f"{style}\n\n【模板要求】\n{template_text}".strip()
        p = Project(title=data.title, genre=data.genre, summary=data.summary, style=style)
        db.add(p); db.commit(); db.refresh(p)
        # 创建项目专属目录
        cfg.project_dir(p.id).mkdir(parents=True, exist_ok=True)
        cfg.project_chapters_dir(p.id).mkdir(parents=True, exist_ok=True)
        return {"id": p.id, "title": p.title, "genre": p.genre, "summary": p.summary, "style": style}
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
    """删除项目。purge_data=True 同时删除其所有圣经数据与项目目录。"""
    cfg = load_config()
    db = _setup_db()
    try:
        p = db.query(Project).filter(Project.id == project_id).first()
        if not p:
            raise HTTPException(404, "项目不存在")
        if purge_data:
            repo = BibleRepository(db, project_id=project_id)
            deleted = repo.delete_all_project_data()
        db.delete(p); db.commit()
        # 删除项目专属目录
        project_dir = cfg.project_dir(project_id)
        if project_dir.exists():
            shutil.rmtree(project_dir)
        return {"deleted": True, "project_id": project_id,
                "data_purged": deleted if purge_data else 0}
    finally:
        db.close()


class BatchDeleteRequest(BaseModel):
    project_ids: list[int]


@router.post("/batch/delete")
def batch_delete_projects(req: BatchDeleteRequest):
    """批量删除项目。"""
    cfg = load_config()
    db = _setup_db()
    deleted_ids = []
    try:
        for pid in req.project_ids:
            p = db.query(Project).filter(Project.id == pid).first()
            if not p:
                continue
            try:
                repo = BibleRepository(db, project_id=pid)
                repo.delete_all_project_data()
            except Exception:
                pass
            db.delete(p)
            project_dir = cfg.project_dir(pid)
            if project_dir.exists():
                shutil.rmtree(project_dir, ignore_errors=True)
            deleted_ids.append(pid)
        db.commit()
        return {"deleted": True, "project_ids": deleted_ids, "count": len(deleted_ids)}
    finally:
        db.close()
