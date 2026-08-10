"""Runner：组装依赖 + 构建 graph + SqliteSaver 断点续跑。

Runner 是编排层的运行入口，把 M1 的各模块（repo/llm/recall/applier/archival）
注入 graph 节点，并用 SqliteSaver 做 checkpoint 实现断点续跑。
"""
from __future__ import annotations

import asyncio
import uuid
from pathlib import Path
from typing import Any

import logging

from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver

from novel_agent.audit.auditor import Auditor
from novel_agent.bible.repository import BibleRepository
from novel_agent.config import Config
from novel_agent.llm.client import LLMClient
from novel_agent.memory.archival import ArchivalMemory
from novel_agent.memory.recall import RecallMemory
from novel_agent.orchestrator.graph import build_graph
from novel_agent.protocol.applier import DeltaApplier
from novel_agent.state_common import TaskStatus, ChapterGenStatus

logger = logging.getLogger(__name__)

# 全局取消令牌注册表：thread_id → asyncio.Event
# 前端调用 /cancel 时 set()，每个节点开始前检查
_cancel_tokens: dict[str, asyncio.Event] = {}


def request_cancel(thread_id: str):
    """请求取消指定 thread 的生成任务。"""
    event = _cancel_tokens.get(thread_id)
    if event:
        event.set()
        logger.info("取消令牌已设置: thread_id=%s", thread_id)
        return True
    return False


def is_cancelled(thread_id: str) -> bool:
    """检查 thread 是否已被取消。"""
    event = _cancel_tokens.get(thread_id)
    return event is not None and event.is_set()


def clear_cancel_token(thread_id: str):
    """清理已完成的取消令牌。"""
    _cancel_tokens.pop(thread_id, None)


class ChapterRunner:
    """单章生成运行器。"""

    def __init__(self, config: Config, repo: BibleRepository,
                 llm_client: LLMClient | None = None,
                 auditor: Auditor | None = None):
        self.config = config
        self.repo = repo
        # 每个 agent 独立 LLM 配置（质量优先，按角色选模型）
        self._extra_clients: list[LLMClient] = []
        if llm_client:
            self.llm_client = llm_client
        else:
            self.llm_client = LLMClient(config.get_agent_llm("writer"))
        self.recall = RecallMemory(config, project_id=repo.project_id)
        try:
            self.archival = ArchivalMemory(config, project_id=repo.project_id)
        except Exception as e:
            logger.warning("ArchivalMemory 初始化失败，降级为 None: %s", e)
            self.archival = None
        self.applier = DeltaApplier(repo, archival=self.archival)
        # Auditor 用独立 client（写审分离）
        self._auditor_client = LLMClient(config.get_agent_llm("auditor"))
        # Debater 用独立 client（情感智商强的模型更适合辩论）
        self._debater_client = LLMClient(config.get_agent_llm("debater"))
        self._extra_clients.append(self._debater_client)
        self.auditor = auditor or Auditor(
            self._auditor_client, writer_client=self.llm_client,
            debater_client=self._debater_client,
        )
        # Polisher / Summarizer 独立 client（若外部注入了 llm_client，测试场景下复用）
        if llm_client:
            self._polisher_client = llm_client
            self._summarizer_client = llm_client
        else:
            self._polisher_client = LLMClient(config.get_agent_llm("polisher"))
            self._summarizer_client = LLMClient(config.get_agent_llm("summarizer"))
            self._extra_clients.extend([self._polisher_client, self._summarizer_client])
        # checkpoint 存储：每项目独立 db，惰性初始化（aiosqlite 连接需在事件循环内创建）
        self._saver_path = str(config.project_dir(self.repo.project_id) / "checkpoints.db")
        Path(self._saver_path).parent.mkdir(parents=True, exist_ok=True)
        self._aio_conn = None
        self.checkpointer = None
        self.graph = None

    async def _ensure_checkpointer(self):
        """惰性初始化 AsyncSqliteSaver + 构建 graph（aiosqlite 连接需在事件循环内创建）。"""
        if self.checkpointer is not None:
            return
        import aiosqlite
        self._aio_conn = await aiosqlite.connect(self._saver_path)
        # 启用 WAL 模式提升并发读写性能
        await self._aio_conn.execute("PRAGMA journal_mode=WAL")
        await self._aio_conn.execute("PRAGMA busy_timeout=5000")
        self.checkpointer = AsyncSqliteSaver(self._aio_conn)
        await self.checkpointer.setup()
        # build_graph 编译时绑定 checkpointer，确保 interrupt/resume 和 aget_state 都能正常工作
        self.graph = build_graph({
            "repo": self.repo,
            "llm_client": self.llm_client,
            "polisher_client": self._polisher_client,
            "summarizer_client": self._summarizer_client,
            "recall": self.recall,
            "applier": self.applier,
            "archival": self.archival,
            "auditor": self.auditor,
            "config": self.config,
        }, checkpointer=self.checkpointer)
        # 打印各 agent 实际使用的模型，方便确认多 agent 配置生效
        logger.info("ChapterRunner 初始化完成 | project=%s | 模型分配: writer=%s, auditor=%s, debater=%s, polisher=%s, summarizer=%s",
                    self.repo.project_id,
                    self.llm_client.config.model,
                    self._auditor_client.config.model,
                    self._debater_client.config.model,
                    self._polisher_client.config.model,
                    self._summarizer_client.config.model)

    # ── 跨进程重启检查点（借鉴 DeterminFlow task_recovery.py）──────────────
    # checkpoint_meta 表记录每次 run 的执行状态，进程崩溃后可据此恢复。
    # 所有写操作用 try/except 包裹，失败只记日志不阻塞生成主流程。
    @property
    def _checkpoint_db_path(self) -> str:
        """checkpoint_meta 专用 SQLite 路径（独立于 langgraph 的 checkpoints.db）。"""
        return str(self.config.project_dir(self.repo.project_id) / "checkpoint_meta.db")

    def _ensure_checkpoint_db(self) -> None:
        """确保 checkpoint_meta 表存在。"""
        import sqlite3

        Path(self._checkpoint_db_path).parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(self._checkpoint_db_path)
        try:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS checkpoint_meta (
                    thread_id TEXT PRIMARY KEY,
                    project_id TEXT,
                    chapter INTEGER,
                    status TEXT,
                    node_name TEXT,
                    timestamp TEXT,
                    state_json TEXT
                )
                """
            )
            conn.commit()
        finally:
            conn.close()

    def save_checkpoint(self, thread_id: str, chapter: int, status: str,
                        node_name: str = "", state: dict | None = None) -> None:
        """保存当前执行状态到 SQLite（checkpoint_meta 表）。

        Args:
            thread_id: 线程 id（断点续跑标识）
            chapter: 章节号
            status: running / completed / failed / interrupted
            node_name: 最后执行的节点名
            state: 序列化的执行状态（result dict），可选
        """
        import json
        import sqlite3
        from datetime import datetime, timezone

        self._ensure_checkpoint_db()
        timestamp = datetime.now(timezone.utc).isoformat()
        state_json = ""
        if state is not None:
            try:
                state_json = json.dumps(state, ensure_ascii=False, default=str)
            except Exception as e:
                logger.warning("checkpoint state 序列化失败: %s", e)
                state_json = ""
        conn = sqlite3.connect(self._checkpoint_db_path)
        try:
            conn.execute(
                "INSERT OR REPLACE INTO checkpoint_meta "
                "(thread_id, project_id, chapter, status, node_name, timestamp, state_json) "
                "VALUES (?, ?, ?, ?, ?, ?, ?)",
                (thread_id, str(self.repo.project_id), chapter, status,
                 node_name, timestamp, state_json),
            )
            conn.commit()
        finally:
            conn.close()
        logger.debug("checkpoint 已保存: thread=%s chapter=%d status=%s", thread_id, chapter, status)

    def load_checkpoint(self, thread_id: str) -> dict | None:
        """从 SQLite 恢复执行状态。

        Returns:
            checkpoint dict（含 state 反序列化字段），未找到返回 None
        """
        import json
        import sqlite3

        self._ensure_checkpoint_db()
        conn = sqlite3.connect(self._checkpoint_db_path)
        conn.row_factory = sqlite3.Row
        try:
            row = conn.execute(
                "SELECT * FROM checkpoint_meta WHERE thread_id = ?", (thread_id,)
            ).fetchone()
            if row is None:
                return None
            result = dict(row)
            if result.get("state_json"):
                try:
                    result["state"] = json.loads(result["state_json"])
                except Exception:
                    result["state"] = None
            else:
                result["state"] = None
            return result
        finally:
            conn.close()

    def list_checkpoints(self, project_id) -> list[dict]:
        """列出项目的所有 checkpoint（按时间倒序）。"""
        import sqlite3

        self._ensure_checkpoint_db()
        conn = sqlite3.connect(self._checkpoint_db_path)
        conn.row_factory = sqlite3.Row
        try:
            rows = conn.execute(
                "SELECT * FROM checkpoint_meta WHERE project_id = ? ORDER BY timestamp DESC",
                (str(project_id),),
            ).fetchall()
            return [dict(r) for r in rows]
        finally:
            conn.close()

    def resume_from_checkpoint(self, thread_id: str) -> dict:
        """从 checkpoint 恢复执行。

        仅返回可恢复的 checkpoint 信息，调用方据此重新调用 run 续跑。
        langgraph 的 AsyncSqliteSaver 已按 thread_id 持久化 graph 状态，
        用相同 thread_id 重跑即可从断点恢复。
        """
        cp = self.load_checkpoint(thread_id)
        if cp is None:
            return {"status": "failed", "error": f"未找到 thread_id={thread_id} 的 checkpoint"}
        if cp.get("status") not in (TaskStatus.INTERRUPTED.value, TaskStatus.FAILED.value):
            return {
                "status": "skipped",
                "message": f"checkpoint 状态为 {cp.get('status')}，无需恢复",
            }
        return {
            "status": "resumable",
            "thread_id": thread_id,
            "chapter": cp.get("chapter"),
            "last_node": cp.get("node_name"),
            "checkpoint_status": cp.get("status"),
            "state": cp.get("state"),
        }

    async def run(self, chapter: int, title: str,
                  thread_id: str | None = None) -> dict:
        """运行单章生成流水线。

        Args:
            chapter: 章节号
            title: 章节标题
            thread_id: 断点续跑的线程 id；同 id 重跑会从 checkpoint 恢复
        """
        tid = thread_id or str(uuid.uuid4())
        # 确保 checkpointer 和 graph 已初始化
        await self._ensure_checkpointer()
        # 注册取消令牌
        _cancel_tokens[tid] = asyncio.Event()
        # 跨进程重启检查点：检查是否有中断的 checkpoint 并提示恢复
        try:
            interrupted = [
                cp for cp in self.list_checkpoints(self.repo.project_id)
                if cp.get("status") == TaskStatus.INTERRUPTED.value
            ]
            if interrupted:
                logger.warning(
                    "发现 %d 个中断的生成 checkpoint，可调用 resume_from_checkpoint 恢复: %s",
                    len(interrupted),
                    [cp.get("thread_id") for cp in interrupted],
                )
        except Exception as e:
            logger.debug("检查中断 checkpoint 失败，跳过: %s", e)
        # 开始时保存 checkpoint（status=running），失败不阻塞生成
        try:
            self.save_checkpoint(tid, chapter, TaskStatus.RUNNING.value)
        except Exception as e:
            logger.warning("保存 running checkpoint 失败，不阻塞生成: %s", e)
        initial_state = {
            "project_id": self.repo.project_id,
            "chapter": chapter,
            "title": title,
            "context": "",
            "draft": "",
            "status": ChapterGenStatus.PENDING.value,
            "error": "",
            "word_count": 0,
            "_thread_id": tid,  # 传递给节点检查取消
        }
        try:
            result = await asyncio.wait_for(
                self.graph.ainvoke(
                    initial_state, config={"configurable": {"thread_id": tid}},
                ),
                timeout=2100,  # 35 分钟，与前端 GEN_TIMEOUT 和 config.py 默认值统一
            )
            # 完成时更新 checkpoint（status=completed）
            try:
                self.save_checkpoint(tid, chapter, TaskStatus.COMPLETED.value, state=result)
            except Exception as e:
                logger.warning("更新 completed checkpoint 失败: %s", e)
            return result
        except asyncio.TimeoutError:
            # 异常时更新 checkpoint（status=interrupted）
            try:
                self.save_checkpoint(tid, chapter, TaskStatus.INTERRUPTED.value)
            except Exception as e:
                logger.warning("更新 interrupted checkpoint 失败: %s", e)
            return {"status": "failed", "error": "生成超时（35分钟）"}
        except Exception:
            # 其他异常：更新 checkpoint 后重新抛出，便于进程重启后恢复
            try:
                self.save_checkpoint(tid, chapter, TaskStatus.INTERRUPTED.value)
            except Exception as e:
                logger.warning("更新 interrupted checkpoint 失败: %s", e)
            raise
        finally:
            clear_cancel_token(tid)

    async def close(self):
        await self.llm_client.close()
        await self._auditor_client.close()
        for c in self._extra_clients:
            try:
                await c.close()
            except Exception:
                pass
        self._extra_clients.clear()
        if self._aio_conn:
            await self._aio_conn.close()
