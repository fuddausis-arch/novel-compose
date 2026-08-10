"""边界条件与异常场景测试。"""
from __future__ import annotations

import httpx
import pytest
from unittest.mock import AsyncMock, patch


# ---- 7.1 输入越界 ----

def test_invalid_project_id(client):
    """访问不存在的项目应返回 404。"""
    resp = client.get("/api/projects/99999999")
    assert resp.status_code == 404


def test_missing_required_field(client):
    """创建项目缺少 title 时应返回 422。"""
    resp = client.post("/api/projects", json={})
    assert resp.status_code == 422


# ---- 7.2 超长内容 ----

def test_overlong_summary(client):
    """超长简介应被接受或明确返回 422，不能崩溃。"""
    resp = client.post(
        "/api/projects",
        json={
            "title": "x" * 1000,
            "genre": "玄幻",
            "summary": "x" * 100000,
            "style": "轻松",
        },
    )
    assert resp.status_code in (200, 422)


# ---- 7.3 特殊字符与注入 ----

def test_special_characters(client):
    """标题包含 HTML/脚本标签时接口应正常返回，不应触发 XSS 过滤异常。"""
    payload = {
        "title": "<script>alert(1)</script>",
        "genre": "玄幻",
        "summary": "",
        "style": "",
    }
    resp = client.post("/api/projects", json=payload)
    assert resp.status_code == 200
    data = resp.json()
    # 当前实现不转义，只要内容正确保存即视为可用
    assert data["title"] == payload["title"] or "<script>" not in data["title"]


def test_sql_injection_like_title(client):
    """标题中包含 SQL 片段不应影响正常保存。"""
    title = "标题' OR '1'='1"
    resp = client.post("/api/projects", json={"title": title, "genre": "玄幻"})
    assert resp.status_code == 200
    assert resp.json()["title"] == title


# ---- 生成接口的边界 ----

def test_generate_world_missing_project(client):
    """生成接口访问不存在的项目应返回 404。"""
    resp = client.post("/api/generation/world/generate", json={"project_id": 99999999})
    assert resp.status_code == 404


def test_generate_world_missing_body(client):
    """生成接口缺少请求体应返回 422。"""
    resp = client.post("/api/generation/world/generate", json={})
    assert resp.status_code == 422


# ---- 7.4 LLM 异常返回 ----

def test_malformed_json_from_llm_returns_422(client, sample_project):
    """LLM 返回非 JSON 内容时，生成接口应返回 422 而非 500。"""
    with patch("novel_agent.llm.client.LLMClient.generate", new_callable=AsyncMock) as mock_generate:
        mock_generate.return_value = "这不是 JSON，只是普通说明文字。"
        resp = client.post(
            "/api/generation/world/generate",
            json={"project_id": sample_project, "requirements": "测试"},
        )
        assert resp.status_code == 422


def test_llm_timeout_returns_502(client, sample_project):
    """LLM 超时/网络异常时，生成接口应返回 502 且服务不崩溃。"""
    with patch("novel_agent.llm.client.LLMClient.generate", new_callable=AsyncMock) as mock_generate:
        mock_generate.side_effect = httpx.TimeoutException("请求超时")
        resp = client.post(
            "/api/generation/world/generate",
            json={"project_id": sample_project, "requirements": "测试"},
        )
        assert resp.status_code == 502
        # 再次请求应仍能正常响应（服务未崩溃）
        resp2 = client.get(f"/api/projects/{sample_project}")
        assert resp2.status_code == 200
