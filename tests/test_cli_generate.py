"""测试 CLI generate 子命令。"""
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from novel_agent.bible.models import Base, Project
from novel_agent.config import Config
from novel_agent.cli import cmd_init, cmd_generate


class _Args:
    def __init__(self, title, genre="", summary="", style="", config=None):
        self.title = title
        self.genre = genre
        self.summary = summary
        self.style = style
        self.config = config


class _GenArgs:
    def __init__(self, chapter=1, title="第一章", config=None):
        self.chapter = chapter
        self.title = title
        self.config = config


@pytest.fixture
def isolated_cli(tmp_path, monkeypatch):
    """隔离的 CLI 执行环境：独立内存库，不碰全局。"""
    cfg = Config(project_data_dir=tmp_path / "project_data")
    engine = create_engine("sqlite:///:memory:", future=True)
    Base.metadata.create_all(bind=engine)
    TestSession = sessionmaker(bind=engine, autoflush=False, future=True)

    monkeypatch.setattr("novel_agent.cli.load_config", lambda _: cfg)
    monkeypatch.setattr("novel_agent.cli.set_config", lambda _cfg: None)
    monkeypatch.setattr("novel_agent.cli.SessionLocal", TestSession)
    monkeypatch.setattr("novel_agent.bible.database.engine", engine)

    return TestSession


@pytest.mark.asyncio
async def test_cmd_generate_runs_pipeline(isolated_cli, monkeypatch, capsys):
    """generate 命令应跑通流水线（mock ChapterRunner）。"""
    # 先 init 项目
    cmd_init(_Args(title="生成测试", genre="科幻"))

    # mock ChapterRunner 避免建真实 archival/checkpointer
    class _FakeRunner:
        def __init__(self, *a, **kw):
            pass

        async def run(self, chapter, title):
            return {"status": "completed", "draft": "正文", "word_count": 100}

        def close(self):
            pass

    # generate 内部从 runner 模块 import ChapterRunner，patch 真正的 import 点
    import novel_agent.orchestrator.runner as runner_mod
    monkeypatch.setattr(runner_mod, "ChapterRunner", _FakeRunner)

    await cmd_generate(_GenArgs(chapter=1, title="第一章"))

    out = capsys.readouterr().out
    assert "第一章" in out
    assert "completed" in out


@pytest.mark.asyncio
async def test_cmd_generate_no_project_error(isolated_cli, monkeypatch, capsys):
    """没有项目时 generate 应提示错误，不崩。"""
    # 不 init，直接 generate（库为空）
    await cmd_generate(_GenArgs(chapter=1, title="第一章"))

    out = capsys.readouterr().out
    assert "错误" in out or "没有项目" in out
