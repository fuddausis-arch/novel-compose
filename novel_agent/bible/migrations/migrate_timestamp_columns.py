"""迁移脚本：将 Bible 库中 5 张表的时间戳列从 String 统一为 DateTime。

涉及的表：
    - factions
    - faction_relationships
    - character_relationships
    - monsters
    - entity_appearances

迁移策略：
    1. 检查目标列当前类型；若已是 DateTime/DATETIME 则跳过（幂等）。
    2. DROP 前用 PRAGMA 收集原表的外键（foreign_key_list）与索引（index_list/index_info）。
    3. 创建临时表，结构与目标表一致，但时间戳列为 DATETIME，并把外键写进 CREATE TABLE。
    4. 将旧表数据拷贝到临时表，期间把字符串 ISO 时间解析为 datetime。
    5. 删除旧表，重命名临时表。
    6. 按 PRAGMA 收集的定义重建索引（含唯一索引），UNIQUE_CONSTRAINTS 仅作兜底。

取舍说明：
    - 外键：SQLite 不支持 ALTER TABLE ADD CONSTRAINT / ADD FOREIGN KEY，
      因此外键在重建临时表时直接写进 CREATE TABLE（此时 PRAGMA foreign_keys=OFF，
      不会对拷入数据做校验）。
    - AUTOINCREMENT 关键字不恢复：INTEGER PRIMARY KEY 已保证自增，
      AUTOINCREMENT 仅影响 rowid 重用策略，对本项目无影响。

该脚本可直接运行，也可被 database.migrate_db 在启动时调用。
"""
from __future__ import annotations

import logging
import sqlite3
from datetime import datetime
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

# 需要迁移的 (表名, [列名]) 列表
MIGRATION_TABLES: list[tuple[str, list[str]]] = [
    ("factions", ["created_at", "updated_at"]),
    ("faction_relationships", ["created_at", "updated_at"]),
    ("character_relationships", ["created_at", "updated_at"]),
    ("monsters", ["created_at", "updated_at"]),
    ("entity_appearances", ["created_at", "updated_at"]),
]

# 各表需要重建的索引/约束（除主键、外键外，业务依赖的唯一约束）
UNIQUE_CONSTRAINTS: dict[str, list[str]] = {
    "factions": ["CREATE UNIQUE INDEX uix_project_faction_name ON factions(project_id, name)"],
    "character_relationships": [
        "CREATE UNIQUE INDEX uix_project_char_rel ON character_relationships(project_id, source_character, target_character, relation_type)"
    ],
    "monsters": ["CREATE UNIQUE INDEX uix_project_monster_name ON monsters(project_id, name)"],
    "entity_appearances": [
        "CREATE UNIQUE INDEX uix_entity_appearance ON entity_appearances(project_id, entity_type, entity_id, chapter)"
    ],
}


def _parse_iso_timestamp(value: Any) -> str:
    """把可能是字符串的 ISO 时间解析为 SQLite 可接受的 DATETIME 字符串。

    若解析失败或为空，则返回当前 UTC 时间，避免 NULL 污染。
    """
    if value is None or value == "":
        return datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S")
    if isinstance(value, datetime):
        return value.strftime("%Y-%m-%d %H:%M:%S")
    if isinstance(value, str):
        value = value.strip()
        if not value:
            return datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S")
        # 尝试多种常见 ISO 格式
        formats = [
            "%Y-%m-%dT%H:%M:%S.%f",
            "%Y-%m-%dT%H:%M:%S",
            "%Y-%m-%d %H:%M:%S.%f",
            "%Y-%m-%d %H:%M:%S",
        ]
        for fmt in formats:
            try:
                dt = datetime.strptime(value, fmt)
                return dt.strftime("%Y-%m-%d %H:%M:%S")
            except ValueError:
                continue
        # 兜底：去掉时区信息后再次尝试
        if "+" in value:
            value = value.split("+")[0]
            for fmt in formats:
                try:
                    dt = datetime.strptime(value, fmt)
                    return dt.strftime("%Y-%m-%d %H:%M:%S")
                except ValueError:
                    continue
    logger.warning("无法解析时间戳 %r，使用当前 UTC 时间兜底", value)
    return datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S")


def _column_type(conn: sqlite3.Connection, table: str, column: str) -> str:
    """返回表中某列的声明类型（大写）。"""
    cur = conn.execute(f"PRAGMA table_info({table})")
    for row in cur.fetchall():
        if row[1] == column:
            return (row[2] or "").upper()
    return ""


def _is_datetime_type(conn: sqlite3.Connection, table: str, column: str) -> bool:
    """判断列是否已经是 DATETIME 类型。"""
    col_type = _column_type(conn, table, column)
    return col_type in ("DATETIME", "TIMESTAMP", "DATE")


def _table_columns(conn: sqlite3.Connection, table: str) -> list[tuple[str, str, int, Any, int]]:
    """返回表的列信息元组 (name, type, notnull, dflt_value, pk)。"""
    cur = conn.execute(f"PRAGMA table_info({table})")
    return [(row[1], row[2], row[3], row[4], row[5]) for row in cur.fetchall()]


def _foreign_keys(conn: sqlite3.Connection, table: str) -> list[dict]:
    """返回表的外键定义（必须在 DROP 前收集，重建表时恢复）。

    PRAGMA foreign_key_list 行格式：(id, seq, table, from, to, on_update, on_delete, match)
    """
    fks: list[dict] = []
    for row in conn.execute(f"PRAGMA foreign_key_list({table})").fetchall():
        fks.append({
            "table": row[2],
            "from": row[3],
            "to": row[4],
            "on_update": row[5],
            "on_delete": row[6],
        })
    return fks


def _table_indexes(conn: sqlite3.Connection, table: str) -> list[dict]:
    """返回表的非主键索引信息（必须在 DROP 前收集，重建后按原样恢复）。

    PRAGMA index_list 行格式：(seq, name, unique, origin, partial)
    PRAGMA index_info 行格式：(seqno, cid, name[, desc])
    origin: 'c'=CREATE INDEX / 'u'=UNIQUE 约束 / 'pk'=主键（跳过）
    """
    indexes: list[dict] = []
    for row in conn.execute(f"PRAGMA index_list({table})").fetchall():
        name, unique, origin = row[1], bool(row[2]), row[3]
        if origin == "pk":
            continue
        cols = [r[2] for r in conn.execute(f"PRAGMA index_info({name})").fetchall()]
        indexes.append({"name": name, "unique": unique, "columns": cols})
    return indexes


def _index_name_from_sql(sql: str) -> str:
    """从 'CREATE [UNIQUE] INDEX <name> ON ...' 中提取索引名，用于跳过已恢复的索引。"""
    parts = sql.split()
    if len(parts) >= 4 and parts[0] == "CREATE" and parts[2] == "INDEX":
        return parts[3]
    return ""


def migrate_table(conn: sqlite3.Connection, table: str, columns: list[str]) -> bool:
    """迁移单张表的时间戳列。返回是否执行了迁移。"""
    if not _table_exists(conn, table):
        logger.info("表 %s 不存在，跳过", table)
        return False

    # 幂等检查：若所有目标列已是 DATETIME，则跳过
    if all(_is_datetime_type(conn, table, col) for col in columns):
        logger.info("表 %s 时间戳列已是 DATETIME，跳过", table)
        return False

    logger.info("开始迁移表 %s 的时间戳列", table)

    # DROP 前收集原表的外键与索引，重建后按原样恢复
    fk_defs: list[str] = []
    for fk in _foreign_keys(conn, table):
        fk_sql = f'FOREIGN KEY("{fk["from"]}") REFERENCES "{fk["table"]}" ("{fk["to"]}")'
        if fk["on_update"] and fk["on_update"] != "NO ACTION":
            fk_sql += f" ON UPDATE {fk['on_update']}"
        if fk["on_delete"] and fk["on_delete"] != "NO ACTION":
            fk_sql += f" ON DELETE {fk['on_delete']}"
        fk_defs.append(fk_sql)
    indexes = _table_indexes(conn, table)

    cols = _table_columns(conn, table)
    col_defs: list[str] = []
    col_names: list[str] = []
    for name, ctype, notnull, dflt, pk in cols:
        col_names.append(name)
        if name in columns:
            ctype = "DATETIME"
            dflt = None  # 去掉旧默认值，由应用层生成 datetime.utcnow()
        parts = [f'"{name}"', ctype]
        if notnull:
            parts.append("NOT NULL")
        if pk:
            parts.append("PRIMARY KEY")
        if dflt is not None:
            parts.append(f"DEFAULT {dflt}")
        col_defs.append(" ".join(parts))

    # 1. 创建临时表（外键定义写进 CREATE TABLE）
    temp_table = f"{table}_temp"
    _drop_table_if_exists(conn, temp_table)
    create_sql = f"CREATE TABLE {temp_table} ({', '.join(col_defs + fk_defs)})"
    conn.execute(create_sql)

    # 2. 拷贝数据并转换时间戳
    select_cols = ", ".join(f'"{c}"' for c in col_names)
    cur = conn.execute(f"SELECT {select_cols} FROM {table}")
    rows = cur.fetchall()
    insert_cols = ", ".join(f'"{c}"' for c in col_names)
    placeholders = ", ".join(["?"] * len(col_names))
    insert_sql = f"INSERT INTO {temp_table} ({insert_cols}) VALUES ({placeholders})"

    converted_rows: list[list[Any]] = []
    for row in rows:
        new_row = list(row)
        for col in columns:
            idx = col_names.index(col)
            new_row[idx] = _parse_iso_timestamp(row[idx])
        converted_rows.append(new_row)

    if converted_rows:
        conn.executemany(insert_sql, converted_rows)

    # 3. 删除旧表并重命名临时表
    conn.execute(f"DROP TABLE {table}")
    conn.execute(f"ALTER TABLE {temp_table} RENAME TO {table}")

    # 4. 按 PRAGMA 收集的定义重建索引（含唯一索引），UNIQUE_CONSTRAINTS 仅作兜底
    restored_names: set[str] = set()
    for idx in indexes:
        idx_cols = ", ".join(f'"{c}"' for c in idx["columns"])
        if idx["unique"]:
            idx_sql = f'CREATE UNIQUE INDEX "{idx["name"]}" ON {table} ({idx_cols})'
        else:
            idx_sql = f'CREATE INDEX "{idx["name"]}" ON {table} ({idx_cols})'
        try:
            conn.execute(idx_sql)
            restored_names.add(idx["name"])
        except Exception as exc:
            logger.warning("重建索引失败 %s: %s", idx_sql, exc)
    for idx_sql in UNIQUE_CONSTRAINTS.get(table, []):
        if _index_name_from_sql(idx_sql) in restored_names:
            continue
        try:
            conn.execute(idx_sql)
        except Exception as exc:
            logger.warning("重建索引失败 %s: %s", idx_sql, exc)

    logger.info("表 %s 迁移完成，共迁移 %d 条记录", table, len(converted_rows))
    return True


def _table_exists(conn: sqlite3.Connection, table: str) -> bool:
    cur = conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (table,)
    )
    return cur.fetchone() is not None


def _drop_table_if_exists(conn: sqlite3.Connection, table: str) -> None:
    conn.execute(f"DROP TABLE IF EXISTS {table}")


def migrate(db_path: Path | str) -> list[str]:
    """执行时间戳列迁移。返回实际迁移的表名列表。"""
    migrated: list[str] = []
    conn = sqlite3.connect(str(db_path))
    try:
        conn.execute("PRAGMA foreign_keys=OFF")
        for table, columns in MIGRATION_TABLES:
            try:
                if migrate_table(conn, table, columns):
                    migrated.append(table)
            except Exception as exc:
                logger.error("迁移表 %s 失败: %s", table, exc)
                conn.rollback()
                raise
        conn.execute("PRAGMA foreign_keys=ON")
        conn.commit()
    finally:
        conn.close()
    return migrated


def migrate_with_engine(engine) -> list[str]:
    """基于已存在的 SQLAlchemy engine 执行迁移（database.migrate_db 调用用）。"""
    from sqlalchemy import text
    from sqlalchemy.orm import sessionmaker

    db_url = str(engine.url)
    if db_url.startswith("sqlite:///"):
        db_path = db_url.replace("sqlite:///", "")
        return migrate(db_path)

    # 非 SQLite 情况：使用通用 ALTER COLUMN 逻辑（本项目实际只用 SQLite）
    Session = sessionmaker(bind=engine)
    session = Session()
    migrated: list[str] = []
    try:
        for table, columns in MIGRATION_TABLES:
            for col in columns:
                try:
                    session.execute(
                        text(f"ALTER TABLE {table} ALTER COLUMN {col} TYPE DATETIME")
                    )
                    migrated.append(f"{table}.{col}")
                except Exception as exc:
                    logger.warning("非 SQLite 迁移跳过 %s.%s: %s", table, col, exc)
        session.commit()
    finally:
        session.close()
    return migrated


if __name__ == "__main__":
    import sys

    logging.basicConfig(level=logging.INFO)

    if len(sys.argv) > 1:
        target_path = Path(sys.argv[1])
    else:
        from novel_agent.config import load_config

        cfg = load_config()
        target_path = cfg.bible_db_path

    if not target_path.exists():
        logger.error("数据库文件不存在: %s", target_path)
        sys.exit(1)

    migrated_tables = migrate(target_path)
    print(f"迁移完成，共迁移 {len(migrated_tables)} 张表: {migrated_tables}")
