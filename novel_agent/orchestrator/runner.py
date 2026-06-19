"""Runner：组装依赖 + 构建 graph + SqliteSaver 断点续跑。

Runner 是编排层的运行入口，把 M1 的各模块（repo/llm/recall/applier/archival）
注入 graph 节点，并用 SqliteSaver 做 checkpoint 实现断点续跑。
"""
from __future__ import annotations

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
        # Auditor 用独立 client（写审分离；M3 默认复用同配置，M4 可配不同模型/温度）
        auditor_client = LLMClient(config.llm)
        self.auditor = auditor or Auditor(auditor_client)
        # checkpoint 存储：持久化到文件，崩溃可恢复
        config.project_data_dir.mkdir(parents=True, exist_ok=True)
        self._saver_conn = sqlite3.connect(
            str(config.project_data_dir / "checkpoints.db"),
            check_same_thread=False,
        )
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
        result = await self.graph.ainvoke(
            initial_state, config={"configurable": {"thread_id": tid}},
        )
        return result

    def close(self):
        self._saver_conn.close()
