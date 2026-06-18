"""章节生成 API + 列表 + 正文。"""
from __future__ import annotations
import asyncio
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from novel_agent.bible.database import SessionLocal, set_config
from novel_agent.bible.models import Base
from novel_agent.bible.repository import BibleRepository
from novel_agent.config import load_config
from novel_agent.orchestrator.runner import ChapterRunner

router = APIRouter()


class GenerateRequest(BaseModel):
    project_id: int
    chapter: int
    title: str
    thread_id: str | None = None


@router.post("/generate")
def generate_chapter(req: GenerateRequest):
    cfg = load_config()
    set_config(cfg)
    from novel_agent.bible import database as db_mod
    Base.metadata.create_all(bind=db_mod.engine)
    db = SessionLocal()
    repo = BibleRepository(db, project_id=req.project_id)
    runner = ChapterRunner(cfg, repo=repo)
    try:
        result = asyncio.run(runner.run(
            chapter=req.chapter, title=req.title, thread_id=req.thread_id))
        return result
    finally:
        runner.close()
        db.close()


@router.get("/list")
def list_chapters(project_id: int):
    from novel_agent.memory.recall import RecallMemory
    cfg = load_config()
    recall = RecallMemory(cfg)
    chapters = recall.list_chapters()
    return [{"chapter": c, "text_preview": recall.read_chapter_text(c)[:200]} for c in chapters]


@router.get("/{chapter}/text")
def get_chapter_text(chapter: int):
    from novel_agent.memory.recall import RecallMemory
    cfg = load_config()
    recall = RecallMemory(cfg)
    text = recall.read_chapter_text(chapter)
    if not text:
        raise HTTPException(404, "章节不存在")
    return {"chapter": chapter, "text": text}
