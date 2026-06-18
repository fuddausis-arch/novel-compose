"""测试 Auditor agent：独立审校，产出结构化审计报告。"""
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
    """Auditor 应返回结构化 AuditReport（mock LLM 返回 JSON）。"""
    mock_llm = AsyncMock()
    mock_llm.generate = AsyncMock(return_value="""```json
{"passed": true, "overall_score": 85, "issues": [], "summary": "达标", "suggestions": []}
```""")
    auditor = Auditor(mock_llm)
    report = await auditor.audit(
        chapter=1, title="第一章", draft="正文内容……", repo=repo,
    )
    assert isinstance(report, AuditReport)
    assert report.passed is True
    assert report.overall_score == 85


@pytest.mark.asyncio
async def test_auditor_flags_failed(repo):
    """LLM 返回不达标时，report.passed 为 False。"""
    mock_llm = AsyncMock()
    mock_llm.generate = AsyncMock(return_value="""```json
{"passed": false, "overall_score": 55, "issues": [{"dimension":"人物OOC","severity":"critical","message":"反应不符"}], "summary": "OOC", "suggestions": ["重写对话"]}
```""")
    auditor = Auditor(mock_llm)
    report = await auditor.audit(
        chapter=1, title="第一章", draft="正文", repo=repo,
    )
    assert report.passed is False
    assert len(report.issues) == 1
    assert report.issues[0].severity == "critical"


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
    assert "解析" in report.summary or "失败" in report.summary
