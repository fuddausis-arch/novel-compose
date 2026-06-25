"""ChatAgent 测试（mock LLM）。"""
import pytest

from novel_agent.bible.database import set_config
from novel_agent.bible.models import Base, Project
from novel_agent.bible.repository import BibleRepository
from novel_agent.chat.agent import ChatAgent
from novel_agent.config import Config


@pytest.fixture
async def agent(tmp_path, monkeypatch):
    monkeypatch.setenv("NOVEL_TEST_DB", "memory")
    cfg = Config(project_data_dir=tmp_path / "project_data")
    set_config(cfg, force=True)
    from novel_agent.bible import database as db_mod
    Base.metadata.create_all(bind=db_mod.engine)
    db = db_mod.SessionLocal()
    db.add(Project(id=1, title="T"))
    db.commit()
    repo = BibleRepository(db, project_id=1)
    a = ChatAgent(repo, cfg)

    async def fake_generate(*a, **kw):
        return '好的，已重写。\n{"type": "rewrite_chapter", "chapter": 3, "feedback": "太生硬"}'

    async def fake_close(self):
        pass

    a.client = type("C", (), {"generate": fake_generate, "close": fake_close})()
    yield a
    db.close()


@pytest.mark.asyncio
async def test_stream_reply(agent):
    chunks = []
    async for c in agent.stream_reply("重写第3章", [], "项目上下文"):
        chunks.append(c)
    texts = [c["content"] for c in chunks if c["type"] == "text"]
    actions = [c["action"] for c in chunks if c["type"] == "action"]
    assert "好的，已重写。" in texts
    assert any(a["type"] == "rewrite_chapter" for a in actions)
