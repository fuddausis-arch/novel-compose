"""测试 API：项目/规划/章节/圣经（mock LLM）。"""
import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from fastapi.testclient import TestClient
from novel_agent.api.app import create_app


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("NOVEL_PROJECT_DATA", str(tmp_path / "project_data"))
    (tmp_path / "project_data").mkdir()
    return TestClient(create_app(project_data_dir=tmp_path / "project_data"))


# ---- 项目 API ----

def test_create_project(client):
    resp = client.post("/api/projects", json={"title": "测试", "genre": "科幻", "summary": "末日"})
    assert resp.status_code == 200
    data = resp.json()
    assert data["title"] == "测试"
    assert data["id"] >= 1


def test_list_projects(client):
    client.post("/api/projects", json={"title": "p1"})
    client.post("/api/projects", json={"title": "p2"})
    resp = client.get("/api/projects")
    assert resp.status_code == 200
    assert len(resp.json()) >= 2


def test_get_project(client):
    r = client.post("/api/projects", json={"title": "x"}).json()
    resp = client.get(f"/api/projects/{r['id']}")
    assert resp.status_code == 200
    assert resp.json()["title"] == "x"


# ---- 圣经 API ----

def test_bible_characters(client):
    pid = client.post("/api/projects", json={"title": "x"}).json()["id"]
    # 直接建角色（绕过规划）
    from novel_agent.bible.database import SessionLocal, set_config
    from novel_agent.bible.models import Base, Character
    from novel_agent.config import load_config
    cfg = load_config(); set_config(cfg)
    from novel_agent.bible import database as db_mod
    Base.metadata.create_all(bind=db_mod.engine)
    db = SessionLocal()
    db.add(Character(project_id=pid, name="刘洋", role="主角"))
    db.commit(); db.close()
    resp = client.get(f"/api/bible/{pid}/characters")
    assert resp.status_code == 200
    assert any(c["name"] == "刘洋" for c in resp.json())


def test_bible_foreshadows_empty(client):
    pid = client.post("/api/projects", json={"title": "x"}).json()["id"]
    resp = client.get(f"/api/bible/{pid}/foreshadows")
    assert resp.status_code == 200
    assert resp.json() == []


# ---- 章节 API（mock LLM + auditor） ----

def test_generate_chapter(client):
    pid = client.post("/api/projects", json={"title": "x"}).json()["id"]
    from novel_agent.audit.schemas import AuditReport
    with patch("novel_agent.orchestrator.runner.LLMClient") as MockLLM, \
         patch("novel_agent.audit.auditor.LLMClient") as MockAuditLLM, \
         patch("novel_agent.audit.auditor.Auditor.audit",
               new=AsyncMock(return_value=AuditReport(passed=True, overall_score=85, summary="ok"))):
        mock = MagicMock()
        mock.generate = AsyncMock(side_effect=["草稿", "润色", '{"core_events":"e"}'])
        MockLLM.return_value = mock
        MockAuditLLM.return_value = MagicMock()
        resp = client.post("/api/chapters/generate", json={
            "project_id": pid, "chapter": 1, "title": "第一章"})
    assert resp.status_code == 200
    assert resp.json()["status"] == "completed"
