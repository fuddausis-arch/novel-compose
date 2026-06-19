"""测试审计报告 schema。"""
from novel_agent.audit.schemas import Issue, AuditReport


def test_issue_valid():
    i = Issue(dimension="设定一致性", severity="critical", message="主角能力前后矛盾")
    assert i.severity == "critical"


def test_issue_tolerant_severity():
    # 宽容化：任意字符串 severity 都接受
    i = Issue(dimension="x", severity="unknown", message="y")
    assert i.severity == "unknown"


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


def test_audit_report_defaults():
    # 宽容化：缺 overall_score 时默认 0，不抛错
    r = AuditReport(passed=True)
    assert r.passed is True
    assert r.overall_score == 0
