"""测试仓储 CRUD。"""
import pytest

from novel_agent.bible.database import SessionLocal, engine
from novel_agent.bible.models import Base, Project, Character, Foreshadow, TruthEvent
from novel_agent.bible.repository import BibleRepository


@pytest.fixture
def repo():
    Base.metadata.create_all(bind=engine)
    db = SessionLocal()
    # 建一个项目
    p = Project(title="测试小说", genre="科幻")
    db.add(p)
    db.commit()
    db.refresh(p)
    yield BibleRepository(db, project_id=p.id)
    db.close()


def test_create_character(repo):
    c = repo.create_character(name="刘洋", role="主角", personality="冷静")
    assert c.id is not None
    assert c.name == "刘洋"


def test_create_foreshadow(repo):
    f = repo.create_foreshadow(
        foreshadow_id="S-001", tier="short", plant_chapter=1,
        description="修理厂地下室神秘文物箱", planned_resolve_chapter=3,
    )
    assert f.status == "pending"
    assert f.foreshadow_id == "S-001"


def test_update_foreshadow_status(repo):
    f = repo.create_foreshadow(foreshadow_id="S-001", tier="short", plant_chapter=1)
    repo.update_foreshadow_status("S-001", "planted")
    f2 = repo.get_foreshadow("S-001")
    assert f2.status == "planted"


def test_append_truth_event(repo):
    repo.append_event(chapter=1, type="foreshadow_planted", entity_id="S-001",
                      payload={"method": "对话暗示"})
    events = repo.list_events(chapter=1)
    assert len(events) == 1
    assert events[0].type == "foreshadow_planted"
    assert events[0].payload["method"] == "对话暗示"


def test_get_pending_foreshadows(repo):
    repo.create_foreshadow(foreshadow_id="S-001", tier="short", plant_chapter=1)
    repo.create_foreshadow(foreshadow_id="S-002", tier="short", plant_chapter=2)
    repo.update_foreshadow_status("S-001", "planted")
    pending = repo.get_foreshadows_by_status("pending")
    assert len(pending) == 1
    assert pending[0].foreshadow_id == "S-002"
