"""圣经数据库 engine + session。

通过 Config 决定路径；测试用 NOVEL_TEST_DB=memory 切内存库。
"""
from __future__ import annotations

import os

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from novel_agent.config import Config, load_config
from novel_agent.bible.models import migrate_db

_config: Config | None = None


def get_config() -> Config:
    global _config
    if _config is None:
        _config = load_config()
    return _config


def set_config(cfg: Config) -> None:
    """测试/编排层注入配置用。"""
    global _config, engine
    _config = cfg
    engine = create_engine(_get_db_url(), echo=False, future=True)
    migrate_db(engine)


def _get_db_url() -> str:
    if os.getenv("NOVEL_TEST_DB") == "memory":
        return "sqlite:///:memory:"
    cfg = get_config()
    db_path = cfg.bible_db_path
    db_path.parent.mkdir(parents=True, exist_ok=True)
    return f"sqlite:///{db_path}"


engine = create_engine(_get_db_url(), echo=False, future=True)


def SessionLocal():
    """返回绑定到当前 engine 的会话。

    使用函数而非模块级 sessionmaker，确保测试/编排层调用 set_config()
    重新绑定 engine 后，所有代码都能拿到新会话。
    """
    return sessionmaker(bind=engine, autoflush=False, future=True)()


migrate_db(engine)
