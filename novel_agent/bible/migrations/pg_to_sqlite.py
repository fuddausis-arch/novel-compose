"""PostgreSQL DDL → SQLite 迁移适配器。

bishu-novel 私有生产链路使用 PostgreSQL 迁移；公开版插件为纯文件方案。
本模块提供方言适配能力：当插件/扩展声明了 PostgreSQL DDL 迁移脚本时，
自动转换为 SQLite 兼容 DDL 并按序执行，保证同一套迁移资产可在
NovelAgent 的 SQLite 存储层上落地。

适配规则（pg → sqlite）：
- SERIAL / BIGSERIAL          → INTEGER（INTEGER PRIMARY KEY 自增由 SQLite 保证）
- JSONB / JSON                → TEXT（JSON 字符串存储，查询层 json.loads）
- TIMESTAMPTZ / TIMESTAMP     → DATETIME
- BOOLEAN                     → INTEGER（0/1）
- BYTEA                       → BLOB
- TEXT[] / 任何 T[]           → TEXT（JSON 数组字符串）
- NOW()                       → CURRENT_TIMESTAMP
- gen_random_uuid()           → (lower(hex(randomblob(16))))（应用层可再格式化）
- ON CONFLICT ... DO UPDATE   → 保留（SQLite 3.24+ 支持 UPSERT 子集）
- CREATE INDEX CONCURRENTLY   → CREATE INDEX（去掉 CONCURRENTLY）
- 移除 PostgreSQL 专属：USING gin/gist 索引方法、ALTER TYPE、COMMENT ON

执行策略：
- 每个迁移文件在独立事务中执行；失败回滚并记录。
- schema_migrations 表记录已应用的迁移，保证幂等。
"""
from __future__ import annotations

import logging
import re
import sqlite3
from pathlib import Path

logger = logging.getLogger(__name__)


class MigrationAdapterError(RuntimeError):
    """迁移适配/执行失败。"""


# ── 类型映射（长名在前，避免前缀误匹配）──────────────────────────
_TYPE_MAP: list[tuple[re.Pattern, str]] = [
    (re.compile(r"\bBIGSERIAL\b", re.IGNORECASE), "INTEGER"),
    (re.compile(r"\bSMALLSERIAL\b", re.IGNORECASE), "INTEGER"),
    (re.compile(r"\bSERIAL\b", re.IGNORECASE), "INTEGER"),
    (re.compile(r"\bJSONB\b", re.IGNORECASE), "TEXT"),
    (re.compile(r"\bTIMESTAMPTZ\b", re.IGNORECASE), "DATETIME"),
    (re.compile(r"\bTIMESTAMP\s+WITH\s+TIME\s+ZONE\b", re.IGNORECASE), "DATETIME"),
    (re.compile(r"\bTIMESTAMP\s+WITHOUT\s+TIME\s+ZONE\b", re.IGNORECASE), "DATETIME"),
    (re.compile(r"\bTIMESTAMP\b", re.IGNORECASE), "DATETIME"),
    (re.compile(r"\bBOOLEAN\b", re.IGNORECASE), "INTEGER"),
    (re.compile(r"\bBYTEA\b", re.IGNORECASE), "BLOB"),
    (re.compile(r"\bDOUBLE\s+PRECISION\b", re.IGNORECASE), "REAL"),
    (re.compile(r"\bUUID\b", re.IGNORECASE), "TEXT"),
]

# 数组类型：TEXT[] / INTEGER[] 等 → TEXT（JSON 字符串）
_ARRAY_RE = re.compile(r"\b([A-Za-z]+)\s*\[\s*\s*\]")

# PostgreSQL 专属语句（整行移除）
_UNSUPPORTED_STMT_RE = re.compile(
    r"^\s*(COMMENT\s+ON|ALTER\s+TYPE|CREATE\s+TYPE|CREATE\s+EXTENSION|SET\s+\w+\s*=)",
    re.IGNORECASE,
)

_NOW_RE = re.compile(r"\bNOW\s*\(\s*\)", re.IGNORECASE)
_UUID_GEN_RE = re.compile(r"\bgen_random_uuid\s*\(\s*\)", re.IGNORECASE)
_CONCURRENTLY_RE = re.compile(r"\bCONCURRENTLY\b", re.IGNORECASE)
_USING_METHOD_RE = re.compile(r"\bUSING\s+(gin|gist|brin|spgist)\b", re.IGNORECASE)
_TRUE_FALSE_RE = [
    (re.compile(r"\bTRUE\b", re.IGNORECASE), "1"),
    (re.compile(r"\bFALSE\b", re.IGNORECASE), "0"),
]


def adapt_pg_ddl_to_sqlite(sql: str) -> str:
    """把 PostgreSQL DDL 转换为 SQLite 兼容 DDL。

    Args:
        sql: PostgreSQL DDL 文本（可含多条语句）

    Returns:
        SQLite 兼容 SQL 文本

    Raises:
        MigrationAdapterError: 遇到无法安全转换的语句
    """
    # 移除 PostgreSQL 专属语句（按行过滤，避免多行 COMMENT ON 残留）
    kept_lines: list[str] = []
    for line in sql.splitlines():
        if _UNSUPPORTED_STMT_RE.match(line):
            logger.warning("跳过 PostgreSQL 专属语句: %s", line.strip()[:80])
            continue
        kept_lines.append(line)
    out = "\n".join(kept_lines)

    # 类型映射
    for pattern, repl in _TYPE_MAP:
        out = pattern.sub(repl, out)
    out = _ARRAY_RE.sub("TEXT", out)

    # 函数/关键字适配
    out = _NOW_RE.sub("CURRENT_TIMESTAMP", out)
    out = _UUID_GEN_RE.sub("(lower(hex(randomblob(16))))", out)
    out = _CONCURRENTLY_RE.sub("", out)
    out = _USING_METHOD_RE.sub("", out)
    for pattern, repl in _TRUE_FALSE_RE:
        out = pattern.sub(repl, out)

    return out


def _split_statements(sql: str) -> list[str]:
    """按分号切分语句（忽略空语句与纯注释段）。"""
    stmts: list[str] = []
    for raw in sql.split(";"):
        stmt = raw.strip()
        # 去掉纯注释行
        lines = [l for l in stmt.splitlines() if not l.strip().startswith("--")]
        stmt = "\n".join(lines).strip()
        if stmt:
            stmts.append(stmt)
    return stmts


def _ensure_migrations_table(conn: sqlite3.Connection) -> None:
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS schema_migrations (
            id INTEGER PRIMARY KEY,
            migration_name TEXT NOT NULL UNIQUE,
            applied_at DATETIME DEFAULT CURRENT_TIMESTAMP
        )
        """
    )


def applied_migrations(conn: sqlite3.Connection) -> set[str]:
    """查询已应用的迁移名集合。"""
    _ensure_migrations_table(conn)
    rows = conn.execute("SELECT migration_name FROM schema_migrations").fetchall()
    return {r[0] for r in rows}


def run_migration_sql(
    conn: sqlite3.Connection,
    migration_name: str,
    pg_sql: str,
) -> dict:
    """执行单个迁移：适配方言后在事务中执行，成功则登记 schema_migrations。

    幂等：已应用的迁移直接跳过。
    """
    done = applied_migrations(conn)
    if migration_name in done:
        logger.info("迁移 %s 已应用，跳过", migration_name)
        return {"status": "skipped", "migration": migration_name}

    sqlite_sql = adapt_pg_ddl_to_sqlite(pg_sql)
    statements = _split_statements(sqlite_sql)
    if not statements:
        logger.info("迁移 %s 适配后无可执行语句，登记为已应用", migration_name)
        _ensure_migrations_table(conn)
        conn.execute(
            "INSERT INTO schema_migrations (migration_name) VALUES (?)",
            (migration_name,),
        )
        conn.commit()
        return {"status": "applied", "migration": migration_name, "statements": 0}

    try:
        conn.execute("BEGIN")
        for stmt in statements:
            conn.execute(stmt)
        conn.execute(
            "INSERT INTO schema_migrations (migration_name) VALUES (?)",
            (migration_name,),
        )
        conn.commit()
    except sqlite3.Error as e:
        conn.rollback()
        raise MigrationAdapterError(
            f"迁移 {migration_name} 执行失败（已回滚）: {e}") from e

    logger.info("迁移 %s 已应用（%d 条语句）", migration_name, len(statements))
    return {"status": "applied", "migration": migration_name,
            "statements": len(statements)}


def run_migrations_dir(
    db_path: str | Path,
    migrations_dir: str | Path,
) -> dict:
    """按文件名排序执行目录下所有 .sql 迁移（幂等）。

    Args:
        db_path: SQLite 数据库文件路径
        migrations_dir: 迁移脚本目录（*.sql，按文件名排序执行）

    Returns:
        {"applied": [...], "skipped": [...], "failed": [...]}
    """
    migrations_dir = Path(migrations_dir)
    if not migrations_dir.is_dir():
        raise MigrationAdapterError(f"迁移目录不存在: {migrations_dir}")

    files = sorted(migrations_dir.glob("*.sql"))
    result: dict[str, list[str]] = {"applied": [], "skipped": [], "failed": []}

    conn = sqlite3.connect(str(db_path))
    try:
        for f in files:
            name = f.stem
            try:
                sql = f.read_text(encoding="utf-8")
                r = run_migration_sql(conn, name, sql)
                result["applied" if r["status"] == "applied" else "skipped"].append(name)
            except MigrationAdapterError as e:
                logger.error("%s", e)
                result["failed"].append(name)
    finally:
        conn.close()

    return result
