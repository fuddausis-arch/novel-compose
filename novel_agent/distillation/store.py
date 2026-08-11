"""蒸馏模块 SQLite 存储层。

管理蒸馏作品、文本片段、蒸馏轮次、生成的 Skill 单元与融合方案。
数据库文件：project_data/distillation.db。
模式对齐 chat/session_store.py：raw sqlite3 + threading.Lock + Row factory。
"""
from __future__ import annotations

import json
import logging
import sqlite3
import threading
from datetime import datetime
from pathlib import Path
from typing import Any

from novel_agent.config import load_config
from novel_agent.state_common import DistillStatus

logger = logging.getLogger(__name__)


def _default_db_path() -> Path:
    """返回 distillation.db 路径，放在项目数据目录下。"""
    cfg = load_config()
    return cfg.project_data_dir / "distillation.db"


class DistillationStore:
    """蒸馏数据的 SQLite 持久化。"""

    def __init__(self, db_path: Path | None = None):
        self._db_path = db_path or _default_db_path()
        self._db_path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
        self._init_db()

    # ------------------------------------------------------------------
    # DB helpers
    # ------------------------------------------------------------------
    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(str(self._db_path), check_same_thread=False, timeout=30.0)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys=ON")
        return conn

    def _init_db(self) -> None:
        with self._lock:
            conn = self._connect()
            try:
                conn.executescript(
                    f"""CREATE TABLE IF NOT EXISTS distill_works (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        title TEXT NOT NULL,
                        source_type TEXT NOT NULL DEFAULT 'file',
                        file_path TEXT,
                        total_chars INTEGER NOT NULL DEFAULT 0,
                        chunk_count INTEGER NOT NULL DEFAULT 0,
                        status TEXT NOT NULL DEFAULT '{DistillStatus.PENDING.value}',
                        created_at TEXT NOT NULL
                    );
                    CREATE TABLE IF NOT EXISTS distill_chunks (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        work_id INTEGER NOT NULL REFERENCES distill_works(id) ON DELETE CASCADE,
                        chunk_index INTEGER NOT NULL,
                        content TEXT NOT NULL,
                        char_count INTEGER NOT NULL DEFAULT 0,
                        status TEXT NOT NULL DEFAULT '{DistillStatus.PENDING.value}'
                    );
                    CREATE TABLE IF NOT EXISTS distill_rounds (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        chunk_id INTEGER NOT NULL REFERENCES distill_chunks(id) ON DELETE CASCADE,
                        round_num INTEGER NOT NULL,
                        prompt_used TEXT NOT NULL DEFAULT '',
                        result_text TEXT NOT NULL DEFAULT '',
                        skill_data_json TEXT NOT NULL DEFAULT '',
                        status TEXT NOT NULL DEFAULT '{DistillStatus.PENDING.value}',
                        created_at TEXT NOT NULL
                    );
                    CREATE TABLE IF NOT EXISTS distill_skills (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        work_id INTEGER NOT NULL REFERENCES distill_works(id) ON DELETE CASCADE,
                        work_title TEXT NOT NULL DEFAULT '',
                        chunk_index INTEGER NOT NULL DEFAULT 0,
                        round_num INTEGER NOT NULL DEFAULT 0,
                        name TEXT NOT NULL,
                        description TEXT NOT NULL DEFAULT '',
                        content TEXT NOT NULL DEFAULT '',
                        tags TEXT NOT NULL DEFAULT '[]',
                        status TEXT NOT NULL DEFAULT 'active',
                        created_at TEXT NOT NULL
                    );
                    CREATE TABLE IF NOT EXISTS distill_fusions (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        name TEXT NOT NULL,
                        skill_ids_json TEXT NOT NULL DEFAULT '[]',
                        weights_json TEXT NOT NULL DEFAULT '[]',
                        description TEXT NOT NULL DEFAULT '',
                        status TEXT NOT NULL DEFAULT 'active',
                        skill_file TEXT NOT NULL DEFAULT '',
                        finished_at TEXT NOT NULL DEFAULT '',
                        created_at TEXT NOT NULL
                    );"""
                )
                conn.commit()
                # 存量库兼容迁移：distill_fusions 补 skill_file / finished_at 列
                for col, ddl in (
                    ("skill_file", "ALTER TABLE distill_fusions ADD COLUMN skill_file TEXT NOT NULL DEFAULT ''"),
                    ("finished_at", "ALTER TABLE distill_fusions ADD COLUMN finished_at TEXT NOT NULL DEFAULT ''"),
                ):
                    try:
                        has = [r[1] for r in conn.execute("PRAGMA table_info(distill_fusions)").fetchall()]
                        if col not in has:
                            conn.execute(ddl)
                            conn.commit()
                    except Exception:
                        pass
            finally:
                conn.close()

        # 启动时清理孤儿状态：上次服务崩溃/重启后，distilling 状态的 work
        # 没有对应运行中的任务，进度永远冻结。标记为 failed 让用户可以重新蒸馏。
        with self._lock:
            conn = self._connect()
            try:
                conn.execute(
                    f"UPDATE distill_works SET status='failed'"
                    f" WHERE status='{DistillStatus.DISTILLING.value}'"
                )
                conn.commit()
            except Exception:
                pass
            finally:
                conn.close()

    @staticmethod
    def _now() -> str:
        return datetime.now().isoformat()

    @staticmethod
    def _row_to_dict(row: sqlite3.Row | None) -> dict | None:
        return dict(row) if row is not None else None

    # ------------------------------------------------------------------
    # works
    # ------------------------------------------------------------------
    def create_work(self, title: str, source_type: str, file_path: str | None,
                    total_chars: int, chunk_count: int) -> int:
        with self._lock:
            conn = self._connect()
            try:
                cur = conn.execute(
                    "INSERT INTO distill_works (title, source_type, file_path, total_chars, chunk_count, status, created_at)"
                    f" VALUES (?, ?, ?, ?, ?, '{DistillStatus.PENDING.value}', ?)",
                    (title, source_type, file_path, total_chars, chunk_count, self._now()),
                )
                conn.commit()
                return int(cur.lastrowid)
            finally:
                conn.close()

    def list_works(self) -> list[dict]:
        with self._lock:
            conn = self._connect()
            try:
                rows = conn.execute(
                    "SELECT * FROM distill_works ORDER BY id DESC"
                ).fetchall()
                return [dict(r) for r in rows]
            finally:
                conn.close()

    def get_work(self, work_id: int) -> dict | None:
        with self._lock:
            conn = self._connect()
            try:
                row = conn.execute(
                    "SELECT * FROM distill_works WHERE id=?", (work_id,)
                ).fetchone()
                return self._row_to_dict(row)
            finally:
                conn.close()

    def update_work_status(self, work_id: int, status: str) -> None:
        with self._lock:
            conn = self._connect()
            try:
                conn.execute(
                    "UPDATE distill_works SET status=? WHERE id=?", (status, work_id)
                )
                conn.commit()
            finally:
                conn.close()

    def delete_work(self, work_id: int) -> bool:
        """删除作品（chunks/rounds/skills 外键级联删除）。返回是否存在。"""
        with self._lock:
            conn = self._connect()
            try:
                cur = conn.execute("DELETE FROM distill_works WHERE id=?", (work_id,))
                conn.commit()
                return cur.rowcount > 0
            finally:
                conn.close()

    # ------------------------------------------------------------------
    # chunks
    # ------------------------------------------------------------------
    def create_chunk(self, work_id: int, chunk_index: int, content: str) -> int:
        with self._lock:
            conn = self._connect()
            try:
                cur = conn.execute(
                    "INSERT INTO distill_chunks (work_id, chunk_index, content, char_count, status)"
                    f" VALUES (?, ?, ?, ?, '{DistillStatus.PENDING.value}')",
                    (work_id, chunk_index, content, len(content)),
                )
                conn.commit()
                return int(cur.lastrowid)
            finally:
                conn.close()

    def list_chunks(self, work_id: int, include_content: bool = False) -> list[dict]:
        cols = "*" if include_content else "id, work_id, chunk_index, char_count, status"
        with self._lock:
            conn = self._connect()
            try:
                rows = conn.execute(
                    f"SELECT {cols} FROM distill_chunks WHERE work_id=? ORDER BY chunk_index",
                    (work_id,),
                ).fetchall()
                return [dict(r) for r in rows]
            finally:
                conn.close()

    def get_chunk(self, chunk_id: int) -> dict | None:
        with self._lock:
            conn = self._connect()
            try:
                row = conn.execute(
                    "SELECT * FROM distill_chunks WHERE id=?", (chunk_id,)
                ).fetchone()
                return self._row_to_dict(row)
            finally:
                conn.close()

    def get_chunk_by_index(self, work_id: int, chunk_index: int) -> dict | None:
        with self._lock:
            conn = self._connect()
            try:
                row = conn.execute(
                    "SELECT * FROM distill_chunks WHERE work_id=? AND chunk_index=?",
                    (work_id, chunk_index),
                ).fetchone()
                return self._row_to_dict(row)
            finally:
                conn.close()

    def update_chunk_status(self, chunk_id: int, status: str) -> None:
        with self._lock:
            conn = self._connect()
            try:
                conn.execute(
                    "UPDATE distill_chunks SET status=? WHERE id=?", (status, chunk_id)
                )
                conn.commit()
            finally:
                conn.close()

    # ------------------------------------------------------------------
    # rounds
    # ------------------------------------------------------------------
    def create_round(self, chunk_id: int, round_num: int, prompt_used: str) -> int:
        with self._lock:
            conn = self._connect()
            try:
                cur = conn.execute(
                    "INSERT INTO distill_rounds (chunk_id, round_num, prompt_used, status, created_at)"
                    " VALUES (?, ?, ?, 'running', ?)",
                    (chunk_id, round_num, prompt_used, self._now()),
                )
                conn.commit()
                return int(cur.lastrowid)
            finally:
                conn.close()

    def complete_round(self, round_id: int, result_text: str,
                       skill_data_json: str, status: str = "done") -> None:
        with self._lock:
            conn = self._connect()
            try:
                conn.execute(
                    "UPDATE distill_rounds SET result_text=?, skill_data_json=?, status=? WHERE id=?",
                    (result_text, skill_data_json, status, round_id),
                )
                conn.commit()
            finally:
                conn.close()

    def get_round(self, chunk_id: int, round_num: int) -> dict | None:
        with self._lock:
            conn = self._connect()
            try:
                row = conn.execute(
                    "SELECT * FROM distill_rounds WHERE chunk_id=? AND round_num=?"
                    " ORDER BY id DESC LIMIT 1",
                    (chunk_id, round_num),
                ).fetchone()
                return self._row_to_dict(row)
            finally:
                conn.close()

    def list_rounds(self, chunk_id: int) -> list[dict]:
        with self._lock:
            conn = self._connect()
            try:
                rows = conn.execute(
                    "SELECT * FROM distill_rounds WHERE chunk_id=? ORDER BY round_num",
                    (chunk_id,),
                ).fetchall()
                return [dict(r) for r in rows]
            finally:
                conn.close()

    # ------------------------------------------------------------------
    # skills
    # ------------------------------------------------------------------
    def create_skill(self, work_id: int, work_title: str, chunk_index: int,
                     round_num: int, name: str, description: str,
                     content: str, tags: list[str] | None = None) -> int:
        with self._lock:
            conn = self._connect()
            try:
                cur = conn.execute(
                    "INSERT INTO distill_skills (work_id, work_title, chunk_index, round_num,"
                    " name, description, content, tags, status, created_at)"
                    " VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'active', ?)",
                    (work_id, work_title, chunk_index, round_num, name, description,
                     content, json.dumps(tags or [], ensure_ascii=False), self._now()),
                )
                conn.commit()
                return int(cur.lastrowid)
            finally:
                conn.close()

    def list_skills(self, work_id: int | None = None) -> list[dict]:
        with self._lock:
            conn = self._connect()
            try:
                if work_id is not None:
                    rows = conn.execute(
                        "SELECT * FROM distill_skills WHERE work_id=? ORDER BY id", (work_id,)
                    ).fetchall()
                else:
                    rows = conn.execute(
                        "SELECT * FROM distill_skills ORDER BY id DESC"
                    ).fetchall()
                return [dict(r) for r in rows]
            finally:
                conn.close()

    def get_skill(self, skill_id: int) -> dict | None:
        with self._lock:
            conn = self._connect()
            try:
                row = conn.execute(
                    "SELECT * FROM distill_skills WHERE id=?", (skill_id,)
                ).fetchone()
                return self._row_to_dict(row)
            finally:
                conn.close()

    def update_skill(self, skill_id: int, **fields: Any) -> None:
        allowed = {"name", "description", "content", "tags", "status"}
        updates = {k: v for k, v in fields.items() if k in allowed and v is not None}
        if not updates:
            return
        if "tags" in updates and isinstance(updates["tags"], list):
            updates["tags"] = json.dumps(updates["tags"], ensure_ascii=False)
        set_clause = ", ".join(f"{k}=?" for k in updates)
        with self._lock:
            conn = self._connect()
            try:
                conn.execute(
                    f"UPDATE distill_skills SET {set_clause} WHERE id=?",
                    (*updates.values(), skill_id),
                )
                conn.commit()
            finally:
                conn.close()

    def delete_skill(self, skill_id: int) -> bool:
        with self._lock:
            conn = self._connect()
            try:
                cur = conn.execute(
                    "DELETE FROM distill_skills WHERE id=?", (skill_id,)
                )
                conn.commit()
                return cur.rowcount > 0
            finally:
                conn.close()

    # ------------------------------------------------------------------
    # fusions
    # ------------------------------------------------------------------
    def create_fusion(self, name: str, skill_ids: list[int],
                      weights: list[float], description: str = "") -> int:
        with self._lock:
            conn = self._connect()
            try:
                cur = conn.execute(
                    "INSERT INTO distill_fusions (name, skill_ids_json, weights_json, description, status, created_at)"
                    " VALUES (?, ?, ?, ?, 'active', ?)",
                    (name, json.dumps(skill_ids), json.dumps(weights),
                     description, self._now()),
                )
                conn.commit()
                return int(cur.lastrowid)
            finally:
                conn.close()

    def list_fusions(self) -> list[dict]:
        with self._lock:
            conn = self._connect()
            try:
                rows = conn.execute(
                    "SELECT * FROM distill_fusions ORDER BY id DESC"
                ).fetchall()
                return [dict(r) for r in rows]
            finally:
                conn.close()

    def get_fusion(self, fusion_id: int) -> dict | None:
        with self._lock:
            conn = self._connect()
            try:
                row = conn.execute(
                    "SELECT * FROM distill_fusions WHERE id=?", (fusion_id,)
                ).fetchone()
                return self._row_to_dict(row)
            finally:
                conn.close()

    def delete_fusion(self, fusion_id: int) -> bool:
        with self._lock:
            conn = self._connect()
            try:
                cur = conn.execute(
                    "DELETE FROM distill_fusions WHERE id=?", (fusion_id,)
                )
                conn.commit()
                return cur.rowcount > 0
            finally:
                conn.close()

    def update_fusion_status(self, fusion_id: int, status: str,
                             skill_file: str = "") -> None:
        """融合任务状态更新：active（进行中）→ done / failed，附带产物文件名。"""
        with self._lock:
            conn = self._connect()
            try:
                if skill_file:
                    conn.execute(
                        "UPDATE distill_fusions SET status=?, skill_file=?, finished_at=? WHERE id=?",
                        (status, skill_file, self._now(), fusion_id),
                    )
                else:
                    conn.execute(
                        "UPDATE distill_fusions SET status=?, finished_at=? WHERE id=?",
                        (status, self._now(), fusion_id),
                    )
                conn.commit()
            finally:
                conn.close()

    # ------------------------------------------------------------------
    # progress
    # ------------------------------------------------------------------
    def progress(self, work_id: int) -> dict:
        """蒸馏进度统计：chunk/round/skill 计数 + 作品状态。"""
        with self._lock:
            conn = self._connect()
            try:
                total_chunks = conn.execute(
                    "SELECT COUNT(*) FROM distill_chunks WHERE work_id=?", (work_id,)
                ).fetchone()[0]
                done_chunks = conn.execute(
                    "SELECT COUNT(*) FROM distill_chunks WHERE work_id=? AND status='done'",
                    (work_id,),
                ).fetchone()[0]
                total_rounds = conn.execute(
                    "SELECT COUNT(*) FROM distill_rounds r JOIN distill_chunks c ON r.chunk_id=c.id"
                    " WHERE c.work_id=?", (work_id,),
                ).fetchone()[0]
                done_rounds = conn.execute(
                    "SELECT COUNT(*) FROM distill_rounds r JOIN distill_chunks c ON r.chunk_id=c.id"
                    " WHERE c.work_id=? AND r.status='done'", (work_id,),
                ).fetchone()[0]
                skills_count = conn.execute(
                    "SELECT COUNT(*) FROM distill_skills WHERE work_id=?", (work_id,)
                ).fetchone()[0]
                work = conn.execute(
                    "SELECT status FROM distill_works WHERE id=?", (work_id,)
                ).fetchone()
                return {
                    "work_id": work_id,
                    "status": work[0] if work else "not_found",
                    "total_chunks": total_chunks,
                    "done_chunks": done_chunks,
                    "total_rounds": total_rounds,
                    "done_rounds": done_rounds,
                    "skills_count": skills_count,
                }
            finally:
                conn.close()


_store: DistillationStore | None = None
_store_lock = threading.Lock()


def get_store() -> DistillationStore:
    """获取全局 DistillationStore 单例。"""
    global _store
    if _store is None:
        with _store_lock:
            if _store is None:
                _store = DistillationStore()
    return _store
