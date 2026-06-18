"""测试 M3 新增节点：audit/polish/route_after_audit。"""
import pytest
from unittest.mock import AsyncMock, MagicMock

from novel_agent.bible.database import SessionLocal, set_config
from novel_agent.bible.models import Base, Project
from novel_agent.bible.repository import BibleRepository
from novel_agent.orchestrator.state import ChapterGenState


@pytest.fixture
def repo(tmp_config):
    from novel_agent.bible import database as db_mod
    set_config(tmp_config)
    Base.metadata.create_all(bind=db_mod.engine)
    db = SessionLocal()
    p = Project(title="测试", genre="科幻")
    db.add(p); db.commit(); db.refresh(p)
    r = BibleRepository(db, project_id=p.id)
    r.create_character(name="刘洋", role="主角")
    yield r
    db.close()


@pytest.mark.asyncio
async def test_audit_node(repo):
    from novel_agent.orchestrator.nodes import audit_chapter
    from novel_agent.audit.schemas import AuditReport
    mock_auditor = AsyncMock()
    mock_auditor.audit = AsyncMock(return_value=AuditReport(
        passed=True, overall_score=85, summary="达标"))
    state = ChapterGenState(
        project_id=repo.project_id, chapter=1, title="第一章",
        draft="正文", draft_version=1, review_iterations=0,
    )
    result = await audit_chapter(state, auditor=mock_auditor, repo=repo)
    assert result["status"] == "audited"
    assert result["review_iterations"] == 1


@pytest.mark.asyncio
async def test_polish_node():
    from novel_agent.orchestrator.nodes import polish_chapter
    mock_client = MagicMock()
    mock_client.generate = AsyncMock(return_value="润色后正文")
    state = ChapterGenState(chapter=1, title="x", draft="原稿", status="audited")
    result = await polish_chapter(state, llm_client=mock_client)
    assert result["polished"] == "润色后正文"
    assert result["status"] == "polished"


def test_route_after_audit_pass():
    from novel_agent.orchestrator.nodes import route_after_audit
    state = ChapterGenState(
        audit_report={"passed": True, "overall_score": 85, "issues": []},
        review_iterations=1,
    )
    assert route_after_audit(state) == "polish"


def test_route_after_audit_fail_under_limit():
    from novel_agent.orchestrator.nodes import route_after_audit
    state = ChapterGenState(
        audit_report={"passed": False, "overall_score": 50, "issues": []},
        review_iterations=1,
    )
    assert route_after_audit(state) == "rewrite"


def test_route_after_audit_fail_over_limit():
    from novel_agent.orchestrator.nodes import route_after_audit
    state = ChapterGenState(
        audit_report={"passed": False, "overall_score": 50, "issues": []},
        review_iterations=3,
    )
    assert route_after_audit(state) == "end_failed"


@pytest.mark.asyncio
async def test_rewrite_node():
    from novel_agent.orchestrator.nodes import rewrite_chapter
    from novel_agent.audit.schemas import AuditReport, Issue
    mock_client = MagicMock()
    mock_client.generate = AsyncMock(return_value="重写草稿")
    state = ChapterGenState(
        chapter=1, title="第一章", context="设定", draft="旧草稿",
        draft_version=1, review_iterations=1,
        audit_report=AuditReport(
            passed=False, overall_score=50,
            issues=[Issue(dimension="人物OOC", severity="critical", message="不符")],
            suggestions=["重写对话"],
        ).model_dump(),
    )
    result = await rewrite_chapter(state, llm_client=mock_client)
    assert result["draft"] == "重写草稿"
    assert result["draft_version"] == 2
    assert result["status"] == "drafted"
