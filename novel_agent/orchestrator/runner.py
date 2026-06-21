"""Runner：组装依赖 + 构建 graph + SqliteSaver 断点续跑。

Runner 是编排层的运行入口，把 M1 的各模块（repo/llm/recall/applier/archival）
注入 graph 节点，并用 SqliteSaver 做 checkpoint 实现断点续跑。
"""
from __future__ import annotations

import asyncio
import sqlite3
import uuid
from typing import Any

from langgraph.checkpoint.sqlite import SqliteSaver

from novel_agent.audit.auditor import Auditor
from novel_agent.bible.repository import BibleRepository
from novel_agent.config import Config
from novel_agent.llm.client import LLMClient
from novel_agent.memory.archival import ArchivalMemory
from novel_agent.memory.recall import RecallMemory
from novel_agent.orchestrator.graph import build_graph
from novel_agent.protocol.applier import DeltaApplier


class ChapterRunner:
    """单章生成运行器。"""

    def __init__(self, config: Config, repo: BibleRepository,
                 llm_client: LLMClient | None = None,
                 auditor: Auditor | None = None):
        self.config = config
        self.repo = repo
        self.llm_client = llm_client or LLMClient(config.llm)
        self.recall = RecallMemory(config, project_id=repo.project_id)
        self.archival = ArchivalMemory(config, project_id=repo.project_id)
        self.applier = DeltaApplier(repo, archival=self.archival)
        # Auditor 用独立 client（写审分离；auditor_llm 为 None 时回退到 llm）
        self._auditor_client = LLMClient(config.auditor_llm or config.llm)
        self.auditor = auditor or Auditor(self._auditor_client)
        # checkpoint 存储：每项目独立 db + WAL，崩溃可恢复
        saver_path = config.project_dir(self.repo.project_id) / "checkpoints.db"
        saver_path.parent.mkdir(parents=True, exist_ok=True)
        self._saver_conn = sqlite3.connect(
            str(saver_path),
            check_same_thread=False,
        )
        # 启用 WAL 模式提升并发读写性能，busy_timeout 防止锁等待失败
        self._saver_conn.execute("PRAGMA journal_mode=WAL")
        self._saver_conn.execute("PRAGMA busy_timeout=5000")
        self.checkpointer = SqliteSaver(self._saver_conn)
        self.checkpointer.setup()
        # build_graph 已 compile（无 checkpointer）；用 with_config 绑定
        self.graph = build_graph({
            "repo": self.repo,
            "llm_client": self.llm_client,
            "recall": self.recall,
            "applier": self.applier,
            "archival": self.archival,
            "auditor": self.auditor,
        }).with_config({"checkpointer": self.checkpointer})

    async def run(self, chapter: int, title: str,
                  thread_id: str | None = None) -> dict:
        """运行单章生成流水线。

        Args:
            chapter: 章节号
            title: 章节标题
            thread_id: 断点续跑的线程 id；同 id 重跑会从 checkpoint 恢复
        """
        tid = thread_id or str(uuid.uuid4())
        initial_state = {
            "project_id": self.repo.project_id,
            "chapter": chapter,
            "title": title,
            "context": "",
            "draft": "",
            "status": "pending",
            "error": "",
            "word_count": 0,
        }
        try:
            result = await asyncio.wait_for(
                self.graph.ainvoke(
                    initial_state, config={"configurable": {"thread_id": tid}},
                ),
                timeout=600,
            )
            return result
        except asyncio.TimeoutError:
            return {"status": "failed", "error": "生成超时（600秒）"}

    async def close(self):
        await self.llm_client.close()
        await self._auditor_client.close()
        self._saver_conn.close()
