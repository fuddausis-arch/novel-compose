"""端到端验证：创建项目 → 写设定 → 装配 core memory → 调 LLM（mock）→ 写正文 → 存圣经。"""
import pytest
from unittest.mock import AsyncMock, patch

from novel_agent.bible.database import SessionLocal, set_config
from novel_agent.bible.models import Base, Project
from novel_agent.bible.repository import BibleRepository
from novel_agent.config import Config
from novel_agent.memory.core import CoreMemoryAssembler
from novel_agent.memory.recall import RecallMemory
from novel_agent.protocol.applier import DeltaApplier
from novel_agent.protocol.schemas import Delta, CharacterDelta, SummaryDelta


@pytest.mark.asyncio
async def test_e2e_single_chapter_generation(tmp_config):
    """M1 端到端：能装配上下文、调 LLM（mock）、存正文与摘要。"""
    from novel_agent.bible import database as db_mod
    set_config(tmp_config)
    Base.metadata.create_all(bind=db_mod.engine)
    db = SessionLocal()
    p = Project(title="末日求生", genre="科幻", summary="末日生存",
                style="口语化短句")
    db.add(p); db.commit(); db.refresh(p)
    repo = BibleRepository(db, project_id=p.id)
    applier = DeltaApplier(repo)

    # 1. 建角色（模拟设定组产出）
    applier.apply(Delta(
        target="character", action="create", chapter=0,
        data=CharacterDelta(name="刘洋", role="主角", personality="冷静"),
    ))

    # 2. 装配 core memory
    core = CoreMemoryAssembler(repo)
    ctx = core.assemble(chapter=1)
    assert "刘洋" in ctx

    # 3. mock LLM 生成正文
    mock_text = "刘洋在修理厂修车，警报响起……（第1章正文）"
    with patch("novel_agent.llm.client.LLMClient.generate",
               new=AsyncMock(return_value=mock_text)):
        from novel_agent.llm.client import LLMClient
        from novel_agent.config import LLMConfig
        client = LLMClient(LLMConfig(api_key="sk-mock"))
        generated = await client.generate(f"基于以下设定写第1章：\n{ctx}")

    assert generated == mock_text

    # 4. 存正文
    recall = RecallMemory(tmp_config)
    recall.save_chapter_text(chapter=1, title="无声征召", content=generated)
    assert "刘洋" in recall.read_chapter_text(chapter=1)

    # 5. 存章节摘要（模拟 Summarizer 产出）
    applier.apply(Delta(
        target="chapter_summary", action="create", chapter=1,
        data=SummaryDelta(title="无声征召", word_count=len(generated),
                          core_events="征召事件", characters_present="刘洋"),
    ))
    s = repo.get_chapter_summary(1)
    assert s is not None
    assert s.title == "无声征召"

    db.close()
