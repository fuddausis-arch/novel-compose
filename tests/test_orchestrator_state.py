"""测试流水线状态 schema。"""
from novel_agent.orchestrator.state import ChapterGenState


def test_state_has_required_fields():
    s = ChapterGenState(project_id=1, chapter=5, title="第五章")
    assert s["project_id"] == 1
    assert s["chapter"] == 5
    assert s["title"] == "第五章"
    # total=False 下未设字段不存在，用 get 取默认
    assert s.get("context", "") == ""
    assert s.get("draft", "") == ""
    assert s.get("status", "pending") == "pending"


def test_state_with_context_and_draft():
    s = ChapterGenState(
        project_id=1, chapter=5, title="第五章",
        context="前文摘要", draft="章节正文", status="drafted",
    )
    assert s["context"] == "前文摘要"
    assert s["draft"] == "章节正文"
    assert s["status"] == "drafted"


def test_state_error_field():
    s = ChapterGenState(project_id=1, chapter=5, title="x", error="LLM 超时")
    assert s["error"] == "LLM 超时"
