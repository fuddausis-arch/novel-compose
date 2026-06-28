"""测试 Auditor agent：多维度独立审校，产出结构化审计报告。"""
import pytest
from unittest.mock import AsyncMock

from novel_agent.audit.auditor import Auditor
from novel_agent.audit.schemas import AuditReport
from novel_agent.bible.database import SessionLocal, set_config
from novel_agent.bible.models import Base, Project
from novel_agent.bible.repository import BibleRepository


@pytest.fixture
def repo(tmp_config):
    from novel_agent.bible import database as db_mod
    set_config(tmp_config)
    Base.metadata.create_all(bind=db_mod.engine)
    db = SessionLocal()
    p = Project(title="测试", genre="科幻")
    db.add(p); db.commit(); db.refresh(p)
    r = BibleRepository(db, project_id=p.id)
    r.create_character(name="刘洋", role="主角", personality="冷静")
    yield r
    db.close()


@pytest.mark.asyncio
async def test_auditor_returns_report(repo):
    """三视角审查全部通过时，Auditor 返回 passed=True。"""
    mock_llm = AsyncMock()
    mock_llm.generate = AsyncMock(return_value="""```json
{"score": 85, "passed": true, "issues": [], "summary": "达标"}
```""")
    auditor = Auditor(mock_llm)
    report = await auditor.audit(
        chapter=1, title="第一章", draft="正文内容……", repo=repo,
    )
    assert isinstance(report, AuditReport)
    assert report.passed is True
    assert report.overall_score == 85
    assert report.user_perspective.score == 85
    assert report.expert_perspective.score == 85
    assert report.editor_perspective.score == 85


@pytest.mark.asyncio
async def test_auditor_flags_failed(repo):
    """任一视角不通过时，report.passed 为 False。"""
    pass_response = """```json
{"score": 85, "passed": true, "issues": [], "summary": "达标"}
```"""
    fail_response = """```json
{"score": 55, "passed": false, "issues": ["人物OOC：反应不符"], "summary": "OOC"}
```"""
    call_count = [0]
    async def mock_generate(*args, **kwargs):
        idx = call_count[0]
        call_count[0] += 1
        # 三视角并行，第2个（专业视角）返回不通过
        return fail_response if idx == 1 else pass_response
    mock_llm = AsyncMock()
    mock_llm.generate = mock_generate
    auditor = Auditor(mock_llm)
    report = await auditor.audit(
        chapter=1, title="第一章", draft="正文", repo=repo,
    )
    assert report.passed is False
    assert report.expert_perspective.passed is False
    assert report.user_perspective.passed is True
    assert len(report.issues) > 0


@pytest.mark.asyncio
async def test_auditor_handles_malformed_json(repo):
    """LLM 返回非 JSON 时，Auditor 应返回 failed 报告而非崩溃。"""
    mock_llm = AsyncMock()
    mock_llm.generate = AsyncMock(return_value="这不是 JSON")
    auditor = Auditor(mock_llm)
    report = await auditor.audit(
        chapter=1, title="第一章", draft="正文", repo=repo,
    )
    assert report.passed is False
    assert report.overall_score == 0
