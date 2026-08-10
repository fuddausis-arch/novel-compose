"""生成 API 功能测试：默认 mock LLM，真实 LLM 测试标记 e2e。"""
from __future__ import annotations

import json

import pytest
from unittest.mock import patch

from tests.conftest import make_mock_llm_client


def _world_response() -> str:
    return json.dumps(
        {"world_settings": [{"category": "世界观", "title": "世界背景", "content": "这是一个玄幻世界。"}]},
        ensure_ascii=False,
    )


def _characters_response() -> str:
    return json.dumps(
        {
            "characters": [
                {
                    "name": "主角",
                    "role": "主角",
                    "age": "20",
                    "gender": "男",
                    "appearance": "英俊",
                    "background": "出身平凡",
                    "personality": "坚毅",
                    "motivation": "变强",
                    "arc": "成长",
                    "secrets": "无",
                }
            ]
        },
        ensure_ascii=False,
    )


def _volumes_response() -> str:
    return json.dumps(
        {
            "volumes": [
                {
                    "order": 1,
                    "title": "第一卷",
                    "summary": "卷一概要",
                    "act": "开端",
                    "key_events": [],
                    "foreshadow_plan": [],
                },
                {
                    "order": 2,
                    "title": "第二卷",
                    "summary": "卷二概要",
                    "act": "发展",
                    "key_events": [],
                    "foreshadow_plan": [],
                },
            ]
        },
        ensure_ascii=False,
    )


def test_generate_world_mock(client, sample_project):
    """世界观生成：mock LLM 返回固定 JSON。"""
    with patch("novel_agent.api.routes_generation.LLMClient") as MockLLM:
        MockLLM.return_value = make_mock_llm_client(_world_response())
        resp = client.post(
            "/api/generation/world/generate",
            json={"project_id": sample_project, "requirements": "测试"},
        )
    assert resp.status_code == 200
    data = resp.json()
    assert data["created"] >= 1
    assert len(data["items"]) >= 1


def test_generate_characters_mock(client, sample_project):
    """角色生成：mock LLM 返回固定 JSON。"""
    with patch("novel_agent.api.routes_generation.LLMClient") as MockLLM:
        MockLLM.return_value = make_mock_llm_client(_characters_response())
        resp = client.post(
            "/api/generation/characters/generate",
            json={"project_id": sample_project, "protagonist_count": 1},
        )
    assert resp.status_code == 200
    data = resp.json()
    assert data["created"] >= 1


def test_generate_volumes_mock(client, sample_project):
    """卷纲生成：mock LLM 返回固定 JSON，验证写入 2 条大纲。"""
    with patch("novel_agent.api.routes_generation.LLMClient") as MockLLM:
        MockLLM.return_value = make_mock_llm_client(_volumes_response())
        resp = client.post(
            "/api/generation/volumes/generate",
            json={"project_id": sample_project, "count": 2},
        )
    assert resp.status_code == 200
    data = resp.json()
    assert data["created"] == 2
    assert len(data["items"]) == 2


@pytest.mark.e2e
def test_generate_world_real_llm(client, sample_project, run_real_llm):
    """真实 LLM：世界观生成（默认不执行）。"""
    if not run_real_llm:
        pytest.skip("需要真实 LLM")
    resp = client.post(
        "/api/generation/world/generate",
        json={"project_id": sample_project, "requirements": "测试"},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["created"] > 0
    assert len(data["items"]) > 0


@pytest.mark.e2e
def test_generate_characters_real_llm(client, sample_project, run_real_llm):
    """真实 LLM：角色生成（默认不执行）。"""
    if not run_real_llm:
        pytest.skip("需要真实 LLM")
    resp = client.post(
        "/api/generation/characters/generate",
        json={"project_id": sample_project, "protagonist_count": 1},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["created"] > 0


@pytest.mark.e2e
def test_generate_volumes_real_llm(client, sample_project, run_real_llm):
    """真实 LLM：卷纲生成（默认不执行）。"""
    if not run_real_llm:
        pytest.skip("需要真实 LLM")
    resp = client.post(
        "/api/generation/volumes/generate",
        json={"project_id": sample_project, "count": 2},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert len(data["items"]) == 2
