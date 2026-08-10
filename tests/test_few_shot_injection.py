import pytest
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock
from novel_agent.orchestrator.nodes import write_chapter
from novel_agent.templates.style_guides.few_shot_samples import get_few_shot_for_beat


@pytest.mark.asyncio
async def test_write_chapter_injects_few_shot_from_outline(tmp_path):
    """write_chapter 必须从本章大纲的 required_beats 中读取 beat_type 并注入 few-shot。

    注：生产环境开启 enable_genre_rag 时，语感检索会用真实小说片段替换 few-shot；
    此测试关闭 genre_rag 以专门验证 few-shot 兜底路径。
    """
    from novel_agent.bible.database import SessionLocal, set_config
    from novel_agent.bible.models import Base, Project
    from novel_agent.config import load_config
    from novel_agent.llm.client import LLMClient
    from novel_agent.bible.repository import BibleRepository

    cfg = load_config()
    set_config(cfg)
    from novel_agent.bible import database as db_mod
    Base.metadata.create_all(bind=db_mod.engine)
    db = SessionLocal()
    proj = Project(title="t", genre="都市异能")
    db.add(proj); db.commit(); db.refresh(proj)
    repo = BibleRepository(db, proj.id)
    repo.create_outline(
        level="chapter", order=1, title="第一章",
        required_beats='[{"tier":"small","type":"打脸","intensity":5}]',
        owed_debts="[]", required_hooks="{}", phase="opening",
    )

    mock_client = MagicMock(spec=LLMClient)
    mock_client.config = MagicMock(temperature=0.8)
    captured_prompt = {}
    async def fake_generate(prompt, system=None, **kwargs):
        captured_prompt["prompt"] = prompt
        return "正文正文。"
    mock_client.generate = fake_generate

    # 关闭 genre_rag，强制走 few-shot 兜底路径（避免 RAG 切片覆盖 few-shot）
    test_cfg = SimpleNamespace(enable_genre_rag=False, allow_auto_expand_chapter=True)

    state = {
        "project_id": proj.id,
        "chapter": 1,
        "title": "第一章",
        "context": "上下文",
        "status": "pending",
    }
    result = await write_chapter(state, mock_client, repo=repo, config=test_cfg)
    assert result["status"] == "drafted"
    assert get_few_shot_for_beat("打脸") in captured_prompt["prompt"]
    db.close()
