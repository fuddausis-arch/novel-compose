"""Planning API 功能测试：run/resume 用 mock VolumeRunner，detect 做静态校验。"""
from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest


def _create_assets(client, project_id: int):
    """创建角色、世界设定，供 detect 重复检测使用。"""
    client.post(
        f"/api/bible/{project_id}/characters",
        json={"name": "林动", "role": "主角"},
    )
    client.post(
        f"/api/bible/{project_id}/world-settings",
        json={"category": "世界观", "title": "大千世界", "content": "世界背景"},
    )


def test_detect_planning_issues(client, sample_project, sample_volume):
    """规划导入前检测应发现重复角色、重复世界设定、卷大纲覆盖与缺卷名。"""
    _create_assets(client, sample_project)

    result = {
        "settings": {
            "characters": [{"name": "林动"}],
            "world_settings": [{"category": "世界观", "title": "大千世界"}],
        },
        "volume_plan": {
            "volumes": [
                {"name": "第一卷"},  # order 1：与 sample_volume 重复 -> duplicate_volume_outline
                {"name": ""},        # order 2：缺卷名 -> missing_volume_name
            ]
        },
    }
    resp = client.post("/api/planning/detect", json={"project_id": sample_project, "result": result})
    assert resp.status_code == 200
    issues = resp.json()["issues"]
    types = {i["type"] for i in issues}

    assert "duplicate_character" in types
    assert "duplicate_world_setting" in types
    assert "duplicate_volume_outline" in types
    assert "missing_volume_name" in types


def test_run_planning_mock(client, sample_project):
    """卷级规划运行：mock VolumeRunner，不调用真实 LLM。"""
    fake_result = {"status": "outlined", "chapter_count": 3}
    fake_runner = type("FakeRunner", (), {})()
    fake_runner.run = AsyncMock(return_value=fake_result)
    fake_runner.aclose = AsyncMock()

    with patch("novel_agent.api.routes_planning.VolumeRunner", return_value=fake_runner):
        resp = client.post(
            "/api/planning/run",
            json={"project_id": sample_project, "volume": "第一卷", "chapter_count": 3, "thread_id": "t1"},
        )
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "outlined"
    assert data["thread_id"] == "t1"
    fake_runner.run.assert_awaited_once()
    fake_runner.aclose.assert_awaited_once()


def test_resume_planning_mock(client, sample_project):
    """人审①后恢复规划：mock VolumeRunner。"""
    fake_result = {"status": "approved"}
    fake_runner = type("FakeRunner", (), {})()
    fake_runner.resume = AsyncMock(return_value=fake_result)
    fake_runner.aclose = AsyncMock()

    with patch("novel_agent.api.routes_planning.VolumeRunner", return_value=fake_runner):
        resp = client.post(
            "/api/planning/resume",
            json={"project_id": sample_project, "thread_id": "t1", "approved": True, "edits": ""},
        )
    assert resp.status_code == 200
    assert resp.json()["status"] == "approved"
    fake_runner.resume.assert_awaited_once()
    fake_runner.aclose.assert_awaited_once()
