"""测试 VolumeRunner：跑规划→人审→resume→写入圣经。"""
import pytest
from unittest.mock import AsyncMock, MagicMock

from novel_agent.bible.database import SessionLocal, set_config
from novel_agent.bible.models import Base, Project
from novel_agent.bible.repository import BibleRepository
from novel_agent.planning.runner import VolumeRunner


@pytest.fixture
def make_runner(tmp_config):
    from novel_agent.bible import database as db_mod
    set_config(tmp_config)
    Base.metadata.create_all(bind=db_mod.engine)
    db = SessionLocal()
    p = Project(title="测试", genre="科幻", summary="末日")
    db.add(p); db.commit(); db.refresh(p)
    r = BibleRepository(db, project_id=p.id)
    runners = []

    def _make(llm_client=None):
        runner = VolumeRunner(tmp_config, repo=r, llm_client=llm_client)
        runners.append(runner)
        return runner

    yield _make
    for rn in runners:
        rn.close()
    db.close()


@pytest.mark.asyncio
async def test_volume_run_interrupts_at_review(make_runner):
    """跑到人审①应 interrupt 挂起。"""
    mock_llm = MagicMock()
    mock_llm.generate = AsyncMock(side_effect=[
        '{"volumes":[{"name":"卷一","chapters":5}]}',  # plan
        '{"characters":[{"name":"刘洋","role":"主角","personality":"冷静"}],"world_settings":[]}',  # design
        '{"chapters":[{"chapter":1,"title":"第一章","summary":"事件","foreshadows":[]}]}',  # outline
    ])
    runner = make_runner(llm_client=mock_llm)

    result = await runner.run(volume="卷一", chapter_count=5, thread_id="v1")
    # interrupt 后 graph 返回当前状态：plan→design 已完成（status=designed），review 挂起
    assert result.get("status") in ("designed", "reviewing")


@pytest.mark.asyncio
async def test_volume_resume_approved_writes_bible(make_runner):
    """人审通过 → resume → 设定/大纲写入圣经。"""
    mock_llm = MagicMock()
    mock_llm.generate = AsyncMock(side_effect=[
        '{"volumes":[{"name":"卷一","chapters":5}]}',
        '{"characters":[{"name":"刘洋","role":"主角","personality":"冷静"}],"world_settings":[]}',
        '{"chapters":[{"chapter":1,"title":"第一章","summary":"事件","foreshadows":[]}]}',
    ])
    runner = make_runner(llm_client=mock_llm)

    await runner.run(volume="卷一", chapter_count=5, thread_id="v2")
    result = await runner.resume({"approved": True}, thread_id="v2")

    assert result.get("status") == "approved"
    # 角色已写入圣经
    assert runner.repo.get_character("刘洋") is not None
    # 大纲已写入
    outlines = runner.repo.list_outlines()
    assert len(outlines) >= 1
