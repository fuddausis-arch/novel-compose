"""测试规划三 agent。"""
import pytest
from unittest.mock import AsyncMock

from novel_agent.planning.agents import Planner, Architect
from novel_agent.bible.database import SessionLocal, set_config
from novel_agent.bible.models import Base, Project
from novel_agent.bible.repository import BibleRepository


@pytest.fixture
def repo(tmp_config):
    from novel_agent.bible import database as db_mod
    set_config(tmp_config)
    Base.metadata.create_all(bind=db_mod.engine)
    db = SessionLocal()
    p = Project(title="末日求生", genre="科幻", summary="末日生存")
    db.add(p); db.commit(); db.refresh(p)
    r = BibleRepository(db, project_id=p.id)
    yield r
    db.close()


@pytest.mark.asyncio
async def test_planner_produces_volume_plan(repo):
    mock_llm = AsyncMock()
    mock_llm.generate = AsyncMock(return_value="""```json
{"volumes":[{"name":"卷一","theme":"生存逃亡","chapters":30,"summary":"主角逃出城市"}]}
```""")
    planner = Planner(mock_llm)
    plan = await planner.plan(project=repo.get_project(), target_chapters=30)
    assert "volumes" in plan
    assert len(plan["volumes"]) >= 1


@pytest.mark.asyncio
async def test_architect_produces_settings(repo):
    mock_llm = AsyncMock()
    mock_llm.generate = AsyncMock(return_value="""```json
{"characters":[{"name":"刘洋","role":"主角","personality":"冷静"}],"world_settings":[{"category":"力量体系","title":"奇点","content":"异能核心"}]}
```""")
    architect = Architect(mock_llm)
    settings = await architect.design(project=repo.get_project(), volume_plan={"volumes":[{"name":"卷一"}]})
    assert "characters" in settings
    assert len(settings["characters"]) >= 1
