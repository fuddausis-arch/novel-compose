"""圆桌会议 SQLite 持久化层。

用 SQLite 存储完整的会话 JSON（序列化为 data 列），替代 DeterminFlow 的
JSON 文件方案。表结构简单：每行一个 session，主键 session_id。

使用 sqlite3 + WAL 模式，threading.Lock 保护跨线程写入。
"""
from __future__ import annotations

import json
import logging
import sqlite3
import threading
from datetime import datetime, timezone
from pathlib import Path

from novel_agent.config import load_config

logger = logging.getLogger("roundtable")

_db_path_cache: Path | None = None
_db_lock = threading.Lock()


def _get_db_path() -> Path:
    """返回 roundtable.db 路径（缓存在模块级，首次从 config 读取）。"""
    global _db_path_cache
    if _db_path_cache is None:
        cfg = load_config()
        _db_path_cache = cfg.project_data_dir / "roundtable.db"
    _db_path_cache.parent.mkdir(parents=True, exist_ok=True)
    return _db_path_cache


def _get_conn() -> sqlite3.Connection:
    conn = sqlite3.connect(str(_get_db_path()), check_same_thread=False)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA busy_timeout=5000")
    return conn


def _ensure_table(conn: sqlite3.Connection) -> None:
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS roundtable_sessions (
            session_id  TEXT PRIMARY KEY,
            topic       TEXT NOT NULL,
            status      TEXT NOT NULL,
            data        TEXT NOT NULL,
            created_at  TEXT NOT NULL,
            updated_at  TEXT NOT NULL
        )
        """
    )
    conn.commit()


class RoundtableStore:
    """SQLite-backed persistence for roundtable sessions."""

    def save(self, session_data: dict) -> bool:
        """插入或更新一条会话记录。返回 True 表示成功。"""
        now = datetime.now(timezone.utc).isoformat()
        with _db_lock:
            conn = _get_conn()
            try:
                _ensure_table(conn)
                conn.execute(
                    """
                    INSERT INTO roundtable_sessions
                        (session_id, topic, status, data, created_at, updated_at)
                    VALUES (?, ?, ?, ?, ?, ?)
                    ON CONFLICT(session_id) DO UPDATE SET
                        topic      = excluded.topic,
                        status     = excluded.status,
                        data       = excluded.data,
                        updated_at = excluded.updated_at
                    """,
                    (
                        session_data["session_id"],
                        session_data.get("topic", ""),
                        session_data.get("status", "waiting"),
                        json.dumps(session_data, ensure_ascii=False),
                        session_data.get("created_at", now),
                        now,
                    ),
                )
                conn.commit()
                return True
            except (sqlite3.Error, OSError) as e:
                logger.error(f"RoundtableStore.save 失败: {e}")
                return False
            finally:
                conn.close()

    def load(self, session_id: str) -> dict | None:
        """按 session_id 加载一条会话数据，不存在返回 None。"""
        with _db_lock:
            conn = _get_conn()
            try:
                _ensure_table(conn)
                row = conn.execute(
                    "SELECT data FROM roundtable_sessions WHERE session_id = ?",
                    (session_id,),
                ).fetchone()
                if row is None:
                    return None
                return json.loads(row[0])
            except (sqlite3.Error, json.JSONDecodeError) as e:
                logger.error(f"RoundtableStore.load({session_id}) 失败: {e}")
                return None
            finally:
                conn.close()

    def load_all(self) -> list[dict]:
        """加载所有会话数据，按创建时间排序。"""
        with _db_lock:
            conn = _get_conn()
            try:
                _ensure_table(conn)
                rows = conn.execute(
                    "SELECT data FROM roundtable_sessions ORDER BY created_at"
                ).fetchall()
                result = []
                for r in rows:
                    try:
                        result.append(json.loads(r[0]))
                    except json.JSONDecodeError:
                        continue
                return result
            except sqlite3.Error as e:
                logger.error(f"RoundtableStore.load_all 失败: {e}")
                return []
            finally:
                conn.close()

    def delete(self, session_id: str) -> bool:
        """删除一条会话记录，返回是否删除了行。"""
        with _db_lock:
            conn = _get_conn()
            try:
                _ensure_table(conn)
                cur = conn.execute(
                    "DELETE FROM roundtable_sessions WHERE session_id = ?",
                    (session_id,),
                )
                conn.commit()
                return cur.rowcount > 0
            except sqlite3.Error as e:
                logger.error(f"RoundtableStore.delete({session_id}) 失败: {e}")
                return False
            finally:
                conn.close()


# 模块级单例
store = RoundtableStore()
