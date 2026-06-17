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


def test_get_arc_summary_not_implemented_gracefully(repo):
    tree = SummaryTree(repo)
    # M1：弧/卷摘要暂不支持自动生成，返回空
    arc_summary = tree.get_arc_summary(arc_chapters=[1, 2, 3])
    # M1 至少返回章节摘要的拼接
    assert "第1章" in arc_summary


def test_get_full_summary(repo):
    tree = SummaryTree(repo)
    full = tree.get_full_summary()
    assert "测试" in full  # 项目标题
    assert "第5章" in full
