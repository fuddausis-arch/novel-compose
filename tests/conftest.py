"""pytest 共享 fixtures。"""
from __future__ import annotations

from pathlib import Path

import pytest

from novel_agent.config import Config


@pytest.fixture(autouse=True)
def _reset_db_global_state():
    """每个测试前重置全局 DB 状态，防止 set_config(force=True) 跨测试污染。

    部分测试调用 set_config(cfg, force=True) 会设置全局 _initialized=True，
    导致后续测试的 set_config(tmp_config)（无 force）变成 no-op，engine 不重绑，
    引发 "no such table" 等错误。这里在每测试前重置 _initialized/_config/engine，
    确保每个测试都从干净状态开始。测试自己的 fixture 会随后按需重绑 engine。
    """
    from novel_agent.bible import database as db_mod
    db_mod._initialized = False
    db_mod._config = None
    try:
        db_mod.engine = db_mod._create_engine()
        db_mod.migrate_db(db_mod.engine)
    except Exception:
        pass
    yield


@pytest.fixture
def tmp_config(tmp_path: Path) -> Config:
    """临时项目数据目录的配置。"""
    return Config(project_data_dir=tmp_path / "project_data")
