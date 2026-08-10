"""Chat API：SSE 流式对话。"""
from __future__ import annotations

import asyncio
import json
import logging

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel
from sse_starlette.sse import EventSourceResponse

from novel_agent.api.app import limiter
from novel_agent.bible.database import SessionLocal, set_config
from novel_agent.bible.models import Base, ChatMessage
from novel_agent.bible.repository import BibleRepository
from novel_agent.chat.agent import ChatAgent
from novel_agent.chat.context import ContextBuilder
from novel_agent.chat.executor import ActionExecutor
from novel_agent.chat.repository import ChatRepository
from novel_agent.chat.session_store import get_session_store
from novel_agent.config import load_config

logger = logging.getLogger(__name__)
router = APIRouter()


class ChatMessageRequest(BaseModel):
    project_id: int
    message: str
    session_type: str = "object"      # "object" | "global"
    object_type: str = ""             # chapter|outline|character|monster|world|faction|relationship
    object_id: str = ""
    title: str = ""


class ChatSessionResponse(BaseModel):
    id: str
    project_id: int
    session_type: str
    object_type: str
    object_id: str
    title: str
    created_at: str | None
    updated_at: str | None


@router.post("/messages")
@limiter.limit("30/minute")
async def send_message(request: Request, req: ChatMessageRequest):
    cfg = load_config()
    set_config(cfg)
    from novel_agent.bible import database as db_mod
    Base.metadata.create_all(bind=db_mod.engine)
    db = SessionLocal()
    try:
        repo = BibleRepository(db, project_id=req.project_id)
        project = repo.get_project()
        if not project:
            raise HTTPException(404, "项目不存在")

        chat_repo = ChatRepository(db, project_id=req.project_id)
        session = chat_repo.get_or_create_session(
            session_type=req.session_type,
            object_type=req.object_type,
            object_id=req.object_id,
            title=req.title,
        )
        history = chat_repo.list_messages(session.id, limit=20)
        context = ContextBuilder(repo, cfg).build(
            req.session_type, req.object_type, req.object_id
        )
        executor = ActionExecutor(repo, cfg)
        agent = ChatAgent(repo, cfg, executor=executor)
        # 设置会话上下文（coding_tools 依赖 workspace_path 做文件读写安全沙箱）
        from novel_agent.chat.session_context import SessionContextManager
        SessionContextManager().set_context(
            session_id=f"chat-{req.project_id}-{session.id}",
            agent_type="orchestrator",
            workspace_path=str(cfg.project_dir(req.project_id)),
        )
        # 会话状态持久化到 SQLite（替代内存 SessionManager）：跨请求复用，支持 steer + 断线重连
        store = get_session_store()

        # Bug 7: try_acquire 原子 check-and-set，防并发竞态
        # Bug 1/2: busy 时转 steer，关 db，只存一次 user 消息
        if not store.try_acquire(session.id, req.project_id):
            store.steer(session.id, req.message, req.project_id)
            chat_repo.add_message(session.id, "user", req.message)
            db.close()  # Bug 2: busy 分支必须关 db，否则泄漏
            return {"steered": True, "message": "已注入当前对话"}

        # 获取 busy 成功，启动 turn
        # Bug 1/4: 先 list_messages 再 add_message，history 不含本条，避免重复进 LLM
        # busy 已置 True，后续 add_message/clear_cancel 异常必须释放 busy 并关 db，否则会话永久卡死
        try:
            chat_repo.add_message(session.id, "user", req.message)
            store.clear_cancel(session.id)
        except Exception:
            store.set_busy(session.id, False, req.project_id)
            db.close()
            raise

        async def event_generator():
            full_text = ""
            actions: list[dict] = []
            completed = False  # Bug 3: 防断开时双重存 + 误发 done
            try:
                async for chunk in agent.stream_reply(
                    req.message, history, context,
                    cancel_event=store.get_cancel_event(session.id),
                    steer_callback=lambda: store.drain_steer(session.id),
                ):
                    if await request.is_disconnected():
                        logger.info("send_message: 客户端已断开，停止回复")
                        store.interrupt(session.id)
                        if full_text:
                            chat_repo.add_message(session.id, "assistant", full_text + "\n（用户中断）", actions=actions)
                        yield {"event": "error", "data": json.dumps({"error": "用户取消或连接断开"}, ensure_ascii=False)}
                        break
                    if chunk["type"] == "reasoning":
                        yield {"event": "reasoning", "data": json.dumps({"content": chunk["content"]}, ensure_ascii=False)}
                    elif chunk["type"] == "text":
                        full_text += chunk["content"]
                        yield {"event": "chunk", "data": json.dumps({"content": chunk["content"]}, ensure_ascii=False)}
                    elif chunk["type"] == "action":
                        action = chunk["action"]
                        actions.append(action)
                        yield {"event": "action", "data": json.dumps(action, ensure_ascii=False, default=str)}
                else:
                    # Bug 3: for 正常结束（没 break）才存 assistant + 发 done
                    chat_repo.add_message(session.id, "assistant", full_text, actions=actions)
                    completed = True
                    yield {"event": "done", "data": "{}"}
            except asyncio.CancelledError:
                store.interrupt(session.id)
                if full_text and not completed:
                    chat_repo.add_message(session.id, "assistant", full_text + "\n（用户中断）", actions=actions)
                raise
            finally:
                store.set_busy(session.id, False, req.project_id)  # Bug 6: set_busy(False) 同时清 stale steer
                await agent.close()
                db.close()

        return EventSourceResponse(event_generator())
    except HTTPException:
        db.close()
        raise


@router.get("/sessions", response_model=list[ChatSessionResponse])
def list_sessions(project_id: int):
    cfg = load_config()
    set_config(cfg)
    from novel_agent.bible import database as db_mod
    Base.metadata.create_all(bind=db_mod.engine)
    db = SessionLocal()
    try:
        repo = ChatRepository(db, project_id=project_id)
        sessions = repo.list_sessions()
        return [
            ChatSessionResponse(
                id=s.id,
                project_id=s.project_id,
                session_type=s.session_type,
                object_type=s.object_type,
                object_id=s.object_id,
                title=s.title,
                created_at=s.created_at.isoformat() if s.created_at else None,
                updated_at=s.updated_at.isoformat() if s.updated_at else None,
            )
            for s in sessions
        ]
    finally:
        db.close()


@router.get("/sessions/{session_id}/messages")
def get_messages(session_id: str, project_id: int):
    cfg = load_config()
    set_config(cfg)
    from novel_agent.bible import database as db_mod
    Base.metadata.create_all(bind=db_mod.engine)
    db = SessionLocal()
    try:
        chat_repo = ChatRepository(db, project_id=project_id)
        session = chat_repo.get_session(session_id)
        if not session:
            raise HTTPException(404, "会话不存在")
        msgs = chat_repo.list_messages(session_id)
        return [
            {
                "id": m.id,
                "session_id": m.session_id,
                "role": m.role,
                "content": m.content,
                "actions": m.actions,
                "created_at": m.created_at.isoformat() if m.created_at else None,
            }
            for m in msgs
        ]
    finally:
        db.close()


@router.get("/sessions/{session_id}/status")
def get_session_status(session_id: str):
    """查询会话运行状态（供前端断线重连判断 busy/steer）。

    返回 {session_id, busy, steer_pending, created_at, updated_at}。
    无运行记录时返回 idle 默认（busy=False），便于前端直接拉取历史消息。
    """
    cfg = load_config()
    set_config(cfg)
    store = get_session_store()
    info = store.get_chat_status(session_id)
    if info is None:
        return {"session_id": session_id, "busy": False, "steer_pending": 0}
    return info


@router.delete("/sessions/{session_id}")
def delete_session(session_id: str, project_id: int):
    cfg = load_config()
    set_config(cfg)
    from novel_agent.bible import database as db_mod
    Base.metadata.create_all(bind=db_mod.engine)
    db = SessionLocal()
    try:
        chat_repo = ChatRepository(db, project_id=project_id)
        if not chat_repo.delete_session(session_id):
            raise HTTPException(404, "会话不存在")
        return {"deleted": True}
    finally:
        db.close()


class InteractiveChatSaveRequest(BaseModel):
    project_id: int
    messages: list[dict]


@router.get("/interactive/messages")
def get_interactive_messages(project_id: int):
    """获取交互式创作页面的聊天记录（session_type='interactive'，与 AI 对话隔离）。"""
    cfg = load_config()
    set_config(cfg)
    from novel_agent.bible import database as db_mod
    Base.metadata.create_all(bind=db_mod.engine)
    db = SessionLocal()
    try:
        chat_repo = ChatRepository(db, project_id=project_id)
        session = chat_repo.get_or_create_session(
            session_type="interactive",
            object_type="",
            object_id="",
            title="交互式创作",
        )
        msgs = chat_repo.list_messages(session.id, limit=200)
        return [
            {
                "id": m.id,
                "session_id": m.session_id,
                "role": m.role,
                "content": m.content,
                "actions": m.actions,
                "created_at": m.created_at.isoformat() if m.created_at else None,
            }
            for m in msgs
        ]
    finally:
        db.close()


@router.post("/interactive/messages")
def save_interactive_messages(req: InteractiveChatSaveRequest):
    """保存/覆盖交互式创作页面的聊天记录。"""
    cfg = load_config()
    set_config(cfg)
    from novel_agent.bible import database as db_mod
    Base.metadata.create_all(bind=db_mod.engine)
    db = SessionLocal()
    try:
        chat_repo = ChatRepository(db, project_id=req.project_id)
        session = chat_repo.get_or_create_session(
            session_type="interactive",
            object_type="",
            object_id="",
            title="交互式创作",
        )
        # 删除旧消息，写入新消息（避免重复和编辑后的状态不一致）
        db.query(ChatMessage).filter(ChatMessage.session_id == session.id).delete()
        for m in req.messages:
            chat_repo.add_message(
                session.id,
                role=m.get("role", "assistant"),
                content=json.dumps(m, ensure_ascii=False),
                actions=[],
            )
        return {"saved": True, "count": len(req.messages)}
    finally:
        db.close()
