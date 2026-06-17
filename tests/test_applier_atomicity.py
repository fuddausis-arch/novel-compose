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


def test_create_summary_indexes_archival(applier, tmp_config):
    """create_summary 应同步索引到 archival 向量库。"""
    from novel_agent.memory.archival import ArchivalMemory
    from novel_agent.protocol.schemas import SummaryDelta
    archival = ArchivalMemory(tmp_config)
    applier.archival = archival
    delta = Delta(
        target="chapter_summary", action="create", chapter=1,
        data=SummaryDelta(title="第一章", core_events="征召事件", word_count=2000),
    )
    result = applier.apply(delta)
    assert result.success
    # 章节摘要应被索引到 archival
    hits = archival.retrieve(query="征召", top_k=5)
    assert len(hits) >= 1
    archival.reset()


def test_applier_without_archival_still_works(applier):
    """未注入 archival 时，create_summary 仍正常（不同步向量库）。"""
    from novel_agent.protocol.schemas import SummaryDelta
    delta = Delta(
        target="chapter_summary", action="create", chapter=1,
        data=SummaryDelta(title="第一章", core_events="事件"),
    )
    result = applier.apply(delta)
    assert result.success
