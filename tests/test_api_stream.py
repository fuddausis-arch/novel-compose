"""测试 SSE 流式章节生成端点。"""
import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from fastapi.testclient import TestClient
from novel_agent.api.app import create_app


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("NOVEL_PROJECT_DATA", str(tmp_path / "project_data"))
    return TestClient(create_app(project_data_dir=tmp_path / "project_data"))


def test_generate_stream_emits_node_events(client):
    """SSE 端点应产出 node 事件序列 + done 事件。"""
    pid = client.post("/api/projects", json={"title": "x"}).json()["id"]
    from novel_agent.audit.schemas import AuditReport
    with patch("novel_agent.orchestrator.runner.LLMClient") as MockLLM, \
         patch("novel_agent.audit.auditor.LLMClient") as MockAuditLLM, \
         patch("novel_agent.audit.auditor.Auditor.audit",
               new=AsyncMock(return_value=AuditReport(passed=True, overall_score=85, summary="ok"))):
        mock = MagicMock()
        mock.generate = AsyncMock(side_effect=["草稿", "润色", '{"core_events":"e"}'])
        mock.close = AsyncMock()
        MockLLM.return_value = mock
        MockAuditLLM.return_value = MagicMock()
        with client.stream("GET", f"/api/chapters/generate/stream?project_id={pid}&chapter=1&title=ch1") as resp:
            assert resp.status_code == 200
            event_types = []
            for line in resp.iter_lines():
                if line.startswith("event:"):
                    event_types.append(line.split(":", 1)[1].strip())
            assert "node" in event_types
            assert "done" in event_types


def test_generate_stream_node_events_contain_pipeline_stages(client):
    """node 事件应包含 assemble/write/audit 等流水线阶段。"""
    pid = client.post("/api/projects", json={"title": "x"}).json()["id"]
    from novel_agent.audit.schemas import AuditReport
    with patch("novel_agent.orchestrator.runner.LLMClient") as MockLLM, \
         patch("novel_agent.audit.auditor.LLMClient") as MockAuditLLM, \
         patch("novel_agent.audit.auditor.Auditor.audit",
               new=AsyncMock(return_value=AuditReport(passed=True, overall_score=85, summary="ok"))):
        mock = MagicMock()
        mock.generate = AsyncMock(side_effect=["草稿", "润色", '{"core_events":"e"}'])
        mock.close = AsyncMock()
        MockLLM.return_value = mock
        MockAuditLLM.return_value = MagicMock()
        nodes_seen = set()
        with client.stream("GET", f"/api/chapters/generate/stream?project_id={pid}&chapter=1&title=ch1") as resp:
            import json
            current_event = None
            for line in resp.iter_lines():
                if line.startswith("event:"):
                    current_event = line.split(":", 1)[1].strip()
                elif line.startswith("data:") and current_event == "node":
                    try:
                        d = json.loads(line.split(":", 1)[1].strip())
                        nodes_seen.add(d["node"])
                    except Exception:
                        pass
        assert "assemble" in nodes_seen
        assert "write" in nodes_seen
        assert "audit" in nodes_seen
