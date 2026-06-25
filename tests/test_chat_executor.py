"""ActionExecutor 测试。"""
import pytest

from novel_agent.bible.database import set_config
from novel_agent.bible.models import Base, Project
from novel_agent.bible.repository import BibleRepository
from novel_agent.chat.executor import ActionExecutor
from novel_agent.config import Config


@pytest.fixture
def executor(tmp_path, monkeypatch):
    monkeypatch.setenv("NOVEL_TEST_DB", "memory")
    cfg = Config(project_data_dir=tmp_path / "project_data")
    set_config(cfg, force=True)
    from novel_agent.bible import database as db_mod
    Base.metadata.create_all(bind=db_mod.engine)
    db = db_mod.SessionLocal()
    db.add(Project(id=1, title="T"))
    db.commit()
    repo = BibleRepository(db, project_id=1)
    yield ActionExecutor(repo, cfg)
    db.close()


@pytest.mark.asyncio
async def test_add_feedback(executor):
    res = await executor.execute({"type": "add_chapter_feedback", "chapter": 3, "feedback": "太生硬"})
    assert res["ok"] is True
    assert res["chapter"] == 3


@pytest.mark.asyncio
async def test_query_status(executor):
    res = await executor.execute({"type": "query_status"})
    assert res["ok"] is True
    assert "chapter_count" in res
