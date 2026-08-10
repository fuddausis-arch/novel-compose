"""圣经数据库 engine + session。

通过 Config 决定路径；测试用 NOVEL_TEST_DB=memory 切内存库。
启用 WAL 模式解决并发写入 "database is locked" 问题。
"""
from __future__ import annotations

import os
import uuid

from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker

from novel_agent.config import Config, load_config
from novel_agent.bible.models import migrate_db

_config: Config | None = None
_initialized: bool = False


def get_config() -> Config:
    global _config
    if _config is None:
        _config = load_config()
    return _config


def set_config(cfg: Config, force: bool = False) -> None:
    """测试/编排层注入配置用。force=True 时强制重绑（测试用）。"""
    global _config, engine, _initialized
    if _initialized and not force:
        return  # 已初始化，避免每请求重绑 engine + 并发 migrate_db
    _config = cfg
    _old_engine = engine if _initialized else None
    engine = _create_engine()
    migrate_db(engine)
    _initialized = True
    # 释放旧 engine 的连接池，避免资源泄漏
    if _old_engine is not None:
        _old_engine.dispose()


def _is_memory_url(url: str) -> bool:
    """判断是否为内存 SQLite URL（含普通内存库与 URI 共享内存库）。"""
    return ":memory:" in url or "mode=memory" in url


def _create_engine():
    """创建 engine，启用 WAL 模式 + 跨线程访问。"""
    url = _get_db_url()
    kwargs = {
        "echo": False,
        "future": True,
        "connect_args": {"check_same_thread": False},
    }
    eng = create_engine(url, **kwargs)
    # 对 SQLite 文件库启用 WAL 模式（内存库不需要）
    if not _is_memory_url(url):
        @event.listens_for(eng, "connect")
        def _set_wal(dbapi_conn, _):
            cursor = dbapi_conn.cursor()
            cursor.execute("PRAGMA journal_mode=WAL")
            cursor.execute("PRAGMA busy_timeout=5000")
            cursor.execute("PRAGMA foreign_keys=ON")  # 启用外键级联
            cursor.close()
    return eng


def _get_db_url() -> str:
    if os.getenv("NOVEL_TEST_DB") == "memory":
        # 使用 URI 共享内存库，使多个连接/线程访问同一内存数据，
        # 同时保留连接池的并发能力（优于 StaticPool 单连接）。
        return f"sqlite:///file:memdb_{uuid.uuid4().hex}?mode=memory&cache=shared&uri=true"
    cfg = get_config()
    db_path = cfg.bible_db_path
    db_path.parent.mkdir(parents=True, exist_ok=True)
    return f"sqlite:///{db_path}"


engine = _create_engine()


def SessionLocal():
    """返回绑定到当前 engine 的会话。

    使用函数而非模块级 sessionmaker，确保测试/编排层调用 set_config()
    重新绑定 engine 后，所有代码都能拿到新会话。
    """
    return sessionmaker(bind=engine, autoflush=False, future=True)()


migrate_db(engine)
