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


def test_bible_factions(client):
    pid = client.post("/api/projects", json={"title": "x"}).json()["id"]
    assert client.get(f"/api/bible/{pid}/factions").json() == []
    r = client.post(f"/api/bible/{pid}/factions", json={"name": "光明教会", "type": "宗教"})
    assert r.status_code == 200
    fid = r.json()["id"]
    assert client.get(f"/api/bible/{pid}/factions").json()[0]["name"] == "光明教会"
    r = client.put(f"/api/bible/{pid}/factions/{fid}", json={"name": "光明教会", "type": "神殿"})
    assert r.status_code == 200
    assert r.json()["type"] == "神殿"
    assert client.delete(f"/api/bible/{pid}/factions/{fid}").status_code == 200
    assert client.get(f"/api/bible/{pid}/factions").json() == []


def test_bible_faction_relationships(client):
    pid = client.post("/api/projects", json={"title": "x"}).json()["id"]
    f1 = client.post(f"/api/bible/{pid}/factions", json={"name": "A"}).json()["id"]
    f2 = client.post(f"/api/bible/{pid}/factions", json={"name": "B"}).json()["id"]
    assert client.get(f"/api/bible/{pid}/faction-relationships").json() == []
    r = client.post(f"/api/bible/{pid}/faction-relationships",
                    json={"source_faction_id": f1, "target_faction_id": f2, "relation_type": "敌对"})
    assert r.status_code == 200
    rid = r.json()["id"]
    assert client.get(f"/api/bible/{pid}/faction-relationships").json()[0]["relation_type"] == "敌对"
    r = client.put(f"/api/bible/{pid}/faction-relationships/{rid}",
                   json={"source_faction_id": f1, "target_faction_id": f2, "relation_type": "同盟"})
    assert r.status_code == 200
    assert r.json()["relation_type"] == "同盟"
    assert client.delete(f"/api/bible/{pid}/faction-relationships/{rid}").status_code == 200
    assert client.get(f"/api/bible/{pid}/faction-relationships").json() == []


def test_bible_character_relationships(client):
    pid = client.post("/api/projects", json={"title": "x"}).json()["id"]
    assert client.get(f"/api/bible/{pid}/character-relationships").json() == []
    r = client.post(f"/api/bible/{pid}/character-relationships",
                    json={"source_character": "刘洋", "target_character": "林夏", "relation_type": "合作"})
    assert r.status_code == 200
    rid = r.json()["id"]
    assert client.get(f"/api/bible/{pid}/character-relationships").json()[0]["target_character"] == "林夏"
    r = client.put(f"/api/bible/{pid}/character-relationships/{rid}",
                   json={"source_character": "刘洋", "target_character": "林夏", "relation_type": "挚友"})
    assert r.status_code == 200
    assert r.json()["relation_type"] == "挚友"
    assert client.delete(f"/api/bible/{pid}/character-relationships/{rid}").status_code == 200
    assert client.get(f"/api/bible/{pid}/character-relationships").json() == []


def test_bible_monsters(client):
    pid = client.post("/api/projects", json={"title": "x"}).json()["id"]
    assert client.get(f"/api/bible/{pid}/monsters").json() == []
    r = client.post(f"/api/bible/{pid}/monsters", json={"name": "魔狼", "rank": "B"})
    assert r.status_code == 200
    mid = r.json()["id"]
    assert client.get(f"/api/bible/{pid}/monsters").json()[0]["name"] == "魔狼"
    r = client.put(f"/api/bible/{pid}/monsters/{mid}", json={"name": "魔狼", "rank": "A"})
    assert r.status_code == 200
    assert r.json()["rank"] == "A"
    assert client.delete(f"/api/bible/{pid}/monsters/{mid}").status_code == 200
    assert client.get(f"/api/bible/{pid}/monsters").json() == []


def test_bible_tier_and_importance(client):
    pid = client.post("/api/projects", json={"title": "x"}).json()["id"]
    r = client.post(f"/api/bible/{pid}/characters", json={"name": "刘洋", "importance": "主角"})
    assert r.status_code == 200
    assert r.json()["importance"] == "主角"
    r = client.post(f"/api/bible/{pid}/factions", json={"name": "光明教会", "tier": "顶级势力"})
    assert r.status_code == 200
    assert r.json()["tier"] == "顶级势力"
    r = client.post(f"/api/bible/{pid}/monsters", json={"name": "魔狼", "tier": "精英"})
    assert r.status_code == 200
    assert r.json()["tier"] == "精英"


def test_entity_appearances_api(client):
    pid = client.post("/api/projects", json={"title": "x"}).json()["id"]
    client.post(f"/api/bible/{pid}/characters", json={"name": "刘洋"})
    r = client.post(f"/api/bible/{pid}/entity-appearances",
                    json={"entity_type": "character", "entity_id": "刘洋",
                          "chapter": 1, "role_in_chapter": "lead"})
    assert r.status_code == 200
    aid = r.json()["id"]
    assert r.json()["entity_id"] == "刘洋"
    r = client.get(f"/api/bible/{pid}/entity-appearances?entity_type=character&chapter=1")
    assert r.status_code == 200
    assert len(r.json()) == 1
    r = client.put(f"/api/bible/{pid}/entity-appearances/{aid}",
                   json={"role_in_chapter": "participant"})
    assert r.status_code == 200
    assert r.json()["role_in_chapter"] == "participant"
    assert client.delete(f"/api/bible/{pid}/entity-appearances/{aid}").status_code == 200


def test_record_appearances_api(client):
    pid = client.post("/api/projects", json={"title": "x"}).json()["id"]
    client.post(f"/api/bible/{pid}/characters", json={"name": "刘洋"})
    r = client.post(f"/api/bible/{pid}/chapters/2/record-appearances",
                    json={"appearances": [{"entity_type": "character", "entity_id": "刘洋",
                                           "chapter": 2, "role_in_chapter": "lead"}]})
    assert r.status_code == 200
    assert r.json()["recorded"] == 1


def test_generate_faction_api(client):
    pid = client.post("/api/projects", json={"title": "x", "genre": "玄幻"}).json()["id"]
    with patch("novel_agent.llm.client.LLMClient") as MockLLM:
        mock = MagicMock()
        mock.generate = AsyncMock(return_value='{"name":"暗影盟","tier":"一流势力","type":"刺客组织","alignment":"中立邪恶","description":"暗中行事"}')
        MockLLM.return_value = mock
        r = client.post(f"/api/bible/{pid}/generate-faction",
                        json={"name_hint": "暗影盟", "type": "刺客组织"})
    assert r.status_code == 200
    assert r.json()["name"] == "暗影盟"
    assert r.json()["tier"] == "一流势力"


def test_generate_monster_api(client):
    pid = client.post("/api/projects", json={"title": "x", "genre": "玄幻"}).json()["id"]
    with patch("novel_agent.llm.client.LLMClient") as MockLLM:
        mock = MagicMock()
        mock.generate = AsyncMock(return_value='{"name":"深渊魔狼","tier":"精英","species":"魔兽","rank":"B","attributes":"暗属性"}')
        MockLLM.return_value = mock
        r = client.post(f"/api/bible/{pid}/generate-monster",
                        json={"name_hint": "深渊魔狼", "species": "魔兽"})
    assert r.status_code == 200
    assert r.json()["name"] == "深渊魔狼"
    assert r.json()["tier"] == "精英"


def test_generate_character_relationship_api(client):
    pid = client.post("/api/projects", json={"title": "x", "genre": "玄幻"}).json()["id"]
    client.post(f"/api/bible/{pid}/characters", json={"name": "刘洋"})
    client.post(f"/api/bible/{pid}/characters", json={"name": "林夏"})
    with patch("novel_agent.llm.client.LLMClient") as MockLLM:
        mock = MagicMock()
        mock.generate = AsyncMock(return_value='{"relation_type":"合作","relation_subtype":"战友","strength":7,"description":"并肩作战"}')
        MockLLM.return_value = mock
        r = client.post(f"/api/bible/{pid}/generate-character-relationship",
                        json={"source_character": "刘洋", "target_character": "林夏",
                              "relation_type_hint": "合作"})
    assert r.status_code == 200
    assert r.json()["relation_type"] == "合作"
    assert r.json()["source_character"] == "刘洋"


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
        mock.close = AsyncMock()
        MockLLM.return_value = mock
        MockAuditLLM.return_value = MagicMock()
        resp = client.post("/api/chapters/generate", json={
            "project_id": pid, "chapter": 1, "title": "第一章"})
    assert resp.status_code == 200
    assert resp.json()["status"] == "completed"


# ---- 配置 API ----

def test_get_llm_config(client):
    resp = client.get("/api/config/llm")
    assert resp.status_code == 200
    data = resp.json()
    assert "base_url" in data
    assert "api_key" in data
    assert "model" in data


def test_update_llm_config(client):
    resp = client.put("/api/config/llm", json={
        "base_url": "https://test.example.com/v1",
        "model": "test-model",
        "temperature": 0.5,
    })
    assert resp.status_code == 200
    assert resp.json()["saved"] is True

    resp = client.get("/api/config/llm")
    data = resp.json()
    assert data["base_url"] == "https://test.example.com/v1"
    assert data["model"] == "test-model"
    assert data["temperature"] == 0.5
