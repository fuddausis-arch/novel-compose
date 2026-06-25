"""ChatRepository 单元测试。"""
from __future__ import annotations

import pytest

from novel_agent.bible.database import set_config
from novel_agent.bible.models import Base
from novel_agent.bible.repository import BibleRepository
from novel_agent.chat.repository import ChatRepository
from novel_agent.config import Config


@pytest.fixture
def repo(tmp_path, monkeypatch):
    monkeypatch.setenv("NOVEL_TEST_DB", "memory")
    cfg = Config(project_data_dir=tmp_path / "project_data")
    set_config(cfg, force=True)
    from novel_agent.bible import database as db_mod
    Base.metadata.create_all(bind=db_mod.engine)
    db = db_mod.SessionLocal()
    project = BibleRepository(db, project_id=1).get_project()
    if project is None:
        from novel_agent.bible.models import Project
        db.add(Project(id=1, title="test"))
        db.commit()
    chat_repo = ChatRepository(db, project_id=1)
    yield chat_repo
    db.close()


def test_get_or_create_session(repo):
    s1 = repo.get_or_create_session("object", "chapter", "3", "第3章")
    s2 = repo.get_or_create_session("object", "chapter", "3")
    assert s1.id == s2.id
    assert s2.title == "第3章"


def test_messages_and_delete(repo):
    s = repo.get_or_create_session("global", title="全局")
    repo.add_message(s.id, "user", "hello")
    repo.add_message(s.id, "assistant", "hi")
    msgs = repo.list_messages(s.id)
    assert len(msgs) == 2
    repo.delete_session(s.id)
    assert repo.get_session(s.id) is None


def test_chapter_feedback(repo):
    fb = repo.add_chapter_feedback(3, "对话太生硬")
    pending = repo.get_pending_feedback(3)
    assert len(pending) == 1
    repo.mark_feedback_applied([fb.id])
    assert len(repo.get_pending_feedback(3)) == 0
