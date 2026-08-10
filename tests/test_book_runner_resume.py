import pytest
from unittest.mock import AsyncMock, patch, MagicMock
from novel_agent.orchestrator.book_runner import BookRunner


@pytest.mark.asyncio
async def test_book_runner_uses_stable_thread_id(tmp_path):
    """同一章多次调用应使用稳定 thread_id，使 SqliteSaver checkpoint 可命中。"""
    from novel_agent.bible.database import SessionLocal, set_config
    from novel_agent.bible.models import Base, Project
    from novel_agent.config import load_config
    from novel_agent.bible.repository import BibleRepository

    cfg = load_config()
    set_config(cfg)
    from novel_agent.bible import database as db_mod
    Base.metadata.create_all(bind=db_mod.engine)
    db = SessionLocal()
    proj = Project(title="t", genre="都市异能")
    db.add(proj); db.commit(); db.refresh(proj)
    repo = BibleRepository(db, proj.id)

    runner = BookRunner(cfg, repo)
    runner.summary_tree = MagicMock()

    seen_tids = []
    async def fake_runner_run(self, chapter, title, thread_id=None):
        seen_tids.append((chapter, thread_id))
        return {"status": "completed", "draft": "x", "draft_version": 1}

    from novel_agent.orchestrator import runner as runner_mod
    with patch.object(runner_mod.ChapterRunner, "run", fake_runner_run), \
         patch.object(runner_mod.ChapterRunner, "close", AsyncMock()):
        await runner.run_volume(1, 3)

    ch1_ids = [tid for ch, tid in seen_tids if ch == 1]
    assert len(ch1_ids) == 1
    assert ch1_ids[0] and "project_" in ch1_ids[0]
    db.close()
