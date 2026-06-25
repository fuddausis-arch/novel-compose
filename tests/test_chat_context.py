"""ContextBuilder 测试。"""
import pytest

from novel_agent.bible.database import set_config
from novel_agent.bible.models import Base, Project
from novel_agent.bible.repository import BibleRepository
from novel_agent.chat.context import ContextBuilder
from novel_agent.config import Config


@pytest.fixture
def builder(tmp_path, monkeypatch):
    monkeypatch.setenv("NOVEL_TEST_DB", "memory")
    cfg = Config(project_data_dir=tmp_path / "project_data")
    set_config(cfg, force=True)
    from novel_agent.bible import database as db_mod
    Base.metadata.create_all(bind=db_mod.engine)
    db = db_mod.SessionLocal()
    db.add(Project(id=1, title="T", genre="玄幻", summary="s"))
    db.commit()
    repo = BibleRepository(db, project_id=1)
    yield ContextBuilder(repo, cfg)
    db.close()


def test_global_context(builder):
    text = builder.build("global", "", "")
    assert "全局对话模式" in text
    assert "T" in text


def test_unknown_object(builder):
    text = builder.build("object", "monster", "99")
    assert "不存在" in text
