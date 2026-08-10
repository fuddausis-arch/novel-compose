"""性能与压力测试。"""
from __future__ import annotations

import asyncio
import time

import httpx
import pytest
from fastapi.testclient import TestClient
from httpx import ASGITransport
from unittest.mock import AsyncMock, patch

from novel_agent.api.app import create_app
from novel_agent.bible.database import set_config
from novel_agent.config import Config, LLMConfig, save_config


@pytest.fixture
def app(tmp_path, monkeypatch):
    """创建带临时数据目录的 App 实例（并发测试使用文件 SQLite + WAL）。"""
    project_data_dir = tmp_path / "project_data"
    project_data_dir.mkdir(parents=True, exist_ok=True)
    config_path = tmp_path / "test_config.yaml"

    # 覆盖 autouse fixture 的内存库设置，使用文件库以启用 WAL 模式
    monkeypatch.setenv("NOVEL_PROJECT_DATA_DIR", str(project_data_dir))
    monkeypatch.setenv("NOVEL_CONFIG_PATH", str(config_path))
    monkeypatch.delenv("NOVEL_TEST_DB", raising=False)

    cfg = Config(project_data_dir=project_data_dir, llm=LLMConfig(api_key=""))
    save_config(cfg, yaml_path=config_path)
    set_config(cfg, force=True)

    application = create_app(project_data_dir=project_data_dir)
    # 关闭限流器，避免压力测试触发 429
    application.state.limiter.enabled = False
    return application


@pytest.fixture
def client(app):
    """同步测试客户端。"""
    return TestClient(app)


@pytest.fixture
def sample_project(client):
    """创建一个用于测试的项目。"""
    resp = client.post("/api/projects", json={"title": "性能测试", "genre": "玄幻"})
    assert resp.status_code == 200
    return resp.json()["id"]


# ---- 8.1 并发项目创建 ----

@pytest.mark.asyncio
async def test_concurrent_project_creation(app):
    """20 个并发项目创建请求应全部成功。"""
    async with httpx.AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as async_client:
        # 先执行一次单请求，完成数据库初始化，避免并发 DDL 导致 SQLite 崩溃
        init_resp = await async_client.post(
            "/api/projects",
            json={"title": "初始化", "genre": "玄幻", "summary": "", "style": ""},
        )
        assert init_resp.status_code == 200

        tasks = [
            async_client.post(
                "/api/projects",
                json={"title": f"并发{i}", "genre": "玄幻", "summary": "", "style": ""},
            )
            for i in range(20)
        ]
        results = await asyncio.gather(*tasks)
    statuses = [r.status_code for r in results]
    assert all(s == 200 for s in statuses), f"存在非 200 状态码: {statuses}"


# ---- 8.2 大章节加载性能 ----

@pytest.mark.timeout(30)
def test_large_chapter_load(client, sample_project):
    """10 万字章节保存后读取应在 2 秒内完成。"""
    # 构造约 10 万汉字正文
    content = "正文" * 50000
    save_resp = client.put(
        "/api/chapters/1/text",
        params={"project_id": sample_project},
        json={"title": "大章节", "content": content},
    )
    assert save_resp.status_code == 200

    start = time.perf_counter()
    load_resp = client.get(
        "/api/chapters/1/text", params={"project_id": sample_project}
    )
    elapsed = time.perf_counter() - start

    assert load_resp.status_code == 200
    data = load_resp.json()
    assert len(data["text"]) >= 100000
    assert elapsed < 2.0, f"大章节加载耗时 {elapsed:.3f}s，超过 2s 阈值"


# ---- 8.3 生成接口超时与重试 ----

@pytest.mark.timeout(30)
def test_generation_timeout_retry(client, sample_project):
    """模拟 LLM 底层请求超时，验证接口返回 502 且不会崩溃。"""
    with patch("httpx.AsyncClient.post", new_callable=AsyncMock) as mock_post:
        mock_post.side_effect = httpx.TimeoutException("模拟超时")
        resp = client.post(
            "/api/generation/world/generate",
            json={"project_id": sample_project, "requirements": "测试"},
        )
        assert resp.status_code == 502
        # 生成接口统一走 _generate_json_with_repair（底层 max_retries=1，解析失败由 LLM 自修复兜底），
        # 故底层 HTTP 仅请求 1 次即失败，避免低层重试与自修复双重叠加导致慢速双倍重试。
        assert mock_post.call_count == 1
