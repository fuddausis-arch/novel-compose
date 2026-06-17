"""测试 runner：组装依赖 + 跑 graph + 断点续跑。"""
import pytest
from unittest.mock import AsyncMock, MagicMock

from novel_agent.bible.database import SessionLocal, set_config
from novel_agent.bible.models import Base, Project
from novel_agent.bible.repository import BibleRepository
from novel_agent.orchestrator.runner import ChapterRunner


@pytest.fixture
def make_runner(tmp_config):
    """工厂 fixture：可注入 mock llm_client。"""
    from novel_agent.bible import database as db_mod
    set_config(tmp_config)
    Base.metadata.create_all(bind=db_mod.engine)
    db = SessionLocal()
    p = Project(title="测试", genre="科幻", summary="末日")
    db.add(p); db.commit(); db.refresh(p)
    r = BibleRepository(db, project_id=p.id)
    r.create_character(name="刘洋", role="主角")

    runners = []

    def _make(llm_client=None):
        runner = ChapterRunner(tmp_config, repo=r, llm_client=llm_client)
        runners.append(runner)
        return runner

    yield _make
    for rn in runners:
        rn.close()
    db.close()


def test_runner_builds_graph(make_runner):
    runner = make_runner()
    assert runner.graph is not None


@pytest.mark.asyncio
async def test_runner_generates_chapter_with_mock_llm(make_runner):
    """用 mock LLM 跑通完整流水线。"""
    mock_client = MagicMock()
    mock_client.generate = AsyncMock(return_value="刘洋在修理厂修车……（正文）")
    runner = make_runner(llm_client=mock_client)

    result = await runner.run(chapter=1, title="第一章")

    assert result["status"] == "completed"
    assert "刘洋" in result["draft"]
    # 正文已存
    assert "刘洋" in runner.recall.read_chapter_text(1)
    # 摘要已存
    assert runner.repo.get_chapter_summary(1) is not None


@pytest.mark.asyncio
async def test_runner_resumes_from_checkpoint(make_runner):
    """崩溃后能从 checkpoint 恢复（同一 thread_id 续跑不报错）。"""
    mock_client = MagicMock()
    mock_client.generate = AsyncMock(return_value="正文内容")
    runner = make_runner(llm_client=mock_client)

    # 第一次跑完
    await runner.run(chapter=1, title="第一章", thread_id="t1")
    # 第二次用同 thread_id 应能恢复状态（不报错）
    result = await runner.run(chapter=1, title="第一章", thread_id="t1")
    assert result["status"] == "completed"
