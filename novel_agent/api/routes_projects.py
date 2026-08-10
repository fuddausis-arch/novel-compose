"""项目 CRUD API。"""
from __future__ import annotations
import re
import shutil
from pathlib import Path
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field, field_validator
from novel_agent.bible.database import SessionLocal, set_config
from novel_agent.bible.models import Base, Project
from novel_agent.bible.repository import BibleRepository
from novel_agent.config import load_config

router = APIRouter()


class ProjectCreate(BaseModel):
    title: str = Field(min_length=1, max_length=500)
    genre: str = Field(default="", max_length=200)
    summary: str = Field(default="", max_length=10000)
    style: str = Field(default="", max_length=2000)
    template_key: str | None = None

    @field_validator("title")
    @classmethod
    def title_must_not_be_blank(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("标题不能为空")
        return v.strip()


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
    # 防路径穿越：禁止 / \ .. 等路径分隔符
    if any(c in template_key for c in '/\\') or template_key.startswith('.'):
        return None
    template_path = _template_dir() / f"{template_key}.md"
    # 确保路径在模板目录内
    try:
        template_path.resolve().relative_to(_template_dir().resolve())
    except ValueError:
        return None
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
        # 从模板文件提取标题和核心卖点作为 description
        text = p.read_text(encoding="utf-8")
        title = key
        desc = ""
        for line in text.splitlines():
            line = line.strip()
            if line.startswith("# "):
                title = line[2:].strip()
            elif line.startswith("## 核心卖点") :
                # 取下一行
                idx = text.splitlines().index([l for l in text.splitlines() if l.strip().startswith("## 核心卖点")][0])
                if idx + 1 < len(text.splitlines()):
                    desc = text.splitlines()[idx + 1].strip()
                break
        templates.append({"key": key, "title": title, "description": desc})
    return templates


@router.post("")
def create_project(data: ProjectCreate):
    cfg = load_config()
    db = _setup_db()
    try:
        style = data.style
        genre = data.genre
        # 如果选择了模板，把模板的 genre 作为项目 genre，模板内容追加到 style
        template_text = _load_template_text(data.template_key)
        if template_text:
            # 从模板标题提取题材名
            for line in template_text.splitlines():
                line = line.strip()
                if line.startswith("# "):
                    genre = genre or line[2:].strip()
                    break
            style = f"{style}\n\n【题材模板】\n{template_text}".strip()
        p = Project(title=data.title, genre=genre, summary=data.summary, style=style)
        db.add(p); db.commit(); db.refresh(p)
        # 创建项目专属目录
        cfg.project_dir(p.id).mkdir(parents=True, exist_ok=True)
        cfg.project_chapters_dir(p.id).mkdir(parents=True, exist_ok=True)
        return _project_to_dict(p)
    finally:
        db.close()


@router.get("")
def list_projects():
    db = _setup_db()
    try:
        projects = db.query(Project).order_by(Project.id.desc()).all()
        return [_project_to_dict(p) for p in projects]
    finally:
        db.close()


@router.get("/{project_id}")
def get_project(project_id: int):
    db = _setup_db()
    try:
        p = db.query(Project).filter(Project.id == project_id).first()
        if not p:
            raise HTTPException(404, "项目不存在")
        return _project_to_dict(p)
    finally:
        db.close()


class ProjectUpdate(BaseModel):
    title: str | None = Field(default=None, min_length=1, max_length=500)
    genre: str | None = Field(default=None, max_length=200)
    summary: str | None = Field(default=None, max_length=10000)
    style: str | None = Field(default=None, max_length=2000)
    constitution: str | None = None
    target_audience: str | None = None
    central_concept: str | None = None

    @field_validator("title")
    @classmethod
    def title_must_not_be_blank(cls, v: str | None) -> str | None:
        if v is not None and not v.strip():
            raise ValueError("标题不能为空")
        return v.strip() if v is not None else None
    word_count_target: int | None = None
    target_volumes: int | None = None
    golden_finger: str | None = None


def _project_to_dict(p: Project) -> dict:
    return {"id": p.id, "title": p.title, "genre": p.genre, "summary": p.summary, "style": p.style,
            "constitution": p.constitution or "",
            "target_audience": p.target_audience or "",
            "central_concept": p.central_concept or "",
            "word_count_target": p.word_count_target or 0,
            "target_volumes": p.target_volumes or 0,
            "golden_finger": p.golden_finger or "",
            "created_at": p.created_at.isoformat() if p.created_at else None,
            "updated_at": p.updated_at.isoformat() if p.updated_at else None}


@router.put("/{project_id}")
def update_project(project_id: int, data: ProjectUpdate):
    db = _setup_db()
    try:
        p = db.query(Project).filter(Project.id == project_id).first()
        if not p:
            raise HTTPException(404, "项目不存在")
        for k in ("title", "genre", "summary", "style", "constitution",
                  "target_audience", "central_concept", "word_count_target",
                  "target_volumes", "golden_finger"):
            v = getattr(data, k)
            if v is not None:
                setattr(p, k, v)
        db.commit(); db.refresh(p)
        return _project_to_dict(p)
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
        # 先关闭该项目的 chroma 向量库连接，释放 sqlite 文件锁，
        # 否则 Windows 上 rmtree 报 PermissionError（chroma.sqlite3 被占用）
        from novel_agent.memory.archival import close_project_memories
        close_project_memories(project_id)
        # 删除项目专属目录
        project_dir = cfg.project_dir(project_id)
        if project_dir.exists():
            shutil.rmtree(project_dir, ignore_errors=True)
        return {"deleted": True, "project_id": project_id,
                "data_purged": deleted if purge_data else 0}
    finally:
        db.close()


class BatchDeleteRequest(BaseModel):
    project_ids: list[int]


@router.post("/batch/delete")
def batch_delete_projects(req: BatchDeleteRequest):
    """批量删除项目。单项目失败不阻塞其余删除。"""
    cfg = load_config()
    db = _setup_db()
    deleted_ids = []
    failed_ids: list[dict] = []
    try:
        for pid in req.project_ids:
            p = db.query(Project).filter(Project.id == pid).first()
            if not p:
                continue
            try:
                repo = BibleRepository(db, project_id=pid)
                repo.delete_all_project_data()
                db.delete(p)
                db.commit()
            except Exception as e:
                db.rollback()
                failed_ids.append({"project_id": pid, "error": str(e)})
                continue
            # 释放该项目的 chroma 文件锁后删除目录（Windows 上锁文件导致 rmtree 失败）
            try:
                from novel_agent.memory.archival import close_project_memories
                close_project_memories(pid)
            except Exception:
                pass
            project_dir = cfg.project_dir(pid)
            if project_dir.exists():
                shutil.rmtree(project_dir, ignore_errors=True)
            deleted_ids.append(pid)
        return {"deleted": True, "project_ids": deleted_ids,
                "count": len(deleted_ids), "failed": failed_ids}
    finally:
        db.close()
