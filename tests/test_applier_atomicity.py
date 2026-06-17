"""测试 applier 事务原子性：handler 内多步写要么全成功要么全回滚。"""
import pytest
from unittest.mock import patch

from novel_agent.bible.database import SessionLocal, set_config
from novel_agent.bible.models import Base, Project
from novel_agent.protocol.applier import DeltaApplier, ApplyError
from novel_agent.protocol.schemas import Delta, ForeshadowDelta


@pytest.fixture
def applier(tmp_config):
    from novel_agent.bible import database as db_mod
    set_config(tmp_config)
    Base.metadata.create_all(bind=db_mod.engine)
    db = SessionLocal()
    p = Project(title="测试")
    db.add(p); db.commit(); db.refresh(p)
    from novel_agent.bible.repository import BibleRepository
    repo = BibleRepository(db, project_id=p.id)
    yield DeltaApplier(repo)
    db.close()


def test_plant_foreshadow_atomic_on_event_failure(applier):
    """append_event 抛错时，伏笔写入应回滚（不留半成品）。"""
    delta = Delta(
        target="foreshadow", action="plant", chapter=3,
        data=ForeshadowDelta(foreshadow_id="S-001", description="文物箱",
                             plant_chapter=3, planned_resolve_chapter=10),
    )
    # 让 append_event 抛错
    with patch.object(applier.repo, "append_event", side_effect=RuntimeError("db down")):
        with pytest.raises(ApplyError):
            applier.apply(delta)
    # 伏笔不应残留
    f = applier.repo.get_foreshadow("S-001")
    assert f is None or f.status != "planted"


def test_successful_apply_commits_atomically(applier):
    """正常 apply 应一次提交完成快照+事件。"""
    delta = Delta(
        target="foreshadow", action="plant", chapter=3,
        data=ForeshadowDelta(foreshadow_id="S-001", description="文物箱",
                             plant_chapter=3, planned_resolve_chapter=10),
    )
    result = applier.apply(delta)
    assert result.success
    assert applier.repo.get_foreshadow("S-001").status == "planted"
    assert len(applier.repo.list_events(chapter=3, entity_id="S-001")) == 1
