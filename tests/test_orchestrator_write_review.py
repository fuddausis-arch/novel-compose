"""写审循环端到端集成测试。"""
import pytest
from unittest.mock import AsyncMock, MagicMock

from novel_agent.audit.auditor import Auditor
from novel_agent.audit.schemas import AuditReport, Issue
from novel_agent.bible.database import SessionLocal, set_config
from novel_agent.bible.models import Base, Project
from novel_agent.bible.repository import BibleRepository
from novel_agent.orchestrator.runner import ChapterRunner


@pytest.fixture
def make_runner(tmp_config):
    from novel_agent.bible import database as db_mod
    set_config(tmp_config)
    Base.metadata.create_all(bind=db_mod.engine)
    db = SessionLocal()
    p = Project(title="测试", genre="科幻", summary="末日")
    db.add(p); db.commit(); db.refresh(p)
    r = BibleRepository(db, project_id=p.id)
    r.create_character(name="刘洋", role="主角")
    runners = []

    def _make(llm_client=None, auditor=None):
        runner = ChapterRunner(tmp_config, repo=r, llm_client=llm_client, auditor=auditor)
        runners.append(runner)
        return runner

    yield _make
    for rn in runners:
        rn.close()
    db.close()


@pytest.mark.asyncio
async def test_write_review_pass_on_first_audit(make_runner):
    """审计一次达标 → polish → save → summarize 全流程。"""
    mock_llm = MagicMock()
    # write/polish/summarize 各调一次 generate，用 side_effect 区分
    mock_llm.generate = AsyncMock(side_effect=[
        "草稿正文",           # write
        "润色后正文",         # polish
        '{"core_events":"事件","characters_present":"刘洋"}',  # summarize
    ])
    mock_auditor = MagicMock()
    mock_auditor.audit = AsyncMock(return_value=AuditReport(
        passed=True, overall_score=85, summary="达标"))
    runner = make_runner(llm_client=mock_llm, auditor=mock_auditor)

    result = await runner.run(chapter=1, title="第一章")

    assert result["status"] == "completed"
    assert result["review_iterations"] == 1
    assert "润色后正文" in runner.recall.read_chapter_text(1)
    assert runner.repo.get_chapter_summary(1) is not None


@pytest.mark.asyncio
async def test_write_review_rewrite_once_then_pass(make_runner):
    """审计不达标 → 重写 → 再审达标。"""
    mock_llm = MagicMock()
    mock_llm.generate = AsyncMock(side_effect=[
        "初版草稿",           # write v1
        "重写草稿",           # rewrite v2
        "润色后",             # polish
        '{"core_events":"事件"}',  # summarize
    ])
    mock_auditor = MagicMock()
    mock_auditor.audit = AsyncMock(side_effect=[
        AuditReport(passed=False, overall_score=50, issues=[
            Issue(dimension="人物OOC", severity="critical", message="不符")],
            suggestions=["重写对话"]),  # 第一次审：不达标
        AuditReport(passed=True, overall_score=85, summary="达标"),  # 第二次：达标
    ])
    runner = make_runner(llm_client=mock_llm, auditor=mock_auditor)

    result = await runner.run(chapter=1, title="第一章")

    assert result["status"] == "completed"
    assert result["review_iterations"] == 2
    assert result["draft_version"] == 2


@pytest.mark.asyncio
async def test_write_review_fail_after_three(make_runner):
    """连续 3 次审计不达标 → 失败结束（不进 polish）。"""
    mock_llm = MagicMock()
    mock_llm.generate = AsyncMock(side_effect=[
        "草稿v1", "草稿v2", "草稿v3",  # write + 2 次 rewrite
    ])
    mock_auditor = MagicMock()
    fail_report = AuditReport(passed=False, overall_score=40, summary="始终不达标")
    mock_auditor.audit = AsyncMock(return_value=fail_report)
    runner = make_runner(llm_client=mock_llm, auditor=mock_auditor)

    result = await runner.run(chapter=1, title="第一章")

    assert result["review_iterations"] == 3
    # 超过 3 次进 end_failed，status 应非 completed
    assert result["status"] != "completed"
