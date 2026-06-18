"""规划 API：启动卷级规划 + 人审① resume。"""
from __future__ import annotations
import asyncio
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from novel_agent.bible.database import SessionLocal, set_config
from novel_agent.bible.models import Base, Project
from novel_agent.bible.repository import BibleRepository
from novel_agent.config import load_config
from novel_agent.planning.runner import VolumeRunner

router = APIRouter()


class PlanRequest(BaseModel):
    project_id: int
    volume: str = "卷一"
    chapter_count: int = 30
    thread_id: str


class ResumeRequest(BaseModel):
    thread_id: str
    approved: bool
    edits: str = ""


def _get_repo(project_id: int):
    cfg = load_config()
    set_config(cfg)
    from novel_agent.bible import database as db_mod
    Base.metadata.create_all(bind=db_mod.engine)
    db = SessionLocal()
    return db, BibleRepository(db, project_id=project_id)


@router.post("/run")
def run_planning(req: PlanRequest):
    db, repo = _get_repo(req.project_id)
    runner = VolumeRunner(load_config(), repo=repo)
    try:
        async def _go():
            result = await runner.run(
                volume=req.volume, chapter_count=req.chapter_count, thread_id=req.thread_id)
            await runner.aclose()
            return result
        result = asyncio.run(_go())
        result["thread_id"] = req.thread_id
        return result
    finally:
        db.close()


@router.post("/resume")
def resume_planning(req: ResumeRequest):
    cfg = load_config()
    set_config(cfg)
    from novel_agent.bible import database as db_mod
    Base.metadata.create_all(bind=db_mod.engine)
    db = SessionLocal()
    project = db.query(Project).order_by(Project.id.desc()).first()
    if not project:
        raise HTTPException(400, "无项目")
    repo = BibleRepository(db, project_id=project.id)
    runner = VolumeRunner(cfg, repo=repo)
    try:
        async def _go():
            result = await runner.resume(
                {"approved": req.approved, "edits": req.edits}, thread_id=req.thread_id)
            await runner.aclose()
            return result
        result = asyncio.run(_go())
        return result
    finally:
        db.close()
