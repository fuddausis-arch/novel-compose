"""测试 delta applier：校验 → 写库 → 追加事件流。"""
import pytest

from novel_agent.bible.database import SessionLocal, set_config
from novel_agent.bible.models import Base
from novel_agent.config import Config
from novel_agent.protocol.applier import DeltaApplier, ApplyError
from novel_agent.protocol.schemas import Delta, ForeshadowDelta, CharacterDelta


@pytest.fixture
def applier(tmp_config):
    from novel_agent.bible import database as db_mod
    set_config(tmp_config)
    Base.metadata.create_all(bind=db_mod.engine)
    from novel_agent.bible.models import Project
    db = SessionLocal()
    p = Project(title="测试")
    db.add(p); db.commit(); db.refresh(p)
    from novel_agent.bible.repository import BibleRepository
    repo = BibleRepository(db, project_id=p.id)
    yield DeltaApplier(repo)
    db.close()


def test_apply_foreshadow_plant_writes_and_events(applier):
    delta = Delta(
        target="foreshadow", action="plant", chapter=3,
        data=ForeshadowDelta(foreshadow_id="S-001", description="文物箱",
                             plant_chapter=3, planned_resolve_chapter=10),
    )
    result = applier.apply(delta)
    assert result.success
    f = applier.repo.get_foreshadow("S-001")
    assert f is not None
    assert f.status == "planted"
    events = applier.repo.list_events(chapter=3, entity_id="S-001")
    assert len(events) == 1
    assert events[0].type == "foreshadow_planted"


def test_apply_character_state_change(applier):
    # 先建角色
    applier.repo.create_character(name="刘洋")
    delta = Delta(
        target="character", action="state_change", chapter=5,
        data=CharacterDelta(name="刘洋", current_emotion="愤怒", current_location="基地"),
    )
    result = applier.apply(delta)
    assert result.success
    c = applier.repo.get_character("刘洋")
    assert c.current_emotion == "愤怒"
    events = applier.repo.list_events(chapter=5, entity_id="刘洋")
    assert any(e.type == "character_state_change" for e in events)


def test_apply_foreshadow_resolve(applier):
    applier.repo.create_foreshadow(foreshadow_id="S-001", tier="short",
                                   plant_chapter=1, status="planted")
    delta = Delta(
        target="foreshadow", action="resolve", chapter=10,
        data=ForeshadowDelta(foreshadow_id="S-001"),
    )
    result = applier.apply(delta)
    assert result.success
    f = applier.repo.get_foreshadow("S-001")
    assert f.status == "resolved"


def test_apply_unknown_action_raises(applier):
    with pytest.raises(ApplyError):
        applier.apply(Delta(
            target="foreshadow", action="delete", chapter=1,
            data=ForeshadowDelta(foreshadow_id="X"),
        ))
