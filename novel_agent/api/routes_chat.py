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
from novel_agent.bible.models import Base
from novel_agent.bible.repository import BibleRepository
from novel_agent.chat.agent import ChatAgent
from novel_agent.chat.context import ContextBuilder
from novel_agent.chat.executor import ActionExecutor
from novel_agent.chat.repository import ChatRepository
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
        chat_repo.add_message(session.id, "user", req.message)
        history = chat_repo.list_messages(session.id, limit=20)
        context = ContextBuilder(repo, cfg).build(
            req.session_type, req.object_type, req.object_id
        )
        agent = ChatAgent(repo, cfg)
        executor = ActionExecutor(repo, cfg)

        async def event_generator():
            full_text = ""
            actions: list[dict] = []
            try:
                async for chunk in agent.stream_reply(req.message, history, context):
                    if chunk["type"] == "text":
                        full_text += chunk["content"]
                        yield {"event": "chunk", "data": json.dumps({"content": chunk["content"]}, ensure_ascii=False)}
                    elif chunk["type"] == "action":
                        action = chunk["action"]
                        actions.append(action)
                        yield {"event": "action", "data": json.dumps({**action, "status": "dispatched"}, ensure_ascii=False)}
                        try:
                            result = await executor.execute(action)
                            yield {"event": "action", "data": json.dumps({**action, "status": "done", "result": result}, ensure_ascii=False, default=str)}
                        except Exception as e:
                            logger.warning("Chat action 执行失败: %s", e)
                            yield {"event": "action", "data": json.dumps({**action, "status": "failed", "error": str(e)}, ensure_ascii=False)}
                chat_repo.add_message(session.id, "assistant", full_text, actions=actions)
                yield {"event": "done", "data": "{}"}
            except asyncio.CancelledError:
                if full_text:
                    chat_repo.add_message(session.id, "assistant", full_text + "\n（用户中断）", actions=actions)
                raise

        return EventSourceResponse(event_generator())
    finally:
        db.close()


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
