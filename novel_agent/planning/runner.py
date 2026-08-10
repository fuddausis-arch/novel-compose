"""VolumeRunner：卷级规划运行器。

跑卷级 graph，遇人审① interrupt 挂起；
用户审核后调 resume(decision) 恢复，决策写入圣经。

用 AsyncSqliteSaver（ainvoke + interrupt/resume 需要 async checkpointer）。
"""
from __future__ import annotations

import uuid
import logging

from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver
from langgraph.types import Command

from novel_agent.bible.repository import BibleRepository
from novel_agent.config import Config
from novel_agent.llm.client import LLMClient
from novel_agent.memory.archival import ArchivalMemory
from novel_agent.planning.agents import Planner, Architect
from novel_agent.planning.graph import build_volume_graph
from novel_agent.protocol.applier import DeltaApplier
from novel_agent.state_common import PlanningStatus

logger = logging.getLogger(__name__)


class VolumeRunner:
    def __init__(self, config: Config, repo: BibleRepository,
                 llm_client: LLMClient | None = None):
        self.config = config
        self.repo = repo
        # 规划 pipeline 仅含 Planner（总编）+ Architect（设定师），章纲交由大纲页单独生成
        self._clients: list[LLMClient] = []
        if llm_client:
            # 外部传入单一 client 时，两个 agent 共用
            self.planner = Planner(llm_client)
            self.architect = Architect(llm_client)
        else:
            c_planner = LLMClient(config.get_agent_llm("planner"))
            c_architect = LLMClient(config.get_agent_llm("architect"))
            self._clients = [c_planner, c_architect]
            self.planner = Planner(c_planner)
            self.architect = Architect(c_architect)
        try:
            self.archival = ArchivalMemory(config, project_id=repo.project_id)
        except Exception as e:
            logger.warning("ArchivalMemory 初始化失败，降级为 None: %s", e)
            self.archival = None
        self.applier = DeltaApplier(repo, archival=self.archival)
        # 打印各 agent 实际使用的模型，方便确认多 agent 配置生效
        if llm_client:
            logger.info("VolumeRunner 初始化完成(外部注入client) | project=%s | planner/architect 共用=%s",
                        repo.project_id, llm_client.config.model)
        else:
            logger.info("VolumeRunner 初始化完成 | project=%s | 模型分配: planner=%s, architect=%s",
                        repo.project_id,
                        c_planner.config.model, c_architect.config.model)
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
                "repo": self.repo, "applier": self.applier,
            }, checkpointer=self.checkpointer)

    def _validate_project(self):
        """校验项目必填字段，避免 LLM prompt 拼接时出现 NoneType.title 错误。"""
        project = self.repo.get_project()
        if project is None:
            raise ValueError(f"项目 {self.repo.project_id} 不存在")
        if not (project.title or "").strip():
            raise ValueError("项目标题不能为空，请先填写项目基本信息")
        if not (project.genre or "").strip():
            raise ValueError("项目类型不能为空，请先填写项目基本信息")

    async def run(self, volume: str = "卷一", chapter_count: int = 30,
                  thread_id: str | None = None,
                  custom_prompt: str = "",
                  target_volumes: int = 0,
                  golden_finger: str = "",
                  protagonist: str = "",
                  constitution: str = "") -> dict:
        await self._ensure_async()
        self._validate_project()
        tid = thread_id or str(uuid.uuid4())
        state = {"project_id": self.repo.project_id, "volume": volume,
                 "chapter_count": chapter_count,
                 "target_volumes": target_volumes,
                 "custom_prompt": custom_prompt,
                 "golden_finger": golden_finger,
                 "protagonist": protagonist,
                 "constitution": constitution,
                 "status": PlanningStatus.PENDING.value}
        return await self.graph.ainvoke(
            state, config={"configurable": {"thread_id": tid}})

    async def resume(self, decision: dict, thread_id: str) -> dict:
        """人审①后恢复：传 approved/edits。"""
        await self._ensure_async()
        self._validate_project()
        return await self.graph.ainvoke(
            Command(resume=decision),
            config={"configurable": {"thread_id": thread_id}})

    async def aclose(self):
        """关闭 async 资源（aiosqlite 连接 + LLM clients）。必须在事件循环内调用。"""
        for c in self._clients:
            try:
                await c.close()
            except Exception:
                pass
        self._clients.clear()
        if self._aio_conn is not None:
            await self._aio_conn.close()
            self._aio_conn = None

    def close(self):
        """同步关闭（async 连接需在循环内关，此处仅占位，建议用 aclose）。"""
        pass
