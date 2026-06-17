"""圣经数据库 engine + session。

通过 Config 决定路径；测试用 NOVEL_TEST_DB=memory 切内存库。
"""
from __future__ import annotations

import os

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from novel_agent.config import Config, load_config

_config: Config | None = None


def get_config() -> Config:
    global _config
    if _config is None:
        _config = load_config()
    return _config


def set_config(cfg: Config) -> None:
    """测试/编排层注入配置用。"""
    global _config, engine, SessionLocal
    _config = cfg
    engine = create_engine(_get_db_url(), echo=False, future=True)
    SessionLocal = sessionmaker(bind=engine, autoflush=False, future=True)


def _get_db_url() -> str:
    if os.getenv("NOVEL_TEST_DB") == "memory":
        return "sqlite:///:memory:"
    cfg = get_config()
    db_path = cfg.bible_db_path
    db_path.parent.mkdir(parents=True, exist_ok=True)
    return f"sqlite:///{db_path}"


engine = create_engine(_get_db_url(), echo=False, future=True)
SessionLocal = sessionmaker(bind=engine, autoflush=False, future=True)
