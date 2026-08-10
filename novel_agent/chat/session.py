"""Session：结合本项目的轻量会话状态管理。

照搬 Codex 的 steer（input_queue.rs）+ cancel（CancellationToken）设计，
但放弃 submission_loop/双通道/Op/Event（那是 Codex TUI 长生命周期场景，
本项目是 HTTP 一问一答，用不上--硬套就是壳）。

Session 持久化（SessionManager 按 chat session_id 跨请求复用）：
- steer_input：用户在 agent 跑时发的消息，工具间隙注入（照搬 Codex Steer）
- cancel_event：中断当前 turn（照搬 Codex CancellationToken）
- busy：是否正在跑 turn。busy 时新消息自动转 steer（不需要单独 steer 端点）

结合项目实际：
- chat_repo 已经持久化 ChatMessage（对话历史），Session 不重复存 history
- agent 每次 turn 创建（带新 db session），Session 不持有 agent
- Session 只管 steer + cancel + busy 状态

设计来源：codex-rs/core/src/session/input_queue.rs（Steer）、
client.rs（CancellationToken）、thread_manager（注册表）
"""
from __future__ import annotations

import asyncio
import logging
import time

logger = logging.getLogger(__name__)


class Session:
    """轻量会话状态：steer + cancel + busy。

    不持有 agent（agent 每次 turn 创建，避免 DB session 跨请求失效）。
    只管跨请求需要保持的状态：steer 输入、取消令牌、busy 标志。
    """

    def __init__(self, session_id: str):
        self.session_id = session_id
        # 会话创建时间，用于自动清理（超过 30 分钟无活动移除）
        self.created_at = time.time()
        # steer 待注入输入（照搬 Codex TurnInputQueue）
        self._steer_input: list[str] = []
        # 中断令牌（照搬 Codex CancellationToken）
        self._cancel_event = asyncio.Event()
        # 是否正在跑 turn（busy 时新消息转 steer）
        self._busy = False
        # Bug 7: busy 的 check-and-set 必须原子，防并发竞态
        self._busy_lock = asyncio.Lock()

    @property
    def busy(self) -> bool:
        return self._busy

    async def try_acquire(self) -> bool:
        """Bug 7: 原子 check-and-set。获取 busy，返回是否成功。

        成功表示当前没有 turn 在跑，调用方应启动 turn；
        失败表示已有 turn 在跑，调用方应走 steer 路径。
        """
        async with self._busy_lock:
            if self._busy:
                return False
            self._busy = True
            return True

    def set_busy(self, val: bool):
        """更新 busy 状态。set_busy(False) 时同时清空 stale steer（Bug 6）。"""
        self._busy = val
        if not val:
            # Bug 6: turn 结束，清掉可能的 stale steer，防下一 turn 误注入
            self._steer_input.clear()

    def steer(self, text: str):
        """照搬 Codex InputQueue.Steer：非破坏性注入。

        用户在 agent 跑时发消息，不中断生成，在下一个工具调用间隙注入 messages。
        """
        self._steer_input.append(text)
        logger.info("Session %s steer 注入: %s", self.session_id, text[:80])

    def drain_steer(self) -> list[str]:
        """取出并清空 steer 输入（照搬 Codex take_pending_input_for_turn_state）。

        agent 在每轮工具执行后调用，拿到待注入的用户补充输入。
        """
        s = self._steer_input[:]
        self._steer_input.clear()
        return s

    def interrupt(self):
        """照搬 Codex Op::Interrupt：硬中断当前 turn。"""
        self._cancel_event.set()
        logger.info("Session %s interrupt", self.session_id)

    def clear_cancel(self):
        """新 turn 开始前清取消令牌。"""
        self._cancel_event.clear()

    @property
    def cancel_event(self) -> asyncio.Event:
        return self._cancel_event


class SessionManager:
    """照搬 Codex ThreadManager 的线程注册表：按 session_id 持久化 Session。

    全局字典 + 锁。Session 跨请求复用（同一个 chat 会话的多次消息共用一个 Session）。
    """

    _sessions: dict[str, Session] = {}
    _lock = asyncio.Lock()

    @classmethod
    async def get_or_create(cls, session_id: str) -> Session:
        """获取或创建 Session（照搬 Codex ThreadManager.get_thread）。

        顺带清理超过 30 分钟无活动的会话，避免内存泄漏。
        """
        async with cls._lock:
            # 清理超过 30 分钟无活动的会话
            now = time.time()
            expired = [sid for sid, s in cls._sessions.items() if now - s.created_at > 1800]
            for sid in expired:
                cls._sessions.pop(sid, None)
                logger.info("Session %s 超时未活动，自动清理", sid)
            if session_id not in cls._sessions:
                cls._sessions[session_id] = Session(session_id)
                logger.info("Session %s 创建并注册", session_id)
            return cls._sessions[session_id]

    @classmethod
    async def remove(cls, session_id: str):
        """移除 Session（照搬 Codex ThreadManager.remove_thread）。"""
        async with cls._lock:
            cls._sessions.pop(session_id, None)
            logger.info("Session %s 移除", session_id)

    @classmethod
    async def get(cls, session_id: str) -> Session | None:
        """只获取不创建（用于检查 busy 状态）。"""
        async with cls._lock:
            return cls._sessions.get(session_id)
