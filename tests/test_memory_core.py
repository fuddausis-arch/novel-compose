"""测试 Core memory 装配：每章注入的常驻上下文。"""
import pytest
from unittest.mock import MagicMock

from novel_agent.bible.database import SessionLocal, set_config
from novel_agent.bible.models import Base, Project
from novel_agent.bible.repository import BibleRepository
from novel_agent.memory.core import CoreMemoryAssembler


@pytest.fixture
def repo(tmp_config):
    from novel_agent.bible import database as db_mod
    set_config(tmp_config)
    Base.metadata.create_all(bind=db_mod.engine)
    db = SessionLocal()
    p = Project(title="测试小说", genre="科幻", summary="末日求生",
                style="口语化短句")
    db.add(p); db.commit(); db.refresh(p)
    r = BibleRepository(db, project_id=p.id)
    # 建角色
    r.create_character(name="刘洋", role="主角", personality="冷静",
                       current_location="基地", current_emotion="警觉")
    # 建伏笔
    r.create_foreshadow(foreshadow_id="S-001", tier="short", plant_chapter=1,
                        description="文物箱", status="planted",
                        planned_resolve_chapter=2)
    r.create_foreshadow(foreshadow_id="S-002", tier="short", plant_chapter=2,
                        description="黑市情报", status="pending",
                        planned_resolve_chapter=5)
    yield r
    db.close()


def test_core_memory_assembles_for_chapter(repo):
    assembler = CoreMemoryAssembler(repo)
    ctx = assembler.assemble(chapter=2)
    # 标题
    assert "测试小说" in ctx
    # 当前活跃角色
    assert "刘洋" in ctx
    assert "基地" in ctx  # 当前位置
    # 本章应埋伏笔
    assert "S-002" in ctx
    assert "黑市情报" in ctx
    # 本章应回收伏笔
    assert "S-001" in ctx
    assert "文物箱" in ctx


def test_core_memory_size_capped(repo):
    assembler = CoreMemoryAssembler(repo)
    ctx = assembler.assemble(chapter=2, max_chars=500)
    assert len(ctx) <= 500


def test_core_memory_no_foreshadows_when_none(repo):
    assembler = CoreMemoryAssembler(repo)
    ctx = assembler.assemble(chapter=99)
    assert "本章应埋伏笔" not in ctx
    assert "本章应回收伏笔" not in ctx


def test_core_memory_includes_archival_retrieval(repo):
    """archival 已从热路径移出（阶段Embedding重定位）。

    core 装配时不再调用 archival 检索——archival 是冷路径工具，
    供 DedupScanner/auditor 按需使用，不进写作热路径。
    """
    mock_archival = MagicMock()
    mock_archival.retrieve.return_value = [
        {"content": "第1章：刘洋被征召到火种基地", "chapter": 1, "distance": 0.3},
        {"content": "设定：奇点是异能核心", "chapter": None, "distance": 0.4},
    ]
    assembler = CoreMemoryAssembler(repo, archival=mock_archival)
    ctx = assembler.assemble(chapter=2, query="刘洋的征召经历")
    # archival 已从热路径移出，不应在 core memory 中出现
    assert "刘洋被征召到火种基地" not in ctx
    assert "奇点是异能核心" not in ctx
    # archival.retrieve 不应被调用（冷路径工具，不进 assemble）
    mock_archival.retrieve.assert_not_called()


def test_core_memory_without_archival(repo):
    """未提供 archival 时，core 仍能装配（不注入历史切片）。"""
    assembler = CoreMemoryAssembler(repo)
    ctx = assembler.assemble(chapter=2)
    assert "测试小说" in ctx
    assert "相关历史切片" not in ctx
