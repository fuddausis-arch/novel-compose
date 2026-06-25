"""验证章节生成时自动注入 chapter_feedback。"""
import pytest

from novel_agent.bible.database import set_config
from novel_agent.bible.models import Base, Project, Outline
from novel_agent.bible.repository import BibleRepository
from novel_agent.chat.repository import ChatRepository
from novel_agent.config import Config
from novel_agent.orchestrator.nodes import _build_chapter_brief


@pytest.fixture
def deps(tmp_path, monkeypatch):
    monkeypatch.setenv("NOVEL_TEST_DB", "memory")
    cfg = Config(project_data_dir=tmp_path / "project_data")
    set_config(cfg, force=True)
    from novel_agent.bible import database as db_mod
    Base.metadata.create_all(bind=db_mod.engine)
    db = db_mod.SessionLocal()
    db.add(Project(id=1, title="T"))
    db.add(Outline(project_id=1, level="chapter", order=3, title="第3章", summary="s"))
    db.commit()
    repo = BibleRepository(db, project_id=1)
    chat_repo = ChatRepository(db, project_id=1)
    chat_repo.add_chapter_feedback(3, "对话太生硬")
    yield repo
    db.close()


def test_feedback_injected(deps):
    outline = deps.get_outline_by_chapter(3)
    brief = _build_chapter_brief(outline, deps)
    assert "用户聊天反馈" in brief
    assert "对话太生硬" in brief
