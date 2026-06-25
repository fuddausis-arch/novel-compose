"""Chat API 路由测试。"""
import pytest

from fastapi.testclient import TestClient

from novel_agent.api.app import create_app
from novel_agent.bible.database import set_config
from novel_agent.bible.models import Base, Project
from novel_agent.bible.repository import BibleRepository
from novel_agent.config import Config


@pytest.fixture
def client(tmp_path, monkeypatch):
    cfg = Config(project_data_dir=tmp_path / "project_data")
    set_config(cfg, force=True)
    from novel_agent.bible import database as db_mod
    Base.metadata.create_all(bind=db_mod.engine)
    db = db_mod.SessionLocal()
    db.add(Project(id=1, title="T"))
    db.commit()
    repo = BibleRepository(db, project_id=1)
    # 创建空章节文件避免 context builder 报错
    (cfg.project_chapters_dir(1)).mkdir(parents=True, exist_ok=True)
    db.close()
    app = create_app()
    app.state.limiter.enabled = False
    return TestClient(app)


def test_list_sessions_empty(client):
    r = client.get("/api/chat/sessions?project_id=1")
    assert r.status_code == 200
    assert r.json() == []


def test_send_message_returns_sse(client, monkeypatch):
    async def fake_stream(*a, **kw):
        yield {"type": "text", "content": "明白"}
        yield {"type": "action", "action": {"type": "query_status"}}

    from novel_agent.chat import agent
    monkeypatch.setattr(agent.ChatAgent, "stream_reply", fake_stream)

    res = client.post("/api/chat/messages", json={
        "project_id": 1,
        "message": "当前进度",
        "session_type": "global",
        "object_type": "",
        "object_id": "",
    })
    assert res.status_code == 200
    text = res.text
    assert "event: chunk" in text
    assert "event: action" in text
    assert "event: done" in text
