"""Chat session 持久化存储：SQLite 替代内存 dict。

阶段 1+2 改造：把会话状态从进程内存搬到 SQLite，支持断线重连和状态查询。

两张表：
- sessions：聊天会话的 busy 标志 + steer_queue（替代 SessionManager 内存字典）。
  对应 ``novel_agent/chat/session.py`` 的 Session/SessionManager，busy 和 steer
  落盘后可在进程重启 / 断线重连后恢复；messages 列预留给未来存 in-flight 快照
  （当前对话历史仍由 chat_repo 的 ChatMessage 表管理，不在此重复）。
- interactive_sessions：交互式创作会话的完整状态 JSON（替代
  ``routes_generation._INTERACTIVE_SESSIONS`` 内存字典），存 draft/audit_report/
  polished 等全部字段。

cancel_event（asyncio.Event）是运行中 turn 的瞬态信号，无法序列化，保留在内存中——
进程重启时 turn 已死，无需恢复取消令牌；正常断线由 finally 释放 busy。
"""
from __future__ import annotations

import asyncio
import json
import logging
import sqlite3
import threading
from datetime import datetime
from pathlib import Path
from typing import Any

from novel_agent.config import load_config

logger = logging.getLogger(__name__)

# 交互式创作会话最大存活时间（秒），超时自动清理
_INTERACTIVE_TTL = 3600
# busy 标志 stale 阈值（秒）：超过则视为崩溃残留，强制释放（匹配 LLM 35min 超时）
_STALE_BUSY_TTL = 1800


def _default_db_path() -> Path:
    """返回 chat_sessions.db 路径，放在项目数据目录下。"""
    cfg = load_config()
    return cfg.project_data_dir / "chat_sessions.db"


class SessionStore:
    """SQLite-backed session persistence。

    替代 SessionManager（chat）和 _INTERACTIVE_SESSIONS（interactive）两个内存字典。
    cancel_event 仍用内存 dict（瞬态，进程内有效）。
    """

    def __init__(self, db_path: Path | None = None):
        self._db_path = db_path or _default_db_path()
        self._db_path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
        # 运行中 turn 的取消令牌（瞬态，不持久化）
        self._cancel_events: dict[str, asyncio.Event] = {}
        self._init_db()

    # ------------------------------------------------------------------
    # DB helpers
    # ------------------------------------------------------------------
    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(str(self._db_path), check_same_thread=False, timeout=30.0)
        conn.row_factory = sqlite3.Row
        return conn

    def _init_db(self) -> None:
        with self._lock:
            conn = self._connect()
            try:
                conn.execute(
                    """CREATE TABLE IF NOT EXISTS sessions (
                        session_id TEXT PRIMARY KEY,
                        project_id INTEGER NOT NULL DEFAULT 0,
                        messages TEXT NOT NULL DEFAULT '[]',
                        created_at TEXT NOT NULL,
                        updated_at TEXT NOT NULL,
                        busy INTEGER DEFAULT 0,
                        steer_queue TEXT DEFAULT '[]'
                    )"""
                )
                conn.execute(
                    """CREATE TABLE IF NOT EXISTS interactive_sessions (
                        session_id TEXT PRIMARY KEY,
                        project_id INTEGER NOT NULL DEFAULT 0,
                        data TEXT NOT NULL DEFAULT '{}',
                        created_at TEXT NOT NULL,
                        updated_at TEXT NOT NULL
                    )"""
                )
                conn.commit()
            finally:
                conn.close()

    @staticmethod
    def _now() -> str:
        return datetime.utcnow().isoformat()

    # ------------------------------------------------------------------
    # Chat sessions（替代 SessionManager）
    # ------------------------------------------------------------------
    def _ensure_chat_row(self, session_id: str, project_id: int) -> None:
        """确保 sessions 表有该 session_id 的行（不存在则插入默认行）。"""
        with self._lock:
            conn = self._connect()
            try:
                row = conn.execute(
                    "SELECT 1 FROM sessions WHERE session_id = ?", (session_id,)
                ).fetchone()
                if row is None:
                    now = self._now()
                    conn.execute(
                        """INSERT INTO sessions
                           (session_id, project_id, messages, created_at, updated_at, busy, steer_queue)
                           VALUES (?, ?, '[]', ?, ?, 0, '[]')""",
                        (session_id, project_id, now, now),
                    )
                    conn.commit()
            finally:
                conn.close()

    def try_acquire(self, session_id: str, project_id: int = 0) -> bool:
        """原子 check-and-set busy（对齐原 Session.try_acquire）。

        成功表示当前没有 turn 在跑，调用方应启动 turn；
        失败表示已有 turn 在跑，调用方应走 steer 路径。

        崩溃恢复：busy=1 但超过 _STALE_BUSY_TTL 未更新，视为残留，强制释放后 acquire。
        """
        self._ensure_chat_row(session_id, project_id)
        with self._lock:
            conn = self._connect()
            try:
                row = conn.execute(
                    "SELECT busy, updated_at FROM sessions WHERE session_id = ?", (session_id,)
                ).fetchone()
                if row and row["busy"]:
                    try:
                        updated = datetime.fromisoformat(row["updated_at"])
                        if (datetime.utcnow() - updated).total_seconds() > _STALE_BUSY_TTL:
                            logger.warning(
                                "Session %s busy 超 %d 秒未更新，强制释放（崩溃恢复）",
                                session_id, _STALE_BUSY_TTL,
                            )
                            conn.execute(
                                "UPDATE sessions SET busy = 0, steer_queue = '[]', updated_at = ? "
                                "WHERE session_id = ?",
                                (self._now(), session_id),
                            )
                            conn.commit()
                    except Exception:
                        pass
                # 原子 acquire：只有 busy=0 时才置 1
                cur = conn.execute(
                    "UPDATE sessions SET busy = 1, updated_at = ? "
                    "WHERE session_id = ? AND busy = 0",
                    (self._now(), session_id),
                )
                conn.commit()
                return cur.rowcount > 0
            finally:
                conn.close()

    def set_busy(self, session_id: str, val: bool, project_id: int = 0) -> None:
        """更新 busy。set_busy(False) 时同时清空 stale steer（对齐原 Session 行为）。"""
        self._ensure_chat_row(session_id, project_id)
        with self._lock:
            conn = self._connect()
            try:
                if val:
                    conn.execute(
                        "UPDATE sessions SET busy = 1, updated_at = ? WHERE session_id = ?",
                        (self._now(), session_id),
                    )
                else:
                    conn.execute(
                        "UPDATE sessions SET busy = 0, steer_queue = '[]', updated_at = ? "
                        "WHERE session_id = ?",
                        (self._now(), session_id),
                    )
                conn.commit()
            finally:
                conn.close()

    def steer(self, session_id: str, text: str, project_id: int = 0) -> None:
        """追加 steer 输入到队列（对齐原 Session.steer）。"""
        self._ensure_chat_row(session_id, project_id)
        with self._lock:
            conn = self._connect()
            try:
                row = conn.execute(
                    "SELECT steer_queue FROM sessions WHERE session_id = ?", (session_id,)
                ).fetchone()
                queue = json.loads(row["steer_queue"]) if row else []
                queue.append(text)
                conn.execute(
                    "UPDATE sessions SET steer_queue = ?, updated_at = ? WHERE session_id = ?",
                    (json.dumps(queue, ensure_ascii=False), self._now(), session_id),
                )
                conn.commit()
            finally:
                conn.close()
        logger.info("Session %s steer 注入: %s", session_id, text[:80])

    def drain_steer(self, session_id: str) -> list[str]:
        """取出并清空 steer 队列（对齐原 Session.drain_steer）。"""
        with self._lock:
            conn = self._connect()
            try:
                row = conn.execute(
                    "SELECT steer_queue FROM sessions WHERE session_id = ?", (session_id,)
                ).fetchone()
                if not row:
                    return []
                queue: list[str] = json.loads(row["steer_queue"])
                conn.execute(
                    "UPDATE sessions SET steer_queue = '[]', updated_at = ? WHERE session_id = ?",
                    (self._now(), session_id),
                )
                conn.commit()
                return queue
            finally:
                conn.close()

    def get_chat_status(self, session_id: str) -> dict | None:
        """查询会话运行状态（供断线重连 / status 端点）。无记录返回 None。"""
        with self._lock:
            conn = self._connect()
            try:
                row = conn.execute(
                    "SELECT * FROM sessions WHERE session_id = ?", (session_id,)
                ).fetchone()
                if not row:
                    return None
                return {
                    "session_id": row["session_id"],
                    "project_id": row["project_id"],
                    "busy": bool(row["busy"]),
                    "steer_pending": len(json.loads(row["steer_queue"] or "[]")),
                    "created_at": row["created_at"],
                    "updated_at": row["updated_at"],
                }
            finally:
                conn.close()

    # -- cancel_event（内存瞬态，不持久化）--
    def get_cancel_event(self, session_id: str) -> asyncio.Event:
        ev = self._cancel_events.get(session_id)
        if ev is None:
            ev = asyncio.Event()
            self._cancel_events[session_id] = ev
        return ev

    def clear_cancel(self, session_id: str) -> None:
        ev = self._cancel_events.get(session_id)
        if ev:
            ev.clear()

    def interrupt(self, session_id: str) -> None:
        ev = self._cancel_events.get(session_id)
        if ev:
            ev.set()
        logger.info("Session %s interrupt", session_id)

    # ------------------------------------------------------------------
    # Interactive sessions（替代 _INTERACTIVE_SESSIONS）
    # ------------------------------------------------------------------
    def save_interactive(self, session_id: str, project_id: int, data: dict) -> None:
        """upsert 完整状态 dict（JSON blob）。"""
        with self._lock:
            conn = self._connect()
            try:
                now = self._now()
                existing = conn.execute(
                    "SELECT created_at FROM interactive_sessions WHERE session_id = ?",
                    (session_id,),
                ).fetchone()
                created = existing["created_at"] if existing else now
                conn.execute(
                    """INSERT INTO interactive_sessions
                       (session_id, project_id, data, created_at, updated_at)
                       VALUES (?, ?, ?, ?, ?)
                       ON CONFLICT(session_id) DO UPDATE SET
                         project_id = excluded.project_id,
                         data = excluded.data,
                         updated_at = excluded.updated_at""",
                    (session_id, project_id,
                     json.dumps(data, ensure_ascii=False), created, now),
                )
                conn.commit()
            finally:
                conn.close()

    def get_interactive(self, session_id: str) -> dict | None:
        with self._lock:
            conn = self._connect()
            try:
                row = conn.execute(
                    "SELECT data FROM interactive_sessions WHERE session_id = ?", (session_id,)
                ).fetchone()
                if not row:
                    return None
                return json.loads(row["data"])
            finally:
                conn.close()

    def update_interactive(self, session_id: str, project_id: int = 0, **fields: Any) -> None:
        """合并更新部分字段（原子 get+merge+save，单次加锁）。"""
        with self._lock:
            conn = self._connect()
            try:
                row = conn.execute(
                    "SELECT data, project_id, created_at FROM interactive_sessions "
                    "WHERE session_id = ?",
                    (session_id,),
                ).fetchone()
                if row:
                    data = json.loads(row["data"])
                    pid = row["project_id"] or project_id
                    created = row["created_at"]
                else:
                    data = {}
                    pid = project_id
                    created = self._now()
                data.update(fields)
                now = self._now()
                conn.execute(
                    """INSERT INTO interactive_sessions
                       (session_id, project_id, data, created_at, updated_at)
                       VALUES (?, ?, ?, ?, ?)
                       ON CONFLICT(session_id) DO UPDATE SET
                         project_id = excluded.project_id,
                         data = excluded.data,
                         updated_at = excluded.updated_at""",
                    (session_id, pid,
                     json.dumps(data, ensure_ascii=False), created, now),
                )
                conn.commit()
            finally:
                conn.close()

    def delete_interactive(self, session_id: str) -> None:
        with self._lock:
            conn = self._connect()
            try:
                conn.execute(
                    "DELETE FROM interactive_sessions WHERE session_id = ?", (session_id,)
                )
                conn.commit()
            finally:
                conn.close()

    def cleanup_expired_interactive(self, ttl: int = _INTERACTIVE_TTL) -> int:
        """清理过期交互式创作会话，返回清理数量。"""
        now = datetime.utcnow()
        expired: list[str] = []
        with self._lock:
            conn = self._connect()
            try:
                rows = conn.execute(
                    "SELECT session_id, created_at FROM interactive_sessions"
                ).fetchall()
                for r in rows:
                    try:
                        created_dt = datetime.fromisoformat(r["created_at"])
                        if (now - created_dt).total_seconds() > ttl:
                            expired.append(r["session_id"])
                    except Exception:
                        expired.append(r["session_id"])
                for sid in expired:
                    conn.execute(
                        "DELETE FROM interactive_sessions WHERE session_id = ?", (sid,)
                    )
                conn.commit()
            finally:
                conn.close()
        if expired:
            logger.info("清理了 %d 个过期的交互式创作会话", len(expired))
        return len(expired)


# ------------------------------------------------------------------
# 模块级单例
# ------------------------------------------------------------------
_store: SessionStore | None = None
_store_lock = threading.Lock()


def get_session_store() -> SessionStore:
    """获取全局 SessionStore 单例（惰性初始化）。"""
    global _store
    if _store is None:
        with _store_lock:
            if _store is None:
                _store = SessionStore()
    return _store
