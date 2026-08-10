"""Chat API 功能测试：会话创建/列表/消息/删除，默认 mock LLM 流式回复。"""
from __future__ import annotations

import pytest

from novel_agent.chat.agent import ChatAgent


async def _fake_stream(*args, **kwargs):
    """返回固定文本流，不调用真实 LLM。"""
    yield {"type": "text", "content": "收到，当前项目状态正常。"}


def _send_message(client, project_id: int, message: str = "当前进度") -> str:
    """发送消息并返回创建出的会话 ID。"""
    resp = client.post(
        "/api/chat/messages",
        json={
            "project_id": project_id,
            "message": message,
            "session_type": "global",
            "object_type": "",
            "object_id": "",
        },
    )
    assert resp.status_code == 200
    text = resp.text
    assert "event: chunk" in text
    assert "event: done" in text

    sessions = client.get(f"/api/chat/sessions?project_id={project_id}").json()
    assert len(sessions) == 1
    return sessions[0]["id"]


def test_list_sessions_empty(client, sample_project):
    """初始时项目下没有会话，列表为空。"""
    resp = client.get(f"/api/chat/sessions?project_id={sample_project}")
    assert resp.status_code == 200
    assert resp.json() == []


def test_send_message_creates_session(client, sample_project, monkeypatch):
    """发送消息后应创建出全局会话并返回 SSE 事件。"""
    monkeypatch.setattr(ChatAgent, "stream_reply", _fake_stream)
    session_id = _send_message(client, sample_project)
    assert session_id


def test_get_messages(client, sample_project, monkeypatch):
    """发送消息后应能读取到 user 与 assistant 两条消息。"""
    monkeypatch.setattr(ChatAgent, "stream_reply", _fake_stream)
    session_id = _send_message(client, sample_project)

    resp = client.get(f"/api/chat/sessions/{session_id}/messages?project_id={sample_project}")
    assert resp.status_code == 200
    msgs = resp.json()
    assert len(msgs) == 2
    assert msgs[0]["role"] == "user"
    assert msgs[1]["role"] == "assistant"
    assert "当前项目状态正常" in msgs[1]["content"]


def test_delete_session(client, sample_project, monkeypatch):
    """删除会话后列表为空，删除不存在会话返回 404。"""
    monkeypatch.setattr(ChatAgent, "stream_reply", _fake_stream)
    session_id = _send_message(client, sample_project)

    resp = client.delete(f"/api/chat/sessions/{session_id}?project_id={sample_project}")
    assert resp.status_code == 200
    assert resp.json()["deleted"] is True

    resp = client.get(f"/api/chat/sessions?project_id={sample_project}")
    assert resp.json() == []

    resp = client.delete(f"/api/chat/sessions/{session_id}?project_id={sample_project}")
    assert resp.status_code == 404


def test_send_message_object_session(client, sample_project, sample_chapter, monkeypatch):
    """对象级会话（章节）应携带 object_type 与 object_id。"""
    monkeypatch.setattr(ChatAgent, "stream_reply", _fake_stream)
    resp = client.post(
        "/api/chat/messages",
        json={
            "project_id": sample_project,
            "message": "优化本章开头",
            "session_type": "object",
            "object_type": "chapter",
            "object_id": str(sample_chapter),
            "title": f"第{sample_chapter}章讨论",
        },
    )
    assert resp.status_code == 200

    sessions = client.get(f"/api/chat/sessions?project_id={sample_project}").json()
    assert len(sessions) == 1
    assert sessions[0]["session_type"] == "object"
    assert sessions[0]["object_type"] == "chapter"
    assert sessions[0]["object_id"] == str(sample_chapter)
