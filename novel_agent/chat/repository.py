"""Chat 仓储：会话、消息、章节反馈。"""
from __future__ import annotations

import uuid

from sqlalchemy.orm import Session

from novel_agent.bible.models import ChatSession, ChatMessage, ChapterFeedback


class ChatRepository:
    """项目级聊天数据读写入口。"""

    def __init__(self, db: Session, project_id: int):
        self.db = db
        self.project_id = project_id

    def get_or_create_session(
        self,
        session_type: str,
        object_type: str = "",
        object_id: str = "",
        title: str = "",
    ) -> ChatSession:
        session = (
            self.db.query(ChatSession)
            .filter(
                ChatSession.project_id == self.project_id,
                ChatSession.session_type == session_type,
                ChatSession.object_type == object_type,
                ChatSession.object_id == str(object_id),
            )
            .first()
        )
        if session:
            return session
        session = ChatSession(
            id=str(uuid.uuid4()),
            project_id=self.project_id,
            session_type=session_type,
            object_type=object_type,
            object_id=str(object_id),
            title=title or f"{object_type or 'global'}-{object_id or 'project'}",
        )
        self.db.add(session)
        self.db.commit()
        self.db.refresh(session)
        return session

    def list_sessions(self) -> list[ChatSession]:
        return (
            self.db.query(ChatSession)
            .filter(ChatSession.project_id == self.project_id)
            .order_by(ChatSession.updated_at.desc())
            .all()
        )

    def get_session(self, session_id: str) -> ChatSession | None:
        return (
            self.db.query(ChatSession)
            .filter(
                ChatSession.id == session_id,
                ChatSession.project_id == self.project_id,
            )
            .first()
        )

    def list_messages(self, session_id: str, limit: int = 100) -> list[ChatMessage]:
        # Bug 8: 取最近 limit 条（desc + reverse），而非最旧 limit 条
        msgs = (
            self.db.query(ChatMessage)
            .filter(ChatMessage.session_id == session_id)
            .order_by(ChatMessage.created_at.desc())
            .limit(limit)
            .all()
        )
        msgs.reverse()
        return msgs

    def add_message(
        self,
        session_id: str,
        role: str,
        content: str,
        actions: list[dict] | None = None,
    ) -> ChatMessage:
        msg = ChatMessage(
            id=str(uuid.uuid4()),
            session_id=session_id,
            role=role,
            content=content,
            actions=actions or [],
        )
        self.db.add(msg)
        self.db.commit()
        self.db.refresh(msg)
        return msg

    def delete_session(self, session_id: str) -> bool:
        deleted = (
            self.db.query(ChatSession)
            .filter(
                ChatSession.id == session_id,
                ChatSession.project_id == self.project_id,
            )
            .delete()
        )
        self.db.commit()
        return deleted > 0

    def add_chapter_feedback(self, chapter: int, feedback: str) -> ChapterFeedback:
        fb = ChapterFeedback(
            project_id=self.project_id,
            chapter=chapter,
            feedback=feedback,
        )
        self.db.add(fb)
        self.db.commit()
        self.db.refresh(fb)
        return fb

    def get_pending_feedback(self, chapter: int) -> list[ChapterFeedback]:
        return (
            self.db.query(ChapterFeedback)
            .filter(
                ChapterFeedback.project_id == self.project_id,
                ChapterFeedback.chapter == chapter,
                ChapterFeedback.applied == False,
            )
            .order_by(ChapterFeedback.created_at.asc())
            .all()
        )

    def mark_feedback_applied(self, feedback_ids: list[int]) -> None:
        if not feedback_ids:
            return
        self.db.query(ChapterFeedback).filter(
            ChapterFeedback.project_id == self.project_id,
            ChapterFeedback.id.in_(feedback_ids)
        ).update({"applied": True})
        self.db.commit()
