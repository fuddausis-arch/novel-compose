"""测试 CLI init 命令。

通过 monkeypatch 隔离全局状态：cmd_init 内部调用的 set_config/load_config/
SessionLocal/engine 全部替换为测试控制的版本，避免污染其他测试的全局 engine。
"""
import pytest

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from novel_agent.bible.models import Base, Project
from novel_agent.config import Config
from novel_agent.cli import cmd_init


class _Args:
    """模拟 argparse Namespace。"""
    def __init__(self, title, genre="", summary="", style="", config=None):
        self.title = title
        self.genre = genre
        self.summary = summary
        self.style = style
        self.config = config


@pytest.fixture
def isolated_cli(tmp_path, monkeypatch):
    """隔离的 CLI 执行环境：独立内存库，不碰全局。"""
    cfg = Config(project_data_dir=tmp_path / "project_data")
    engine = create_engine("sqlite:///:memory:", future=True)
    Base.metadata.create_all(bind=engine)
    TestSession = sessionmaker(bind=engine, autoflush=False, future=True)

    # 替换 cli 模块内的全局引用
    monkeypatch.setattr("novel_agent.cli.load_config", lambda _: cfg)
    monkeypatch.setattr("novel_agent.cli.set_config", lambda _cfg: None)
    monkeypatch.setattr("novel_agent.cli.SessionLocal", TestSession)
    # cli.cmd_init 内部 `from novel_agent.bible import database as db_mod`
    # 然后 db_mod.engine；monkeypatch database 模块的 engine
    monkeypatch.setattr("novel_agent.bible.database.engine", engine)

    return TestSession


def test_cmd_init_creates_project(isolated_cli, capsys):
    """init 命令应创建项目并写入。"""
    cmd_init(_Args(title="测试小说", genre="科幻", summary="测试用"))

    db = isolated_cli()
    projects = db.query(Project).all()
    db.close()
    assert len(projects) == 1
    p = projects[0]
    assert p.title == "测试小说"
    assert p.genre == "科幻"
    assert p.summary == "测试用"
    out = capsys.readouterr().out
    assert "测试小说" in out
    assert "id=" in out


def test_cmd_init_default_empty_fields(isolated_cli):
    """未提供的字段应默认为空串。"""
    cmd_init(_Args(title="极简项目"))

    db = isolated_cli()
    projects = db.query(Project).all()
    db.close()
    assert len(projects) == 1
    p = projects[0]
    assert p.title == "极简项目"
    assert p.genre == ""
    assert p.summary == ""
