"""测试生成 API：suggest / adopt 端点。"""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from novel_agent.api.app import create_app
from novel_agent.bible.database import SessionLocal
from novel_agent.bible.models import AiSuggestion
from novel_agent.config import Config


@pytest.fixture
def client(tmp_path, monkeypatch):
    data_dir = tmp_path / "project_data"
    data_dir.mkdir()
    cfg = Config(project_data_dir=data_dir)
    monkeypatch.setattr("novel_agent.api.routes_projects.load_config", lambda: cfg)
    monkeypatch.setattr("novel_agent.api.routes_generation.load_config", lambda: cfg)
    return TestClient(create_app(project_data_dir=data_dir))


async def _fake_generate_plot(*args, **kwargs):
    return '{"suggestions": [{"title": "下一章", "summary": "摘要", "payload": {"level": "chapter", "order": 2}}]}'


async def _fake_generate_monster(*args, **kwargs):
    return '{"suggestions": [{"title": "深渊魔狼", "summary": "来自深渊的狼群", "payload": {"species": "魔兽", "rank": "B", "tier": "精英", "habitats": "深渊"}}]}'


def test_suggest_plot_returns_structure(client, monkeypatch):
    monkeypatch.setattr("novel_agent.llm.client.LLMClient.generate", _fake_generate_plot)
    r = client.post("/api/projects", json={"title": "测试", "genre": "玄幻", "summary": "测"})
    pid = r.json()["id"]

    resp = client.post("/api/generation/suggest", json={
        "project_id": pid,
        "context_type": "outline",
        "context_id": "",
        "suggest_type": "plot",
        "count": 1,
    })
    assert resp.status_code == 200
    data = resp.json()
    assert len(data["suggestions"]) == 1
    assert data["suggestions"][0]["type"] == "plot"
    assert data["suggestions"][0]["title"] == "下一章"


def test_adopt_plot_creates_outline(client, monkeypatch):
    monkeypatch.setattr("novel_agent.llm.client.LLMClient.generate", _fake_generate_plot)
    pid = client.post("/api/projects", json={"title": "测试", "genre": "玄幻", "summary": "测"}).json()["id"]

    resp = client.post("/api/generation/suggest/adopt", json={
        "project_id": pid,
        "context_type": "outline",
        "context_id": "",
        "suggest_type": "plot",
        "prompt": "test",
        "raw_response": "test",
        "status": "adopted",
        "suggestions": [
            {"type": "plot", "title": "下一章", "summary": "摘要", "payload": {"level": "chapter", "order": 2}}
        ],
    })
    assert resp.status_code == 200
    data = resp.json()
    assert len(data["created"]["outlines"]) == 1
    assert data["created"]["monsters"] == []


def test_adopt_monster_creates_monster(client, monkeypatch):
    monkeypatch.setattr("novel_agent.llm.client.LLMClient.generate", _fake_generate_monster)
    pid = client.post("/api/projects", json={"title": "测试", "genre": "玄幻", "summary": "测"}).json()["id"]

    resp = client.post("/api/generation/suggest/adopt", json={
        "project_id": pid,
        "context_type": "monster",
        "context_id": "",
        "suggest_type": "monster",
        "prompt": "test",
        "raw_response": "test",
        "status": "adopted",
        "suggestions": [
            {
                "type": "monster",
                "title": "深渊魔狼",
                "summary": "来自深渊的狼群",
                "payload": {"species": "魔兽", "rank": "B", "tier": "精英", "habitats": "深渊"},
            }
        ],
    })
    assert resp.status_code == 200
    data = resp.json()
    assert len(data["created"]["monsters"]) == 1
    assert data["created"]["monsters"][0]["name"] == "深渊魔狼"
    assert data["created"]["outlines"] == []


def test_rejected_suggestion_records_history(client, monkeypatch):
    monkeypatch.setattr("novel_agent.llm.client.LLMClient.generate", _fake_generate_plot)
    pid = client.post("/api/projects", json={"title": "测试", "genre": "玄幻", "summary": "测"}).json()["id"]

    resp = client.post("/api/generation/suggest/adopt", json={
        "project_id": pid,
        "context_type": "outline",
        "context_id": "",
        "suggest_type": "plot",
        "prompt": "test prompt",
        "raw_response": "raw",
        "status": "rejected",
        "suggestions": [
            {"type": "plot", "title": "下一章", "summary": "摘要", "payload": {"level": "chapter", "order": 2}}
        ],
    })
    assert resp.status_code == 200
    data = resp.json()
    assert data["created"]["outlines"] == []

    db = SessionLocal()
    try:
        rows = db.query(AiSuggestion).filter(AiSuggestion.project_id == pid).all()
        assert len(rows) == 1
        assert rows[0].status == "rejected"
        assert len(rows[0].adopted_items) == 1
        assert rows[0].adopted_items[0]["title"] == "下一章"
    finally:
        db.close()
