"""VolumeRunner：卷级规划运行器。

跑卷级 graph，遇人审① interrupt 挂起；
用户审核后调 resume(decision) 恢复，决策写入圣经。

用 AsyncSqliteSaver（ainvoke + interrupt/resume 需要 async checkpointer）。
"""
from __future__ import annotations

import uuid

from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver
from langgraph.types import Command

from novel_agent.bible.repository import BibleRepository
from novel_agent.config import Config
from novel_agent.llm.client import LLMClient
from novel_agent.memory.archival import ArchivalMemory
from novel_agent.planning.agents import Planner, Architect, Outliner
from novel_agent.planning.graph import build_volume_graph
from novel_agent.protocol.applier import DeltaApplier


class VolumeRunner:
    def __init__(self, config: Config, repo: BibleRepository,
                 llm_client: LLMClient | None = None):
        self.config = config
        self.repo = repo
        client = llm_client or LLMClient(config.llm)
        self.planner = Planner(client)
        self.architect = Architect(client)
        self.outliner = Outliner(client)
        self.archival = ArchivalMemory(config)
        self.applier = DeltaApplier(repo, archival=self.archival)
        config.project_data_dir.mkdir(parents=True, exist_ok=True)
        # AsyncSqliteSaver 需要 aiosqlite 连接
        import aiosqlite
        self._db_path = str(config.project_data_dir / "volume_checkpoints.db")
        self._aio_conn = None
        self.checkpointer = None
        self.graph = None

    async def _ensure_async(self):
        """惰性初始化 async checkpointer（aiosqlite 连接需在事件循环内创建）。"""
        if self.checkpointer is None:
            import aiosqlite
            self._aio_conn = await aiosqlite.connect(self._db_path)
            self.checkpointer = AsyncSqliteSaver(self._aio_conn)
            await self.checkpointer.setup()
            self.graph = build_volume_graph({
                "planner": self.planner, "architect": self.architect,
                "outliner": self.outliner, "repo": self.repo, "applier": self.applier,
            }, checkpointer=self.checkpointer)

    async def run(self, volume: str, chapter_count: int = 30,
                  thread_id: str | None = None) -> dict:
        await self._ensure_async()
        tid = thread_id or str(uuid.uuid4())
        state = {"project_id": self.repo.project_id, "volume": volume,
                 "chapter_count": chapter_count, "status": "pending"}
        return await self.graph.ainvoke(
            state, config={"configurable": {"thread_id": tid}})

    async def resume(self, decision: dict, thread_id: str) -> dict:
        """人审①后恢复：传 approved/edits。"""
        await self._ensure_async()
        return await self.graph.ainvoke(
            Command(resume=decision),
            config={"configurable": {"thread_id": thread_id}})

    async def aclose(self):
        """关闭 async 资源（aiosqlite 连接）。必须在事件循环内调用。"""
        if self._aio_conn is not None:
            await self._aio_conn.close()
            self._aio_conn = None

    def close(self):
        """同步关闭（async 连接需在循环内关，此处仅占位，建议用 aclose）。"""
        pass
