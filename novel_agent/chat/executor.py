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
        if action_type == "generate_outlines":
            return await self._generate_outlines(action)
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
            chat_repo.add_chapter_feedback(chapter, feedback)
        # 异步触发章节生成
        from novel_agent.orchestrator.runner import ChapterRunner
        runner = ChapterRunner(self.cfg, repo=self.repo)
        try:
            outline = self.repo.get_outline_by_chapter(chapter)
            title = outline.title if outline else f"第{chapter}章"
            result = await runner.run(chapter=chapter, title=title)
            return {"ok": result.get("status") != "failed", "chapter": chapter, "result": result}
        finally:
            await runner.close()

    def _add_feedback(self, action: dict) -> dict:
        from novel_agent.chat.repository import ChatRepository
        chapter = int(action.get("chapter", 0))
        feedback = action.get("feedback", "")
        chat_repo = ChatRepository(self.repo.db, self.repo.project_id)
        fb = chat_repo.add_chapter_feedback(chapter, feedback)
        return {"ok": True, "feedback_id": fb.id, "chapter": chapter}

    async def _generate_outlines(self, action: dict) -> dict:
        # 调用 planning 路由的底层 runner
        from novel_agent.planning.runner import VolumeRunner
        runner = VolumeRunner(self.cfg, self.repo)
        try:
            result = await runner.run(action.get("volume", ""), chapter_count=int(action.get("chapter_count", 10)))
            return {"ok": True, "result": result}
        finally:
            await runner.close()

    def _query_status(self, _action: dict) -> dict:
        chapters = self.repo.list_chapter_summaries(limit=20)
        fores = self.repo.list_foreshadows()
        return {
            "ok": True,
            "chapter_count": len(chapters),
            "unresolved_foreshadows": len([f for f in fores if f.status not in ("resolved", "abandoned")]),
        }
