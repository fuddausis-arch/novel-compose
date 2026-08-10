"""测试 commit_chapter 改走 DeltaApplier（数据流闭环）。"""
import json

import pytest
from fastapi.testclient import TestClient
from unittest.mock import AsyncMock, patch

from novel_agent.api.app import create_app
from novel_agent.memory.recall import RecallMemory
from novel_agent.protocol.applier import DeltaApplier


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("NOVEL_PROJECT_DATA", str(tmp_path / "project_data"))
    monkeypatch.setenv("NOVEL_CONFIG_PATH", str(tmp_path / "test_config.yaml"))
    (tmp_path / "project_data").mkdir()
    return TestClient(create_app(project_data_dir=tmp_path / "project_data"))


def test_commit_chapter_uses_applier(client):
    """commit_chapter 必须通过 DeltaApplier 统一应用变更。"""
    pid = client.post("/api/projects", json={
        "title": "applier 测试", "genre": "都市异能"
    }).json()["id"]
    client.post(f"/api/bible/{pid}/outlines", json={
        "level": "chapter", "order": 1, "title": "第一章", "summary": "测试大纲"
    })

    raw_response = json.dumps({
        "summary": "刘洋出门，遇到林夏。",
        "state_deltas": [
            {"entity_type": "角色", "entity_id": "刘洋",
             "field": "current_location", "old": "家", "new": "公司"}
        ],
        "relationships": [
            {"character_a": "刘洋", "character_b": "林夏", "interaction_type": "meeting"}
        ],
        "events": [
            {"event_type": "character_state_changed", "subject": "刘洋", "payload": {"desc": "出门"}}
        ],
        "foreshadow_updates": [
            {"foreshadow_id": "S-001", "status": "planted"}
        ],
    }, ensure_ascii=False)

    captured = []

    def fake_apply(self, deltas, chapter):
        captured.extend(deltas)

    with patch("novel_agent.api.routes_generation.LLMClient") as MockLLM, \
         patch.object(RecallMemory, "read_chapter_text", return_value="正文正文。"), \
         patch.object(DeltaApplier, "apply_deltas", fake_apply):
        mock = MockLLM.return_value
        mock.generate = AsyncMock(return_value=raw_response)
        mock.close = AsyncMock()
        resp = client.post("/api/generation/chapter/commit", json={
            "project_id": pid, "chapter": 1
        })

    assert resp.status_code == 200
    types = {d["type"] for d in captured}
    assert "state_change" in types
    assert "relationship_update" in types
    assert "event" in types
    assert "foreshadow_update" in types
    assert "chapter_commit" in types
