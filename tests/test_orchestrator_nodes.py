"""测试编排节点函数。"""
import pytest
from unittest.mock import AsyncMock, MagicMock

from novel_agent.bible.database import SessionLocal, set_config
from novel_agent.bible.models import Base, Project
from novel_agent.bible.repository import BibleRepository
from novel_agent.orchestrator.state import ChapterGenState
from novel_agent.orchestrator.nodes import assemble_context, write_chapter, save_text, save_summary


@pytest.fixture
def repo(tmp_config):
    from novel_agent.bible import database as db_mod
    set_config(tmp_config)
    Base.metadata.create_all(bind=db_mod.engine)
    db = SessionLocal()
    p = Project(title="测试", genre="科幻", summary="末日")
    db.add(p); db.commit(); db.refresh(p)
    r = BibleRepository(db, project_id=p.id)
    r.create_character(name="刘洋", role="主角")
    yield r
    db.close()


def test_assemble_context_node(repo):
    state = ChapterGenState(project_id=repo.project_id, chapter=1, title="第一章")
    result = assemble_context(state, repo=repo)
    assert "刘洋" in result["context"]
    assert result["status"] == "assembled"


@pytest.mark.asyncio
async def test_write_chapter_node(repo):
    state = ChapterGenState(
        project_id=repo.project_id, chapter=1, title="第一章",
        context="设定：刘洋是主角", status="assembled",
    )
    mock_client = MagicMock()
    mock_client.generate = AsyncMock(return_value="第一章正文……")
    result = await write_chapter(state, llm_client=mock_client)
    assert "第一章正文" in result["draft"]
    assert result["status"] == "drafted"


def test_save_text_node(repo, tmp_config):
    state = ChapterGenState(
        project_id=repo.project_id, chapter=1, title="第一章",
        draft="第一章正文内容", status="drafted",
    )
    from novel_agent.memory.recall import RecallMemory
    recall = RecallMemory(tmp_config)
    result = save_text(state, recall=recall)
    assert result["status"] == "saved"
    assert "第一章正文内容" in recall.read_chapter_text(1)


def test_save_summary_node(repo):
    state = ChapterGenState(
        project_id=repo.project_id, chapter=1, title="第一章",
        draft="第一章正文内容", status="saved", word_count=6,
    )
    from novel_agent.protocol.applier import DeltaApplier
    applier = DeltaApplier(repo)
    result = save_summary(state, applier=applier)
    assert result["status"] == "completed"
    s = repo.get_chapter_summary(1)
    assert s is not None
    assert s.title == "第一章"
