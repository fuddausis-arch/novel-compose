"""章节编辑、提交、导出功能测试。"""
from __future__ import annotations

import json
from unittest.mock import patch

from tests.conftest import make_mock_llm_client


def test_save_chapter_text(client, sample_project, sample_chapter):
    """保存并读取章节正文。"""
    resp = client.get(f"/api/chapters/{sample_chapter}/text?project_id={sample_project}")
    assert resp.status_code == 200

    resp = client.put(
        f"/api/chapters/{sample_chapter}/text?project_id={sample_project}",
        json={"title": "第一章（改）", "content": "更新后的正文内容。"},
    )
    assert resp.status_code == 200
    assert resp.json()["saved"] is True

    resp = client.get(f"/api/chapters/{sample_chapter}/text?project_id={sample_project}")
    assert resp.json()["text"] == "更新后的正文内容。"


def test_commit_chapter(client, sample_project, sample_chapter):
    """章节提交：mock commit 所需的 LLM 提取结果。"""
    mock_response = json.dumps(
        {
            "summary": "本章讲述了主角的冒险。",
            "state_deltas": [],
            "relationships": [],
            "events": [],
            "foreshadow_updates": [],
            "new_characters": [],
            "new_factions": [],
            "new_monsters": [],
            "new_world_settings": [],
        },
        ensure_ascii=False,
    )
    with patch("novel_agent.api.routes_generation.LLMClient") as MockLLM:
        MockLLM.return_value = make_mock_llm_client(mock_response)
        resp = client.post(
            "/api/generation/chapter/commit",
            json={"project_id": sample_project, "chapter": sample_chapter},
        )
    assert resp.status_code == 200
    data = resp.json()
    assert data["committed"] is True
    assert data["chapter"] == sample_chapter


def test_export_txt(client, sample_project, sample_chapter):
    """导出全部章节为 TXT。"""
    resp = client.get(f"/api/chapters/export/txt?project_id={sample_project}")
    assert resp.status_code == 200
    assert resp.headers["content-type"] == "text/plain; charset=utf-8"
    assert "第一章正文内容" in resp.text


def test_list_chapters(client, sample_project, sample_chapter):
    """列出项目下章节。"""
    resp = client.get(f"/api/chapters/list?project_id={sample_project}")
    assert resp.status_code == 200
    chapters = resp.json()
    assert any(ch["chapter"] == sample_chapter for ch in chapters)
