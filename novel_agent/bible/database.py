"""圣经数据库 engine + session。

测试用内存 SQLite，生产用文件 SQLite。通过环境变量切换。
"""
from __future__ import annotations

import os

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from novel_agent.models_stub import _PROJECT_DATA_DIR  # 见 Task 5 说明


def _get_db_url() -> str:
    """测试环境用内存库，否则用文件。"""
    if os.getenv("NOVEL_TEST_DB") == "memory":
        return "sqlite:///:memory:"
    db_path = _PROJECT_DATA_DIR() / "bible.db"
    db_path.parent.mkdir(parents=True, exist_ok=True)
    return f"sqlite:///{db_path}"


engine = create_engine(_get_db_url(), echo=False, future=True)
SessionLocal = sessionmaker(bind=engine, autoflush=False, future=True)
