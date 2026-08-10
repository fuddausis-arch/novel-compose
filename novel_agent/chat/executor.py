"""主 Agent 指令执行器：把结构化动作转成内部 API 调用。"""
from __future__ import annotations

import asyncio
import logging

from novel_agent.bible.repository import BibleRepository
from novel_agent.config import Config

logger = logging.getLogger(__name__)


class ActionExecutor:
    """执行主 Agent 识别出的动作，返回可被 SSE 推送的结果。"""

    def __init__(self, repo: BibleRepository, cfg: Config):
        self.repo = repo
        self.cfg = cfg

    async def execute(self, action: dict) -> dict:
        action_type = action.get("type")
        if action_type == "rewrite_chapter":
            return await self._rewrite_chapter(action)
        if action_type == "add_chapter_feedback":
            return self._add_feedback(action)
        if action_type == "query_status":
            return self._query_status(action)
        logger.warning("未知 chat action: %s", action_type)
        return {"ok": False, "error": f"未知动作 {action_type}"}

    async def _rewrite_chapter(self, action: dict) -> dict:
        from novel_agent.chat.repository import ChatRepository
        chapter = int(action.get("chapter", 0))
        feedback = action.get("feedback", "")
        chat_repo = ChatRepository(self.repo.db, self.repo.project_id)
        if feedback:
            fb = chat_repo.add_chapter_feedback(chapter, feedback)
            chat_repo.mark_feedback_applied([fb.id])
        # 不再启动后台 task，返回 redirect 让前端走 generate/stream 端点（有节点进度）
        outline = self.repo.get_outline_by_chapter(chapter)
        title = outline.title if outline else f"第{chapter}章"
        return {
            "ok": True, "chapter": chapter, "status": "redirect",
            "title": title, "message": f"第{chapter}章重写已启动，正在生成…",
        }

    def _add_feedback(self, action: dict) -> dict:
        from novel_agent.chat.repository import ChatRepository
        chapter = int(action.get("chapter", 0))
        feedback = action.get("feedback", "")
        if not feedback:
            return {"ok": False, "error": "feedback 不能为空"}
        chat_repo = ChatRepository(self.repo.db, self.repo.project_id)
        fb = chat_repo.add_chapter_feedback(chapter, feedback)
        return {"ok": True, "feedback_id": fb.id, "chapter": chapter}

    def _query_status(self, _action: dict) -> dict:
        summaries = self.repo.list_chapter_summaries(limit=10000)
        outlines = self.repo.list_outlines(level="chapter")
        fores = self.repo.list_foreshadows()
        unresolved = [f for f in fores if f.status not in ("resolved", "abandoned")]
        return {
            "ok": True,
            "outline_count": len(outlines),
            "generated_count": len(summaries),
            "unresolved_foreshadows": len(unresolved),
        }
