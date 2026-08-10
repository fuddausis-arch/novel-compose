"""pytest 共享 fixtures。"""
from __future__ import annotations

import json
import os
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from novel_agent.api.app import create_app
from novel_agent.config import Config, LLMConfig, load_config, save_config


@pytest.fixture(autouse=True)
def _reset_db_global_state(monkeypatch):
    """每个测试前重置全局 DB 状态，防止 set_config(force=True) 跨测试污染。

    部分测试调用 set_config(cfg, force=True) 会设置全局 _initialized=True，
    导致后续测试的 set_config(tmp_config)（无 force）变成 no-op，engine 不重绑，
    引发 "no such table" 等错误。这里在每测试前重置 _initialized/_config/engine，
    确保每个测试都从干净状态开始。测试自己的 fixture 会随后按需重绑 engine。

    同时默认使用内存 SQLite，避免测试在真实文件库中落盘。
    """
    monkeypatch.setenv("NOVEL_TEST_DB", "memory")
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


@pytest.fixture
def client(tmp_path: Path, monkeypatch) -> TestClient:
    """FastAPI TestClient：使用内存 SQLite + 临时项目目录，禁用限流器。"""
    project_data_dir = tmp_path / "project_data"
    project_data_dir.mkdir(parents=True, exist_ok=True)
    config_path = tmp_path / "test_config.yaml"

    monkeypatch.setenv("NOVEL_TEST_DB", "memory")
    monkeypatch.setenv("NOVEL_PROJECT_DATA_DIR", str(project_data_dir))
    monkeypatch.setenv("NOVEL_CONFIG_PATH", str(config_path))

    cfg = Config(project_data_dir=project_data_dir, llm=LLMConfig(api_key=""))
    save_config(cfg, yaml_path=config_path)

    # 强制绑定到内存引擎，确保路由里的 set_config 使用同一内存库
    from novel_agent.bible.database import set_config
    set_config(cfg, force=True)

    app = create_app(project_data_dir=project_data_dir)
    app.state.limiter.enabled = False
    return TestClient(app)


@pytest.fixture
def sample_project(client: TestClient) -> int:
    """创建一个示例项目并返回项目 ID。"""
    resp = client.post(
        "/api/projects",
        json={"title": "测试小说", "genre": "玄幻", "summary": "简介", "style": "轻松"},
    )
    assert resp.status_code == 200
    return resp.json()["id"]


@pytest.fixture
def sample_volume(client: TestClient, sample_project: int) -> int:
    """为示例项目创建一个卷级大纲并返回其 ID。"""
    resp = client.post(
        f"/api/bible/{sample_project}/outlines",
        json={"level": "volume", "order": 1, "title": "第一卷", "summary": "卷级概要"},
    )
    assert resp.status_code == 200
    return resp.json()["id"]


@pytest.fixture
def sample_chapter(client: TestClient, sample_project: int) -> int:
    """为示例项目创建第 1 章大纲与正文，返回章节号。"""
    resp = client.post(
        f"/api/bible/{sample_project}/outlines",
        json={"level": "chapter", "order": 1, "title": "第一章", "summary": "章级概要"},
    )
    assert resp.status_code == 200

    resp = client.put(
        f"/api/chapters/1/text?project_id={sample_project}",
        json={"title": "第一章", "content": "这是第一章正文内容。"},
    )
    assert resp.status_code == 200
    return 1


@pytest.fixture
def run_real_llm() -> bool:
    """是否执行真实 LLM 测试，由环境变量 NOVEL_RUN_REAL_LLM_TESTS 控制。"""
    return os.getenv("NOVEL_RUN_REAL_LLM_TESTS", "0") == "1"


def make_mock_llm_client(response_text: str) -> MagicMock:
    """构造一个返回固定文本的 mock LLMClient。"""
    mock_client = MagicMock()
    mock_client.generate = AsyncMock(return_value=response_text)
    mock_client.close = AsyncMock()
    return mock_client
