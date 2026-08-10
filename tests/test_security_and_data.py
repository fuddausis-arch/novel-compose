"""数据安全与隐私测试。"""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from novel_agent.api.app import create_app


@pytest.fixture
def client(tmp_path, monkeypatch):
    """创建使用独立临时配置文件的测试客户端。"""
    monkeypatch.setenv("NOVEL_PROJECT_DATA_DIR", str(tmp_path / "project_data"))
    monkeypatch.setenv("NOVEL_CONFIG_PATH", str(tmp_path / "test_config.yaml"))
    (tmp_path / "project_data").mkdir(parents=True, exist_ok=True)
    app = create_app(project_data_dir=tmp_path / "project_data")
    app.state.limiter.enabled = False
    return TestClient(app)


@pytest.fixture
def client_with_secret(tmp_path, monkeypatch):
    """使用包含真实 API Key 的配置文件创建客户端。"""
    monkeypatch.setenv("NOVEL_PROJECT_DATA_DIR", str(tmp_path / "project_data"))
    config_path = tmp_path / "test_config.yaml"
    monkeypatch.setenv("NOVEL_CONFIG_PATH", str(config_path))
    secret_key = "sk-1234567890abcdef"
    config_path.write_text(
        f"llm:\n  api_key: {secret_key}\n  model: gpt-4o-mini\n",
        encoding="utf-8",
    )
    (tmp_path / "project_data").mkdir(parents=True, exist_ok=True)
    app = create_app(project_data_dir=tmp_path / "project_data")
    app.state.limiter.enabled = False
    return TestClient(app), secret_key


@pytest.fixture
def project_a(client):
    """项目 A。"""
    resp = client.post("/api/projects", json={"title": "项目A", "genre": "玄幻"})
    assert resp.status_code == 200
    return resp.json()["id"]


@pytest.fixture
def project_b(client):
    """项目 B。"""
    resp = client.post("/api/projects", json={"title": "项目B", "genre": "科幻"})
    assert resp.status_code == 200
    return resp.json()["id"]


# ---- 9.1 API Key 不泄露 ----

def test_config_api_key_not_exposed(client_with_secret):
    """配置接口返回的 LLM API Key 必须是脱敏后的，不能泄露完整密钥。"""
    client, secret_key = client_with_secret
    resp = client.get("/api/config/llm")
    assert resp.status_code == 200
    body = resp.text
    assert secret_key not in body, "完整 API Key 出现在响应中"
    data = resp.json()
    assert data["api_key"].endswith("****"), "API Key 未正确脱敏"


def test_agent_llm_config_masks_key(client_with_secret):
    """agent-llm 列表接口同样不能泄露完整 API Key。"""
    client, secret_key = client_with_secret
    resp = client.get("/api/config/agent-llm")
    assert resp.status_code == 200
    assert secret_key not in resp.text, "完整 API Key 出现在 agent-llm 响应中"


# ---- 9.2 跨项目数据隔离 ----

def test_project_data_isolation(client, project_a, project_b):
    """项目 A 的章节不应出现在项目 B 的章节列表中。"""
    # 仅在项目 A 下保存章节正文
    save_resp = client.put(
        "/api/chapters/1/text",
        params={"project_id": project_a},
        json={"title": "A 的章节", "content": "项目 A 的内容"},
    )
    assert save_resp.status_code == 200

    resp_a = client.get("/api/chapters/list", params={"project_id": project_a})
    resp_b = client.get("/api/chapters/list", params={"project_id": project_b})

    assert resp_a.status_code == 200
    assert resp_b.status_code == 200
    list_a = resp_a.json()
    list_b = resp_b.json()

    assert list_a != list_b, "跨项目章节列表未隔离"
    assert len(list_b) == 0, "项目 B 不应看到项目 A 的章节"
    assert len(list_a) == 1
    assert list_a[0]["title"] == "A 的章节"


# ---- 9.3 SQL 注入防护 ----

def test_sql_injection_attempt(client):
    """对整数型路径参数传入 SQL 片段应被 FastAPI 校验拒绝。"""
    resp = client.get("/api/projects/1' OR '1'='1")
    assert resp.status_code == 422
