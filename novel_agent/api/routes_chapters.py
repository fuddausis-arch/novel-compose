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
    """列出项目下的所有章节。注意：此路由必须在 /{chapter}/text 之前注册，避免被当作 chapter 参数。"""
    from novel_agent.memory.recall import RecallMemory
    cfg = load_config()
    recall = RecallMemory(cfg, project_id=project_id)
    chapters = recall.list_chapters()
    return [{"chapter": c, "text_preview": recall.read_chapter_text(c)[:200]} for c in chapters]


@router.get("/generate/stream")
async def generate_chapter_stream(project_id: int, chapter: int, title: str,
                                  thread_id: str | None = None):
    """SSE 流式生成章节，实时推送节点状态（assemble/write/audit/polish/...）。"""
    import json
    import uuid
    from sse_starlette.sse import EventSourceResponse

    cfg = load_config()
    set_config(cfg)
    from novel_agent.bible import database as db_mod
    Base.metadata.create_all(bind=db_mod.engine)
    db = SessionLocal()
    repo = BibleRepository(db, project_id=project_id)
    runner = ChapterRunner(cfg, repo=repo)
    tid = thread_id or str(uuid.uuid4())

    async def event_generator():
        initial = {"project_id": project_id, "chapter": chapter, "title": title,
                   "context": "", "draft": "", "status": "pending", "error": "",
                   "word_count": 0, "draft_version": 0, "review_iterations": 0}
        try:
            async for mode, chunk in runner.graph.astream(
                initial,
                config={"configurable": {"thread_id": tid}},
                stream_mode=["updates"],
            ):
                if mode == "updates":
                    for node_name, node_output in chunk.items():
                        yield {"event": "node", "data": json.dumps({
                            "node": node_name, "output": node_output,
                        }, ensure_ascii=False, default=str)}
            yield {"event": "done", "data": json.dumps({"status": "completed", "thread_id": tid})}
        except Exception as e:
            yield {"event": "error", "data": json.dumps({"message": str(e)})}
        finally:
            runner.close()
            db.close()

    return EventSourceResponse(event_generator())


@router.get("/{chapter}/text")
def get_chapter_text(chapter: int, project_id: int):
    """获取章节正文（去除 markdown 标题行，只返回正文）。"""
    from novel_agent.memory.recall import RecallMemory
    cfg = load_config()
    recall = RecallMemory(cfg, project_id=project_id)
    raw = recall.read_chapter_text(chapter)
    if not raw:
        raise HTTPException(404, "章节不存在")
    lines = raw.splitlines()
    # 跳过第一行 markdown 标题
    text = "\n".join(lines[1:]).lstrip("\n")
    return {"chapter": chapter, "text": text}


class ChapterTextEdit(BaseModel):
    title: str = ""
    content: str = ""


@router.put("/{chapter}/text")
def save_chapter_text(chapter: int, project_id: int, data: ChapterTextEdit):
    """编辑后保存章节正文到文件。"""
    from novel_agent.memory.recall import RecallMemory
    cfg = load_config()
    recall = RecallMemory(cfg, project_id=project_id)
    path = recall.save_chapter_text(chapter=chapter, title=data.title,
                                    content=data.content)
    return {"chapter": chapter, "saved": True, "path": str(path)}


@router.delete("/{chapter}")
def delete_chapter(chapter: int, project_id: int):
    """删除章节正文文件 + 圣经摘要。"""
    from novel_agent.memory.recall import RecallMemory
    cfg = load_config()
    recall = RecallMemory(cfg, project_id=project_id)
    # 删正文文件
    pattern = f"第{chapter:03d}章_*.md"
    deleted_files = []
    for p in recall.chapters_dir.glob(pattern):
        p.unlink()
        deleted_files.append(str(p))
    # 删圣经摘要
    db_deleted = False
    db = SessionLocal()
    try:
        set_config(load_config())
        from novel_agent.bible import database as db_mod
        Base.metadata.create_all(bind=db_mod.engine)
        repo = BibleRepository(db, project_id=project_id)
        db_deleted = repo.delete_chapter_summary(chapter)
    finally:
        db.close()
    return {"deleted": True, "files": deleted_files, "summary_removed": db_deleted}


@router.get("/export/txt")
def export_txt(project_id: int):
    """导出全部章节为单个 TXT。"""
    from novel_agent.memory.recall import RecallMemory
    from fastapi.responses import PlainTextResponse
    cfg = load_config()
    recall = RecallMemory(cfg, project_id=project_id)
    chapters = recall.list_chapters()
    parts = []
    for ch in chapters:
        text = recall.read_chapter_text(ch)
        if text:
            parts.append(text)
    return PlainTextResponse("\n\n".join(parts), media_type="text/plain",
                             headers={"Content-Disposition": "attachment; filename=novel.txt"})
