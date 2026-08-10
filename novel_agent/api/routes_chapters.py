"""章节生成 API + 列表 + 正文。"""
from __future__ import annotations
import asyncio
import logging
from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel
from novel_agent.api.app import limiter
from novel_agent.bible.database import SessionLocal, set_config
from novel_agent.bible.models import Base
from novel_agent.bible.repository import BibleRepository
from novel_agent.config import load_config
from novel_agent.orchestrator.runner import ChapterRunner

logger = logging.getLogger(__name__)
router = APIRouter()


class GenerateRequest(BaseModel):
    project_id: int
    chapter: int
    title: str
    thread_id: str | None = None


def _extract_interrupt_value(state) -> dict:
    """从 LangGraph state 提取 interrupt 值（astream 被 human_review 暂停时）。

    LangGraph 的 interrupt 不会推送节点更新，只能在 astream 结束后通过
    aget_state 检查 state.next，再从 task.interrupts 中取出中断值作为
    review_pending 事件的 payload。generate 与 resume 两条路径共用。
    """
    interrupt_data: dict = {}
    if not state:
        return interrupt_data
    for task in state.tasks:
        if hasattr(task, "interrupts") and task.interrupts:
            for intr in task.interrupts:
                interrupt_data = intr.value if hasattr(intr, "value") else {}
                break
    return interrupt_data


@router.post("/generate")
@limiter.limit("10/minute")
async def generate_chapter(request: Request, req: GenerateRequest):
    """异步生成章节，与 SSE 端点共用同一事件循环，避免 asyncio.run 嵌套。"""
    cfg = load_config()
    set_config(cfg)
    from novel_agent.bible import database as db_mod
    Base.metadata.create_all(bind=db_mod.engine)
    db = SessionLocal()
    repo = BibleRepository(db, project_id=req.project_id)
    runner = ChapterRunner(cfg, repo=repo)
    try:
        result = await runner.run(
            chapter=req.chapter, title=req.title, thread_id=req.thread_id)
        return result
    finally:
        await runner.close()
        db.close()


@router.get("/list")
def list_chapters(project_id: int):
    """列出项目下的所有章节。注意：此路由必须在 /{chapter}/text 之前注册，避免被当作 chapter 参数。

    合并两个来源：
    1. 已写过的章节文件（RecallMemory 扫描 .md 文件）
    2. 章级大纲（outlines 表 level=chapter），让用户能看到章纲并生成正文
    """
    from novel_agent.memory.recall import RecallMemory
    cfg = load_config()
    recall = RecallMemory(cfg, project_id=project_id)
    chapters = recall.list_chapters_with_titles()

    # 补充text_preview（只读文件头部200字，不读完整文件）
    for ch in chapters:
        ch["text_preview"] = recall.read_chapter_preview(ch["chapter"])

    # 合并章级大纲：未写过正文的章纲也显示在列表中
    try:
        set_config(cfg)
        from novel_agent.bible import database as db_mod
        Base.metadata.create_all(bind=db_mod.engine)
        db = SessionLocal()
        try:
            repo = BibleRepository(db, project_id=project_id)
            chapter_outlines = repo.list_outlines(level="chapter")
            existing_chs = {ch["chapter"] for ch in chapters}
            for co in chapter_outlines:
                ch_num = co.order if co.order and co.order > 0 else co.id
                if ch_num not in existing_chs:
                    chapters.append({
                        "chapter": ch_num,
                        "title": co.title or f"第{ch_num}章",
                        "text_preview": (co.summary or "")[:200],
                    })
                    existing_chs.add(ch_num)
        finally:
            db.close()
    except Exception as e:
        logger.warning("合并章级大纲失败: %s", e)

    # 按章号排序
    chapters.sort(key=lambda c: c["chapter"])
    return chapters


@router.get("/generate/stream")
@limiter.limit("10/minute")
async def generate_chapter_stream(request: Request, project_id: int, chapter: int, title: str,
                                  thread_id: str | None = None):
    """SSE 流式生成章节，实时推送节点状态。

    human_review 节点会 interrupt 暂停，推送 review_pending 事件，等待 /resume/stream 恢复。
    """
    import json
    import uuid
    from sse_starlette.sse import EventSourceResponse

    # 初始化阶段：config 加载、db session、ChapterRunner 初始化可能抛异常，
    # 包进 try-except 记录 init_error，通过 SSE error 事件返回，避免直接 500
    init_error: str | None = None
    cfg = None
    db = None
    repo = None
    runner = None
    try:
        cfg = load_config()
        set_config(cfg)
        from novel_agent.bible import database as db_mod
        Base.metadata.create_all(bind=db_mod.engine)
        db = SessionLocal()
        repo = BibleRepository(db, project_id=project_id)
        runner = ChapterRunner(cfg, repo=repo)
    except Exception as e:
        init_error = f"{type(e).__name__}: {e}"
        if db is not None:
            try:
                db.close()
            except Exception as e:
                logger.warning("db.close失败: %s", e)

    tid = thread_id or str(uuid.uuid4())

    async def event_generator():
        # 初始化失败：直接通过 SSE error 事件返回，前端能看到具体原因
        if init_error:
            yield {"event": "error", "data": json.dumps({"error": init_error}, ensure_ascii=False)}
            return
        await runner._ensure_checkpointer()
        initial = {"project_id": project_id, "chapter": chapter, "title": title,
                   "context": "", "draft": "", "status": "pending", "error": "",
                   "word_count": 0, "draft_version": 0, "review_iterations": 0,
                   "_thread_id": tid}
        final_status = "completed"
        queue: asyncio.Queue = asyncio.Queue(maxsize=100)
        last_node = [None]

        async def producer():
            nonlocal final_status
            from novel_agent.orchestrator.runner import _cancel_tokens, clear_cancel_token
            _cancel_tokens[tid] = asyncio.Event()
            try:
                async for mode, chunk in runner.graph.astream(
                    initial,
                    config={"configurable": {"thread_id": tid}},
                    stream_mode=["updates"],
                ):
                    if await request.is_disconnected():
                        logger.warning("generate_chapter_stream: 客户端断开，取消LLM调用 thread_id=%s", tid)
                        _cancel_tokens[tid].set()
                        final_status = "failed"
                        break
                    if mode == "updates":
                        for node_name, node_output in chunk.items():
                            last_node[0] = node_name
                            node_status = None
                            node_payload: dict = {"node": node_name, "status": None, "thread_id": tid}
                            if isinstance(node_output, dict):
                                node_status = node_output.get("status")
                                node_payload["status"] = node_status
                                if node_status in ("failed", "end_failed"):
                                    final_status = "failed"
                                # analyze_style 节点：推送人类样本分析结果给前端展示
                                if node_name == "analyze_style":
                                    style_analysis = node_output.get("style_analysis", "")
                                    benchmark_text = node_output.get("style_benchmark_text", "")
                                    if style_analysis:
                                        node_payload["style_analysis"] = style_analysis
                                    if benchmark_text:
                                        node_payload["style_benchmark"] = benchmark_text[:800]
                            await queue.put({"event": "node", "data": json.dumps(
                                node_payload, ensure_ascii=False, default=str)})

                # astream 正常结束后，检查是否被 interrupt 暂停
                # 注意：不能用 last_node == "human_review" 判断，因为 interrupt
                # 不会推送节点更新，last_node 仍是上一个节点（如 audit）
                if final_status != "failed":
                    logger.debug("SSE: astream 结束，检查 interrupt状态 final_status=%s last_node=%s", final_status, last_node[0])
                    try:
                        state = await runner.graph.aget_state(
                            config={"configurable": {"thread_id": tid}})
                        logger.debug("SSE: aget_state完成 state.next=%s tasks=%d", state.next if state else None, len(state.tasks) if state else 0)
                    except Exception as ase:
                        logger.debug("SSE: aget_state异常: %s", ase)
                        state = None
                    if state and state.next:
                        # 被 interrupt 暂停，提取 payload
                        interrupt_data = _extract_interrupt_value(state)
                        logger.debug("SSE: 推送review_pending事件 thread_id=%s", tid)
                        await queue.put({"event": "review_pending", "data": json.dumps({
                            "thread_id": tid, **interrupt_data,
                        }, ensure_ascii=False, default=str)})
                        return  # 不推送 done，等 /resume/stream

                if final_status == "failed":
                    await queue.put({"event": "error", "data": json.dumps({"status": "failed", "thread_id": tid})})
                else:
                    await queue.put({"event": "done", "data": json.dumps({"status": final_status, "thread_id": tid})})
            except Exception as e:
                await queue.put({"event": "error", "data": json.dumps({"error": str(e)})})
            finally:
                clear_cancel_token(tid)

        producer_task = asyncio.create_task(producer())
        try:
            while True:
                try:
                    event = await asyncio.wait_for(queue.get(), timeout=15.0)
                    yield event
                    if event["event"] in ("done", "error", "review_pending"):
                        break
                except asyncio.TimeoutError:
                    yield {"event": "heartbeat", "data": "{}"}
        finally:
            if not producer_task.done():
                producer_task.cancel()
                try:
                    await producer_task
                except asyncio.CancelledError:
                    pass
            await runner.close()
            db.close()

    return EventSourceResponse(event_generator(), ping=15)


@router.get("/resume/stream")
@limiter.limit("10/minute")
async def resume_chapter_stream(request: Request, project_id: int, thread_id: str,
                                decision: str = "approve", feedback: str = ""):
    """恢复被 interrupt 暂停的章节生成。

    decision: "approve" → style_refine；"reject" → rewrite
    feedback: 用户人审时输入的文字意见。reject 时注入 rewrite prompt；
              approve 时也会写入 state 作为备注，但不影响润色逻辑。
    """
    import json
    from sse_starlette.sse import EventSourceResponse
    from langgraph.types import Command

    # 初始化阶段：config 加载、db session、ChapterRunner 初始化可能抛异常，
    # 包进 try-except 记录 init_error，通过 SSE error 事件返回，避免直接 500
    init_error: str | None = None
    cfg = None
    db = None
    repo = None
    runner = None
    try:
        cfg = load_config()
        set_config(cfg)
        from novel_agent.bible import database as db_mod
        Base.metadata.create_all(bind=db_mod.engine)
        db = SessionLocal()
        repo = BibleRepository(db, project_id=project_id)
        runner = ChapterRunner(cfg, repo=repo)
    except Exception as e:
        init_error = f"{type(e).__name__}: {e}"
        if db is not None:
            try:
                db.close()
            except Exception as e:
                logger.warning("db.close失败: %s", e)

    # 构造 resume 值：有意见时传 dict，无意见时传字符串（保持兼容）
    feedback = (feedback or "").strip()
    resume_value: dict | str
    if feedback:
        resume_value = {"decision": decision, "feedback": feedback}
    else:
        resume_value = decision

    async def event_generator():
        await runner._ensure_checkpointer()
        final_status = "completed"
        queue: asyncio.Queue = asyncio.Queue(maxsize=100)

        async def producer():
            nonlocal final_status
            from novel_agent.orchestrator.runner import _cancel_tokens, clear_cancel_token
            logger.debug("resume producer: 开始 astream thread_id=%s decision=%s feedback_len=%d",
                         thread_id, decision, len(feedback))
            # 注册取消令牌：恢复阶段也允许用户取消
            _cancel_tokens[thread_id] = asyncio.Event()
            try:
                async for mode, chunk in runner.graph.astream(
                    Command(resume=resume_value),  # Command 作为 input 恢复 interrupt
                    config={"configurable": {"thread_id": thread_id}},
                    stream_mode=["updates"],
                ):
                    if await request.is_disconnected():
                        logger.debug("resume_chapter_stream: 客户端断开，取消LLM调用 thread_id=%s", thread_id)
                        _cancel_tokens[thread_id].set()
                        final_status = "failed"
                        break
                    logger.debug("resume producer: 收到chunk mode=%s chunk_keys=%s", mode, list(chunk.keys()) if isinstance(chunk, dict) else type(chunk).__name__)
                    if mode == "updates":
                        for node_name, node_output in chunk.items():
                            node_status = None
                            if isinstance(node_output, dict):
                                node_status = node_output.get("status")
                                if node_status in ("failed", "end_failed"):
                                    final_status = "failed"
                            await queue.put({"event": "node", "data": json.dumps({
                                "node": node_name, "status": node_status,
                            }, ensure_ascii=False, default=str)})

                if final_status == "failed":
                    await queue.put({"event": "error", "data": json.dumps({"status": "failed"})})
                    return
                # astream 结束后检查是否被 interrupt 暂停（重写后可能再次走到人审）
                try:
                    state = await runner.graph.aget_state(
                        config={"configurable": {"thread_id": thread_id}})
                except Exception:
                    state = None
                if state and state.next:
                    interrupt_data = _extract_interrupt_value(state)
                    await queue.put({"event": "review_pending", "data": json.dumps({
                        "thread_id": thread_id, **interrupt_data,
                    }, ensure_ascii=False, default=str)})
                    return
                await queue.put({"event": "done", "data": json.dumps({"status": final_status})})
            except Exception as e:
                await queue.put({"event": "error", "data": json.dumps({"error": str(e)})})
            finally:
                clear_cancel_token(thread_id)

        producer_task = asyncio.create_task(producer())
        try:
            while True:
                try:
                    event = await asyncio.wait_for(queue.get(), timeout=15.0)
                    yield event
                    if event["event"] in ("done", "error", "review_pending"):
                        break
                except asyncio.TimeoutError:
                    yield {"event": "heartbeat", "data": "{}"}
        finally:
            if not producer_task.done():
                producer_task.cancel()
                try:
                    await producer_task
                except asyncio.CancelledError:
                    pass
            await runner.close()
            db.close()

    return EventSourceResponse(event_generator(), ping=15)


@router.post("/cancel")
async def cancel_chapter(project_id: int, thread_id: str):
    """取消章节生成——设置取消令牌，每个节点开始前检查。"""
    from novel_agent.orchestrator.runner import request_cancel
    success = request_cancel(thread_id)
    return {"cancelled": success, "thread_id": thread_id}


@router.get("/{chapter}/text")
def get_chapter_text(chapter: int, project_id: int):
    """获取章节正文（去除 markdown 标题行，只返回正文）。

    章节未写过正文时返回空文本而非 404，让前端能打开编辑器开始生成。
    """
    from novel_agent.memory.recall import RecallMemory
    cfg = load_config()
    recall = RecallMemory(cfg, project_id=project_id)
    raw = recall.read_chapter_text(chapter)
    if not raw:
        # 没写过正文，返回空文本（不报 404，让前端能打开编辑器）
        # 尝试从章纲获取标题
        title = f"第{chapter}章"
        try:
            set_config(cfg)
            from novel_agent.bible import database as db_mod
            Base.metadata.create_all(bind=db_mod.engine)
            db = SessionLocal()
            try:
                repo = BibleRepository(db, project_id=project_id)
                outline = next((o for o in repo.list_outlines(level="chapter") if o.order == chapter), None)
                if outline and outline.title:
                    title = outline.title
            finally:
                db.close()
        except Exception as e:
            logger.warning("获取章纲标题失败: %s", e)
        return {"chapter": chapter, "text": "", "title": title}
    # 只跳过 # 开头的 markdown 标题行；纯正文不跳
    lines = raw.splitlines()
    if lines and lines[0].lstrip().startswith("#"):
        text = "\n".join(lines[1:]).lstrip("\n")
    else:
        text = raw
    return {"chapter": chapter, "text": text}


class ChapterTextEdit(BaseModel):
    title: str = ""
    content: str = ""


def _cleanup_chapter_memory(cfg, project_id: int, chapter: int, db) -> None:
    """P1#9：删除章节后同步清理记忆残留（向量切片/状态快照/TruthEvent 事件流）。

    全部 try/except 包裹：清理失败仅记日志，不阻塞主流程。
    """
    # 向量切片
    try:
        from novel_agent.memory.archival import ArchivalMemory
        ArchivalMemory(cfg, project_id=project_id).delete_chapter(chapter)
    except Exception as e:
        logger.warning("删除章节%d向量切片失败: %s", chapter, e)
    # 状态快照 + TruthEvent 事件流
    try:
        from novel_agent.bible.models import StateSnapshot, TruthEvent
        db.query(StateSnapshot).filter(
            StateSnapshot.project_id == project_id,
            StateSnapshot.chapter == chapter,
        ).delete(synchronize_session=False)
        db.query(TruthEvent).filter(
            TruthEvent.project_id == project_id,
            TruthEvent.chapter == chapter,
        ).delete(synchronize_session=False)
        db.commit()
    except Exception as e:
        logger.warning("删除章节%d记忆残留(快照/事件)失败: %s", chapter, e)


@router.put("/{chapter}/text")
def save_chapter_text(chapter: int, project_id: int, data: ChapterTextEdit):
    """编辑后保存章节正文到文件。"""
    from novel_agent.memory.recall import RecallMemory
    cfg = load_config()
    recall = RecallMemory(cfg, project_id=project_id)
    path = recall.save_chapter_text(chapter=chapter, title=data.title,
                                    content=data.content)
    # P1#9：保存成功后重建该章向量切片（记忆写入闭环），失败不阻塞主流程
    try:
        from novel_agent.memory.archival import ArchivalMemory
        ArchivalMemory(cfg, project_id=project_id).index_chapter(
            chapter=chapter, title=data.title, content=data.content)
    except Exception as e:
        logger.warning("保存章节%d后重建向量切片失败: %s", chapter, e)
    # 断链①③：出场记录 + 叙事线轻扫已统一收口到 recall.save_chapter_text（写章即更新），此处无需重复
    return {"chapter": chapter, "saved": True, "path": str(path)}


@router.get("/export/txt")
def export_txt(project_id: int):
    """导出全部章节为单个 TXT。必须在 /{chapter} 路由之前注册，避免被遮蔽。"""
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


@router.delete("/{chapter}")
def delete_chapter(chapter: int, project_id: int):
    """删除章节正文文件 + 圣经摘要 + 同步清理记忆残留。"""
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
        # 级联清理该章的实体出场记录，避免删除后残留幽灵出场
        repo.delete_entity_appearances_for_chapter(chapter)
        # P1#9：同步清理该章记忆残留（快照/事件流），失败仅记日志
        _cleanup_chapter_memory(cfg, project_id, chapter, db)
    finally:
        db.close()
    return {"deleted": True, "files": deleted_files, "summary_removed": db_deleted}


@router.post("/batch-delete")
def batch_delete_chapters(project_id: int, chapters: list[int]):
    """批量删除章节正文文件 + 圣经摘要。使用单一事务，全部成功才 commit。"""
    from novel_agent.memory.recall import RecallMemory
    cfg = load_config()
    recall = RecallMemory(cfg, project_id=project_id)
    deleted_chapters = []
    failed = []
    set_config(cfg)
    from novel_agent.bible import database as db_mod
    Base.metadata.create_all(bind=db_mod.engine)
    db = SessionLocal()
    try:
        repo = BibleRepository(db, project_id=project_id)
        for chapter in chapters:
            try:
                pattern = f"第{chapter:03d}章_*.md"
                for p in recall.chapters_dir.glob(pattern):
                    p.unlink()
                repo.delete_chapter_summary(chapter)
                # 级联清理该章的实体出场记录
                repo.delete_entity_appearances_for_chapter(chapter)
                # P1#9：同步清理该章记忆残留（快照/事件流），失败仅记日志
                _cleanup_chapter_memory(cfg, project_id, chapter, db)
                deleted_chapters.append(chapter)
            except Exception:
                failed.append(chapter)
        if failed:
            db.rollback()
        else:
            db.commit()
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()
    return {"deleted": deleted_chapters, "failed": failed, "deleted_count": len(deleted_chapters)}
