"""测试审计报告 schema。"""
import pytest
from pydantic import ValidationError

from novel_agent.audit.schemas import Issue, AuditReport


def test_issue_valid():
    i = Issue(dimension="设定一致性", severity="critical", message="主角能力前后矛盾")
    assert i.severity == "critical"


def test_issue_invalid_severity():
    with pytest.raises(ValidationError):
        Issue(dimension="x", severity="unknown", message="y")


def test_audit_report_passed():
    r = AuditReport(passed=True, overall_score=85, issues=[], summary="达标")
    assert r.passed is True
    assert r.overall_score == 85


def test_audit_report_with_issues():
    r = AuditReport(
        passed=False, overall_score=60,
        issues=[
            Issue(dimension="人物OOC", severity="critical", message="角色反应不符人设"),
            Issue(dimension="节奏控制", severity="minor", message="转折过密"),
        ],
        summary="关键问题：OOC",
    )
    assert len(r.issues) == 2
    assert any(i.severity == "critical" for i in r.issues)


def test_audit_report_requires_fields():
    with pytest.raises(ValidationError):
        AuditReport(passed=True)  # 缺 overall_score
