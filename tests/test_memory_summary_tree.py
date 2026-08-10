"""测试摘要树：章→弧→卷→全书。"""
import pytest

from novel_agent.bible.database import SessionLocal, set_config
from novel_agent.bible.models import Base, Project
from novel_agent.bible.repository import BibleRepository
from novel_agent.memory.summary_tree import SummaryTree


@pytest.fixture
def repo(tmp_config):
    from novel_agent.bible import database as db_mod
    set_config(tmp_config)
    Base.metadata.create_all(bind=db_mod.engine)
    db = SessionLocal()
    p = Project(title="测试")
    db.add(p); db.commit(); db.refresh(p)
    r = BibleRepository(db, project_id=p.id)
    # 建几章摘要
    for ch in range(1, 6):
        r.create_chapter_summary(
            chapter=ch, title=f"第{ch}章", core_events=f"第{ch}章事件",
            word_count=2000,
        )
    yield r
    db.close()


def test_get_chapter_summaries(repo):
    tree = SummaryTree(repo)
    summaries = tree.get_recent_chapter_summaries(count=3)
    assert len(summaries) == 3
    # 最近 3 章按章节升序
    assert [s.chapter for s in summaries] == [3, 4, 5]
