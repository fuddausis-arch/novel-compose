# M1：地基与记忆层 实现计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 搭建多 agent 小说生成系统的地基——项目骨架、圣经数据层（9 库 + 事件流）、三层记忆读写、LLM 客户端、JSON delta 写入协议。M1 结束时不涉及 agent 编排，但能创建项目、读写圣经、校验 delta、调用 LLM 生成文本。

**Architecture:** Python 单仓。`bible/` 包负责结构化记忆（SQLAlchemy ORM + SQLite），`memory/` 包负责三层记忆读写（core 装配 / archival 向量检索 / summary tree / recall），`llm/` 包负责 OpenAI 兼容客户端，`protocol/` 负责 JSON delta 校验与 apply。配置与项目数据落 `project_data/`。

**Tech Stack:** Python 3.11+、SQLAlchemy 2.0、SQLite、Chroma（向量库）、pydantic 2、httpx、pytest、pytest-asyncio

---

## 文件结构（M1 范围）

```
vibe coding/                          # 项目根（覆盖旧 Electron 项目）
├── docs/superpowers/specs/           # 保留：spec
├── .study/                           # 保留：参考项目
├── multi-agent-code-generator-project.md  # 保留：项目书
├── pyproject.toml                    # 新建：项目元数据 + 依赖
├── .gitignore                        # 新建
├── README.md                         # 新建
├── novel_agent/                      # 新建：主包
│   ├── __init__.py
│   ├── config.py                     # 配置加载（env + yaml）
│   ├── bible/                        # 圣经数据层
│   │   ├── __init__.py
│   │   ├── models.py                 # 9 库 ORM 模型 + 事件流表
│   │   ├── database.py               # engine + session + 建表
│   │   └── repository.py             # CRUD 仓储
│   ├── memory/                       # 三层记忆
│   │   ├── __init__.py
│   │   ├── core.py                   # Core memory 装配（每章注入上下文）
│   │   ├── archival.py               # Archival 向量检索（Chroma）
│   │   ├── summary_tree.py           # 章→弧→卷→全书 摘要树
│   │   └── recall.py                 # 全量原文 + 事件时间线查询
│   ├── protocol/                     # JSON delta 协议
│   │   ├── __init__.py
│   │   ├── schemas.py                # pydantic delta schema（按库）
│   │   └── applier.py                # 校验 + immutable apply + 事件流追加
│   ├── llm/                          # LLM 客户端
│   │   ├── __init__.py
│   │   └── client.py                 # OpenAI 兼容客户端 + 重试/降级/超时
│   └── cli.py                        # 命令行入口（init/generate 等）
├── tests/                            # 测试
│   ├── conftest.py                   # pytest fixtures（临时 db、临时项目）
│   ├── test_bible_models.py
│   ├── test_repository.py
│   ├── test_protocol_applier.py
│   ├── test_memory_core.py
│   ├── test_memory_archival.py
│   ├── test_memory_summary_tree.py
│   ├── test_memory_recall.py
│   └── test_llm_client.py
└── project_data/                     # 运行时数据（gitignore）
    └── .gitkeep
```

---

## Task 1: 清理旧代码并初始化 git

**Files:**
- Delete: `main.js`, `preload.js`, `package.json`, `package-lock.json`, `node_modules/`, `frontend/`, `backend/`
- Keep: `docs/`, `.study/`, `multi-agent-code-generator-project.md`

- [ ] **Step 1: 删除旧 Electron 项目文件**

```bash
cd "C:\Users\LYY\Desktop\vibe coding"
del main.js preload.js package.json package-lock.json
rmdir /s /q node_modules
rmdir /s /q frontend
rmdir /s /q backend
```

- [ ] **Step 2: 确认保留文件仍在**

```bash
dir docs .study multi-agent-code-generator-project.md
```
Expected: 三者都在

- [ ] **Step 3: 初始化 git 仓库**

```bash
cd "C:\Users\LYY\Desktop\vibe coding"
git init
git branch -m main
```

- [ ] **Step 4: 创建 .gitignore**

文件内容：
```gitignore
# Python
__pycache__/
*.py[cod]
*.egg-info/
.eggs/
build/
dist/
.venv/
venv/
env/

# 项目运行时数据
project_data/*
!project_data/.gitkeep

# IDE
.vscode/
.idea/
*.swp

# OS
.DS_Store
Thumbs.db

# 测试
.pytest_cache/
.coverage
htmlcov/
```

- [ ] **Step 5: 首次提交**

```bash
git add .
git commit -m "chore: 清理旧 Electron 项目，初始化新仓库"
```

---

## Task 2: Python 项目骨架与依赖

**Files:**
- Create: `pyproject.toml`, `novel_agent/__init__.py`, `novel_agent/config.py`, `README.md`, `project_data/.gitkeep`, `tests/conftest.py`

- [ ] **Step 1: 创建 pyproject.toml**

```toml
[project]
name = "novel-agent"
version = "0.1.0"
description = "多 Agent 自动小说生成系统"
requires-python = ">=3.11"
dependencies = [
    "sqlalchemy>=2.0.30",
    "pydantic>=2.7",
    "httpx>=0.27",
    "chromadb>=0.5.0",
    "pyyaml>=6.0",
    "python-dotenv>=1.0",
]

[project.optional-dependencies]
dev = [
    "pytest>=8.0",
    "pytest-asyncio>=0.23",
    "pytest-cov>=5.0",
]

[project.scripts]
novel-agent = "novel_agent.cli:main"

[build-system]
requires = ["setuptools>=68"]
build-backend = "setuptools.build_meta"

[tool.setuptools.packages.find]
include = ["novel_agent*"]

[tool.pytest.ini_options]
asyncio_mode = "auto"
testpaths = ["tests"]
```

- [ ] **Step 2: 创建虚拟环境并安装**

```bash
cd "C:\Users\LYY\Desktop\vibe coding"
python -m venv .venv
.venv\Scripts\activate
pip install -e ".[dev]"
```
Expected: 安装成功，`novel-agent` 命令可用（虽然 cli 还没写，先确认入口注册）

- [ ] **Step 3: 创建 novel_agent/__init__.py**

```python
"""多 Agent 自动小说生成系统。"""

__version__ = "0.1.0"
```

- [ ] **Step 4: 创建 novel_agent/config.py**

```python
"""配置加载：env 优先，yaml 补充。"""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

import yaml


@dataclass
class LLMConfig:
    base_url: str = "https://api.openai.com/v1"
    api_key: str = ""
    model: str = "gpt-4o-mini"
    temperature: float = 0.7
    max_tokens: int = 4000
    timeout: float = 180.0


@dataclass
class Config:
    project_data_dir: Path = Path("project_data")
    llm: LLMConfig = field(default_factory=LLMConfig)

    @property
    def bible_db_path(self) -> Path:
        return self.project_data_dir / "bible.db"

    @property
    def chroma_dir(self) -> Path:
        return self.project_data_dir / "chroma"

    @property
    def chapters_dir(self) -> Path:
        return self.project_data_dir / "chapters"


def load_config(yaml_path: Path | None = None) -> Config:
    """加载配置。yaml 文件可选，env 变量覆盖。"""
    cfg = Config()
    if yaml_path and yaml_path.exists():
        with open(yaml_path, encoding="utf-8") as f:
            data = yaml.safe_load(f) or {}
        if "project_data_dir" in data:
            cfg.project_data_dir = Path(data["project_data_dir"])
        llm_data = data.get("llm", {})
        cfg.llm = LLMConfig(
            base_url=llm_data.get("base_url", cfg.llm.base_url),
            api_key=llm_data.get("api_key", cfg.llm.api_key),
            model=llm_data.get("model", cfg.llm.model),
            temperature=llm_data.get("temperature", cfg.llm.temperature),
            max_tokens=llm_data.get("max_tokens", cfg.llm.max_tokens),
            timeout=llm_data.get("timeout", cfg.llm.timeout),
        )
    # env 覆盖
    cfg.llm.api_key = os.getenv("NOVEL_LLM_API_KEY", cfg.llm.api_key)
    cfg.llm.base_url = os.getenv("NOVEL_LLM_BASE_URL", cfg.llm.base_url)
    cfg.llm.model = os.getenv("NOVEL_LLM_MODEL", cfg.llm.model)
    return cfg
```

- [ ] **Step 5: 创建 tests/conftest.py**

```python
"""pytest 共享 fixtures。"""
from __future__ import annotations

import tempfile
from pathlib import Path

import pytest

from novel_agent.config import Config


@pytest.fixture
def tmp_config(tmp_path: Path) -> Config:
    """临时项目数据目录的配置。"""
    return Config(project_data_dir=tmp_path / "project_data")
```

- [ ] **Step 6: 创建 README.md**

```markdown
# 多 Agent 自动小说生成系统

基于 LangGraph 的多 agent 网文自动生成系统，目标 200 万字长篇。

## 开发

```bash
python -m venv .venv
.venv\Scripts\activate
pip install -e ".[dev]"
pytest
```

## 文档

- 设计 spec: `docs/superpowers/specs/2026-06-17-multi-agent-novel-generator-design.md`
```

- [ ] **Step 7: 创建 project_data/.gitkeep**

空文件，确保目录被 git 跟踪。

- [ ] **Step 8: 验证安装与导入**

```bash
python -c "from novel_agent.config import load_config; print(load_config())"
pytest
```
Expected: 配置打印无报错；pytest 运行 0 测试无错误

- [ ] **Step 9: Commit**

```bash
git add .
git commit -m "feat: 项目骨架与依赖配置"
```

---

## Task 3: 圣经数据层 — ORM 模型（9 库 + 事件流）

**Files:**
- Create: `novel_agent/bible/__init__.py`, `novel_agent/bible/models.py`
- Test: `tests/test_bible_models.py`

- [ ] **Step 1: 写失败测试 tests/test_bible_models.py**

```python
"""测试 ORM 模型能正确建表。"""
from sqlalchemy import inspect

from novel_agent.bible.database import engine
from novel_agent.bible.models import (
    Base, Project, Character, WorldSetting, Outline,
    Foreshadow, ForeshadowImplant, ChapterSummary,
    EmotionArc, SubplotBoard, CharacterMatrix, TruthEvent,
)


def test_all_tables_created():
    """所有 9 库 + 事件流 + project 表应被创建。"""
    Base.metadata.create_all(bind=engine)
    inspector = inspect(engine)
    tables = set(inspector.get_table_names())
    expected = {
        "projects", "characters", "world_settings", "outlines",
        "foreshadows", "foreshadow_implants", "chapter_summaries",
        "emotion_arcs", "subplot_board", "character_matrix",
        "truth_events",
    }
    assert expected.issubset(tables), f"缺失表: {expected - tables}"


def test_truth_event_columns():
    """事件流表应有 chapter/type/entity_id/payload/timestamp。"""
    Base.metadata.create_all(bind=engine)
    inspector = inspect(engine)
    cols = {c["name"] for c in inspector.get_columns("truth_events")}
    assert {"id", "chapter", "type", "entity_id", "payload", "timestamp"}.issubset(cols)


def test_foreshadow_status_column():
    """伏笔表应有 status 字段。"""
    Base.metadata.create_all(bind=engine)
    inspector = inspect(engine)
    cols = {c["name"] for c in inspector.get_columns("foreshadows")}
    assert "status" in cols
```

- [ ] **Step 2: 运行测试验证失败**

```bash
pytest tests/test_bible_models.py -v
```
Expected: FAIL（模块不存在）

- [ ] **Step 3: 创建 novel_agent/bible/__init__.py**

```python
"""圣经数据层：结构化权威状态。"""
```

- [ ] **Step 4: 创建 novel_agent/bible/models.py**

```python
"""圣经 ORM 模型：9 库 + 事件流表。

对应 spec 第 2.2 节。所有时间戳用 UTC。
"""
from __future__ import annotations

from datetime import datetime

from sqlalchemy import (
    Column, Integer, String, Text, DateTime, ForeignKey, JSON, Float,
)
from sqlalchemy.orm import DeclarativeBase, relationship


class Base(DeclarativeBase):
    pass


class Project(Base):
    """小说项目元信息。"""
    __tablename__ = "projects"

    id = Column(Integer, primary_key=True, index=True)
    title = Column(String(200), nullable=False)
    genre = Column(String(100), default="")
    summary = Column(Text, default="")
    style = Column(Text, default="")
    constitution = Column(Text, default="")
    target_audience = Column(String(200), default="")
    word_count_target = Column(Integer, default=0)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class Character(Base):
    """角色卡（对应「主要人物卡」）。"""
    __tablename__ = "characters"

    id = Column(Integer, primary_key=True, index=True)
    project_id = Column(Integer, ForeignKey("projects.id"), nullable=False, index=True)
    name = Column(String(100), nullable=False)
    role = Column(String(50), default="")          # 主角/配角/反派
    age = Column(String(50), default="")
    gender = Column(String(20), default="")
    appearance = Column(Text, default="")
    background = Column(Text, default="")
    personality = Column(Text, default="")
    motivation = Column(Text, default="")
    # 动态状态（每章 diff 更新）
    current_location = Column(String(200), default="")
    current_emotion = Column(String(100), default="")
    known_info = Column(Text, default="")          # 角色已知信息（信息边界）
    arc = Column(Text, default="")
    relationships = Column(Text, default="")
    secrets = Column(Text, default="")
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class WorldSetting(Base):
    """世界设定（对应「核心设定」）。"""
    __tablename__ = "world_settings"

    id = Column(Integer, primary_key=True, index=True)
    project_id = Column(Integer, ForeignKey("projects.id"), nullable=False, index=True)
    category = Column(String(50), default="")      # 世界观/力量体系/势力/地点/规则
    title = Column(String(200), default="")
    content = Column(Text, default="")
    order = Column(Integer, default=0)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class Outline(Base):
    """大纲：卷→弧→章三级（对应「细纲」）。"""
    __tablename__ = "outlines"

    id = Column(Integer, primary_key=True, index=True)
    project_id = Column(Integer, ForeignKey("projects.id"), nullable=False, index=True)
    level = Column(String(20), nullable=False)     # volume / arc / chapter
    parent_id = Column(Integer, ForeignKey("outlines.id"), nullable=True)
    order = Column(Integer, default=0)
    act = Column(String(50), default="")           # 开端/发展/高潮/结局 或 卷名
    title = Column(String(200), default="")
    summary = Column(Text, default="")
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class Foreshadow(Base):
    """伏笔台账（对应「伏笔与道具追踪」）。"""
    __tablename__ = "foreshadows"

    id = Column(Integer, primary_key=True, index=True)
    project_id = Column(Integer, ForeignKey("projects.id"), nullable=False, index=True)
    foreshadow_id = Column(String(20), nullable=False, index=True)  # S-001 / M-001 / L-001
    tier = Column(String(10), default="")          # short / medium / long
    plant_chapter = Column(Integer, default=0)
    description = Column(Text, default="")
    depends_on = Column(Text, default="")          # 依赖的其他伏笔 id
    status = Column(String(20), default="pending")  # pending/planted/developing/resolved/abandoned
    planned_resolve_chapter = Column(Integer, default=0)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class ForeshadowImplant(Base):
    """伏笔植入方案（对应「核心伏笔早期植入方案」）。"""
    __tablename__ = "foreshadow_implants"

    id = Column(Integer, primary_key=True, index=True)
    project_id = Column(Integer, ForeignKey("projects.id"), nullable=False, index=True)
    foreshadow_id = Column(String(20), nullable=False, index=True)
    chapter = Column(Integer, default=0)
    implant_method = Column(Text, default="")
    created_at = Column(DateTime, default=datetime.utcnow)


class ChapterSummary(Base):
    """章节摘要历史。"""
    __tablename__ = "chapter_summaries"

    id = Column(Integer, primary_key=True, index=True)
    project_id = Column(Integer, ForeignKey("projects.id"), nullable=False, index=True)
    chapter = Column(Integer, nullable=False, index=True)
    title = Column(String(200), default="")
    time_location = Column(String(500), default="")
    core_events = Column(Text, default="")
    characters_present = Column(Text, default="")
    emotion_changes = Column(Text, default="")
    foreshadow_dynamics = Column(Text, default="")
    subplot_progress = Column(Text, default="")
    chapter_hook = Column(Text, default="")
    word_count = Column(Integer, default=0)
    created_at = Column(DateTime, default=datetime.utcnow)


class EmotionArc(Base):
    """情感弧线追踪。"""
    __tablename__ = "emotion_arcs"

    id = Column(Integer, primary_key=True, index=True)
    project_id = Column(Integer, ForeignKey("projects.id"), nullable=False, index=True)
    character_name = Column(String(100), nullable=False, index=True)
    chapter = Column(Integer, nullable=False)
    event = Column(Text, default="")
    emotion_before = Column(String(100), default="")
    emotion_after = Column(String(100), default="")
    growth = Column(Text, default="")
    created_at = Column(DateTime, default=datetime.utcnow)


class SubplotBoard(Base):
    """支线进度板。"""
    __tablename__ = "subplot_board"

    id = Column(Integer, primary_key=True, index=True)
    project_id = Column(Integer, ForeignKey("projects.id"), nullable=False, index=True)
    name = Column(String(200), nullable=False)
    is_main = Column(Integer, default=0)           # 1=主线 0=支线
    status = Column(String(50), default="active")  # active/paused/resolved
    progress = Column(Integer, default=0)          # 0-100
    related_characters = Column(Text, default="")
    next_goal = Column(Text, default="")
    planned_resolve_chapter = Column(Integer, default=0)
    updated_chapter = Column(Integer, default=0)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class CharacterMatrix(Base):
    """角色交互矩阵：相遇记录/知识边界/信息传播。"""
    __tablename__ = "character_matrix"

    id = Column(Integer, primary_key=True, index=True)
    project_id = Column(Integer, ForeignKey("projects.id"), nullable=False, index=True)
    chapter = Column(Integer, nullable=False)
    character_a = Column(String(100), nullable=False)
    character_b = Column(String(100), default="")
    interaction_type = Column(String(50), default="")  # meeting/conflict/cooperation/info_share
    info_exchanged = Column(Text, default="")
    relationship_change = Column(Text, default="")
    created_at = Column(DateTime, default=datetime.utcnow)


class TruthEvent(Base):
    """事件流：不可变追加，支持 time-travel 查询（spec 2.3）。"""
    __tablename__ = "truth_events"

    id = Column(Integer, primary_key=True, index=True)
    project_id = Column(Integer, ForeignKey("projects.id"), nullable=False, index=True)
    chapter = Column(Integer, nullable=False, index=True)
    type = Column(String(50), nullable=False)      # foreshadow_planted/foreshadow_resolved/
                                                   # character_state_change/resource_change/
                                                   # relationship_change/timeline_event
    entity_id = Column(String(100), default="")    # 伏笔id/角色名/物品名
    payload = Column(JSON, default=dict)
    timestamp = Column(DateTime, default=datetime.utcnow, index=True)
```

- [ ] **Step 5: 创建 novel_agent/bible/database.py**

```python
"""圣经数据库 engine + session。

测试用内存 SQLite，生产用文件 SQLite。通过环境变量切换。
"""
from __future__ import annotations

import os

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from novel_agent.models_stub import _PROJECT_DATA_DIR  # 见 Step 6 说明


def _get_db_url() -> str:
    """测试环境用内存库，否则用文件。"""
    if os.getenv("NOVEL_TEST_DB") == "memory":
        return "sqlite:///:memory:"
    db_path = _PROJECT_DATA_DIR() / "bible.db"
    db_path.parent.mkdir(parents=True, exist_ok=True)
    return f"sqlite:///{db_path}"


engine = create_engine(_get_db_url(), echo=False, future=True)
SessionLocal = sessionmaker(bind=engine, autoflush=False, future=True)
```

- [ ] **Step 6: 创建 novel_agent/models_stub.py（临时，Task 5 会并入 config）**

> 说明：database.py 需要知道 project_data 路径。M1 暂用 stub，避免循环依赖；Task 5 重构时合并进 config。

```python
"""临时桥接：提供 project_data 路径。Task 5 会重构进 config。"""
from __future__ import annotations

import os
from pathlib import Path


def _PROJECT_DATA_DIR() -> Path:
    return Path(os.getenv("NOVEL_PROJECT_DATA", "project_data"))
```

- [ ] **Step 7: 运行测试**

```bash
set NOVEL_TEST_DB=memory
pytest tests/test_bible_models.py -v
```
Expected: 3 个测试 PASS

- [ ] **Step 8: Commit**

```bash
git add .
git commit -m "feat(bible): 9 库 ORM 模型 + 事件流表"
```

---

## Task 4: 圣经仓储层 — CRUD

**Files:**
- Create: `novel_agent/bible/repository.py`
- Test: `tests/test_repository.py`

- [ ] **Step 1: 写失败测试 tests/test_repository.py**

```python
"""测试仓储 CRUD。"""
import pytest

from novel_agent.bible.database import SessionLocal, engine
from novel_agent.bible.models import Base, Project, Character, Foreshadow, TruthEvent
from novel_agent.bible.repository import BibleRepository


@pytest.fixture
def repo():
    Base.metadata.create_all(bind=engine)
    db = SessionLocal()
    # 建一个项目
    p = Project(title="测试小说", genre="科幻")
    db.add(p)
    db.commit()
    db.refresh(p)
    yield BibleRepository(db, project_id=p.id)
    db.close()


def test_create_character(repo):
    c = repo.create_character(name="刘洋", role="主角", personality="冷静")
    assert c.id is not None
    assert c.name == "刘洋"


def test_create_foreshadow(repo):
    f = repo.create_foreshadow(
        foreshadow_id="S-001", tier="short", plant_chapter=1,
        description="修理厂地下室神秘文物箱", planned_resolve_chapter=3,
    )
    assert f.status == "pending"
    assert f.foreshadow_id == "S-001"


def test_update_foreshadow_status(repo):
    f = repo.create_foreshadow(foreshadow_id="S-001", tier="short", plant_chapter=1)
    repo.update_foreshadow_status("S-001", "planted")
    f2 = repo.get_foreshadow("S-001")
    assert f2.status == "planted"


def test_append_truth_event(repo):
    repo.append_event(chapter=1, type="foreshadow_planted", entity_id="S-001",
                      payload={"method": "对话暗示"})
    events = repo.list_events(chapter=1)
    assert len(events) == 1
    assert events[0].type == "foreshadow_planted"
    assert events[0].payload["method"] == "对话暗示"


def test_get_pending_foreshadows(repo):
    repo.create_foreshadow(foreshadow_id="S-001", tier="short", plant_chapter=1)
    repo.create_foreshadow(foreshadow_id="S-002", tier="short", plant_chapter=2)
    repo.update_foreshadow_status("S-001", "planted")
    pending = repo.get_foreshadows_by_status("pending")
    assert len(pending) == 1
    assert pending[0].foreshadow_id == "S-002"
```

- [ ] **Step 2: 运行验证失败**

```bash
set NOVEL_TEST_DB=memory
pytest tests/test_repository.py -v
```
Expected: FAIL（BibleRepository 不存在）

- [ ] **Step 3: 创建 novel_agent/bible/repository.py**

```python
"""圣经仓储：CRUD 封装。所有写操作经此层，便于后续加校验/事件。"""
from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy.orm import Session

from novel_agent.bible.models import (
    Character, Foreshadow, TruthEvent, ChapterSummary,
    EmotionArc, SubplotBoard, CharacterMatrix, WorldSetting, Outline,
    ForeshadowImplant, Project,
)


class BibleRepository:
    """单项目的圣经读写入口。"""

    def __init__(self, db: Session, project_id: int):
        self.db = db
        self.project_id = project_id

    # ---- 项目 ----
    def get_project(self) -> Project | None:
        return self.db.query(Project).filter(Project.id == self.project_id).first()

    # ---- 角色 ----
    def create_character(self, **kwargs) -> Character:
        c = Character(project_id=self.project_id, **kwargs)
        self.db.add(c)
        self.db.commit()
        self.db.refresh(c)
        return c

    def list_characters(self) -> list[Character]:
        return self.db.query(Character).filter(
            Character.project_id == self.project_id
        ).all()

    def get_character(self, name: str) -> Character | None:
        return self.db.query(Character).filter(
            Character.project_id == self.project_id,
            Character.name == name,
        ).first()

    def update_character(self, name: str, **kwargs) -> Character | None:
        c = self.get_character(name)
        if not c:
            return None
        for k, v in kwargs.items():
            if hasattr(c, k):
                setattr(c, k, v)
        self.db.commit()
        self.db.refresh(c)
        return c

    # ---- 伏笔 ----
    def create_foreshadow(self, **kwargs) -> Foreshadow:
        f = Foreshadow(project_id=self.project_id, **kwargs)
        self.db.add(f)
        self.db.commit()
        self.db.refresh(f)
        return f

    def get_foreshadow(self, foreshadow_id: str) -> Foreshadow | None:
        return self.db.query(Foreshadow).filter(
            Foreshadow.project_id == self.project_id,
            Foreshadow.foreshadow_id == foreshadow_id,
        ).first()

    def update_foreshadow_status(self, foreshadow_id: str, status: str) -> Foreshadow | None:
        f = self.get_foreshadow(foreshadow_id)
        if not f:
            return None
        f.status = status
        self.db.commit()
        self.db.refresh(f)
        return f

    def get_foreshadows_by_status(self, status: str) -> list[Foreshadow]:
        return self.db.query(Foreshadow).filter(
            Foreshadow.project_id == self.project_id,
            Foreshadow.status == status,
        ).all()

    def get_foreshadows_to_plant(self, chapter: int) -> list[Foreshadow]:
        """取本章应埋设的伏笔（plant_chapter 匹配且未埋）。"""
        return self.db.query(Foreshadow).filter(
            Foreshadow.project_id == self.project_id,
            Foreshadow.plant_chapter == chapter,
            Foreshadow.status.in_(["pending", "planted"]),
        ).all()

    def get_foreshadows_to_resolve(self, chapter: int) -> list[Foreshadow]:
        """取本章应回收的伏笔。"""
        return self.db.query(Foreshadow).filter(
            Foreshadow.project_id == self.project_id,
            Foreshadow.planned_resolve_chapter == chapter,
            Foreshadow.status.in_(["planted", "developing"]),
        ).all()

    # ---- 事件流 ----
    def append_event(self, chapter: int, type: str, entity_id: str = "",
                     payload: dict | None = None) -> TruthEvent:
        ev = TruthEvent(
            project_id=self.project_id, chapter=chapter, type=type,
            entity_id=entity_id, payload=payload or {},
        )
        self.db.add(ev)
        self.db.commit()
        self.db.refresh(ev)
        return ev

    def list_events(self, chapter: int | None = None, entity_id: str | None = None) -> list[TruthEvent]:
        q = self.db.query(TruthEvent).filter(TruthEvent.project_id == self.project_id)
        if chapter is not None:
            q = q.filter(TruthEvent.chapter == chapter)
        if entity_id is not None:
            q = q.filter(TruthEvent.entity_id == entity_id)
        return q.order_by(TruthEvent.timestamp).all()

    # ---- 章节摘要 ----
    def create_chapter_summary(self, **kwargs) -> ChapterSummary:
        s = ChapterSummary(project_id=self.project_id, **kwargs)
        self.db.add(s)
        self.db.commit()
        self.db.refresh(s)
        return s

    def get_chapter_summary(self, chapter: int) -> ChapterSummary | None:
        return self.db.query(ChapterSummary).filter(
            ChapterSummary.project_id == self.project_id,
            ChapterSummary.chapter == chapter,
        ).first()

    def list_chapter_summaries(self, limit: int = 10) -> list[ChapterSummary]:
        return self.db.query(ChapterSummary).filter(
            ChapterSummary.project_id == self.project_id,
        ).order_by(ChapterSummary.chapter.desc()).limit(limit).all()

    # ---- 大纲 ----
    def create_outline(self, **kwargs) -> Outline:
        o = Outline(project_id=self.project_id, **kwargs)
        self.db.add(o)
        self.db.commit()
        self.db.refresh(o)
        return o

    def list_outlines(self, level: str | None = None) -> list[Outline]:
        q = self.db.query(Outline).filter(Outline.project_id == self.project_id)
        if level:
            q = q.filter(Outline.level == level)
        return q.order_by(Outline.order).all()
```

- [ ] **Step 4: 运行测试**

```bash
set NOVEL_TEST_DB=memory
pytest tests/test_repository.py -v
```
Expected: 5 个测试 PASS

- [ ] **Step 5: Commit**

```bash
git add .
git commit -m "feat(bible): 仓储层 CRUD + 事件流追加"
```

---

## Task 5: 重构 database.py 使用 Config（消除 stub）

**Files:**
- Modify: `novel_agent/bible/database.py`, `novel_agent/models_stub.py`
- Delete: `novel_agent/models_stub.py`
- Test: `tests/test_repository.py`（已有，应仍通过）

- [ ] **Step 1: 重写 novel_agent/bible/database.py**

```python
"""圣经数据库 engine + session。

通过 Config 决定路径；测试用 NOVEL_TEST_DB=memory 切内存库。
"""
from __future__ import annotations

import os
from pathlib import Path

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from novel_agent.config import Config, load_config

_config: Config | None = None


def get_config() -> Config:
    global _config
    if _config is None:
        _config = load_config()
    return _config


def set_config(cfg: Config) -> None:
    """测试/编排层注入配置用。"""
    global _config, engine, SessionLocal
    _config = cfg
    engine = create_engine(_get_db_url(), echo=False, future=True)
    SessionLocal = sessionmaker(bind=engine, autoflush=False, future=True)


def _get_db_url() -> str:
    if os.getenv("NOVEL_TEST_DB") == "memory":
        return "sqlite:///:memory:"
    cfg = get_config()
    db_path = cfg.bible_db_path
    db_path.parent.mkdir(parents=True, exist_ok=True)
    return f"sqlite:///{db_path}"


engine = create_engine(_get_db_url(), echo=False, future=True)
SessionLocal = sessionmaker(bind=engine, autoflush=False, future=True)
```

- [ ] **Step 2: 删除 novel_agent/models_stub.py**

```bash
del novel_agent\models_stub.py
```

- [ ] **Step 3: 运行全部测试确认无回归**

```bash
set NOVEL_TEST_DB=memory
pytest -v
```
Expected: 全部 PASS

- [ ] **Step 4: Commit**

```bash
git add .
git commit -m "refactor(bible): database 使用 Config，移除 stub"
```

---

## Task 6: JSON delta 协议 — schemas

**Files:**
- Create: `novel_agent/protocol/__init__.py`, `novel_agent/protocol/schemas.py`
- Test: `tests/test_protocol_schemas.py`

- [ ] **Step 1: 写失败测试 tests/test_protocol_schemas.py**

```python
"""测试 delta schema 校验。"""
import pytest
from pydantic import ValidationError

from novel_agent.protocol.schemas import (
    Delta, ForeshadowDelta, CharacterDelta, SummaryDelta,
)


def test_foreshadow_plant_delta_valid():
    d = Delta(
        target="foreshadow",
        action="plant",
        chapter=3,
        data=ForeshadowDelta(foreshadow_id="S-001", description="神秘文物箱"),
    )
    assert d.action == "plant"


def test_foreshadow_delta_missing_id_rejected():
    with pytest.raises(ValidationError):
        ForeshadowDelta(description="缺 id")


def test_character_state_change_valid():
    d = Delta(
        target="character",
        action="state_change",
        chapter=5,
        data=CharacterDelta(name="刘洋", current_emotion="愤怒", current_location="基地"),
    )
    assert d.data.name == "刘洋"


def test_summary_delta_valid():
    d = Delta(
        target="chapter_summary",
        action="create",
        chapter=1,
        data=SummaryDelta(title="无声征召", word_count=1500, core_events="征召事件"),
    )
    assert d.data.word_count == 1500


def test_delta_invalid_target_rejected():
    with pytest.raises(ValidationError):
        Delta(target="invalid", action="x", chapter=1, data={})


def test_delta_invalid_action_rejected():
    with pytest.raises(ValidationError):
        Delta(target="foreshadow", action="teleport", chapter=1,
              data=ForeshadowDelta(foreshadow_id="S-001"))
```

- [ ] **Step 2: 运行验证失败**

```bash
pytest tests/test_protocol_schemas.py -v
```
Expected: FAIL（模块不存在）

- [ ] **Step 3: 创建 novel_agent/protocol/__init__.py**

```python
"""JSON delta 协议：agent 产出的结构化变更。"""
```

- [ ] **Step 4: 创建 novel_agent/protocol/schemas.py**

```python
"""Delta schema：agent 产出 → 校验 → apply 的契约。

spec 2.4：模型只输出 JSON delta，pydantic 校验后 immutable apply。
"""
from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field


class ForeshadowDelta(BaseModel):
    foreshadow_id: str
    description: str = ""
    tier: str = ""
    plant_chapter: int = 0
    planned_resolve_chapter: int = 0
    depends_on: str = ""
    implant_method: str = ""


class CharacterDelta(BaseModel):
    name: str
    role: str = ""
    personality: str = ""
    motivation: str = ""
    current_location: str = ""
    current_emotion: str = ""
    known_info: str = ""


class SummaryDelta(BaseModel):
    title: str = ""
    word_count: int = 0
    time_location: str = ""
    core_events: str = ""
    characters_present: str = ""
    emotion_changes: str = ""
    foreshadow_dynamics: str = ""
    subplot_progress: str = ""
    chapter_hook: str = ""


class OutlineDelta(BaseModel):
    level: Literal["volume", "arc", "chapter"]
    order: int = 0
    act: str = ""
    title: str = ""
    summary: str = ""


class Delta(BaseModel):
    """单个 delta 操作。"""
    target: Literal["foreshadow", "character", "chapter_summary",
                    "outline", "emotion_arc", "subplot", "character_matrix",
                    "world_setting"]
    action: Literal["create", "update", "plant", "develop", "resolve",
                    "state_change", "delete"]
    chapter: int
    data: dict | BaseModel = Field(default_factory=dict)
    notes: str = ""
```

- [ ] **Step 5: 运行测试**

```bash
pytest tests/test_protocol_schemas.py -v
```
Expected: 6 个测试 PASS

- [ ] **Step 6: Commit**

```bash
git add .
git commit -m "feat(protocol): JSON delta pydantic schemas"
```

---

## Task 7: JSON delta 协议 — applier（校验 + immutable apply + 事件流追加）

**Files:**
- Create: `novel_agent/protocol/applier.py`
- Test: `tests/test_protocol_applier.py`

- [ ] **Step 1: 写失败测试 tests/test_protocol_applier.py**

```python
"""测试 delta applier：校验 → 写库 → 追加事件流。"""
import pytest

from novel_agent.bible.database import SessionLocal, set_config
from novel_agent.bible.models import Base
from novel_agent.config import Config
from novel_agent.protocol.applier import DeltaApplier, ApplyError
from novel_agent.protocol.schemas import Delta, ForeshadowDelta, CharacterDelta


@pytest.fixture
def applier(tmp_config):
    from novel_agent.bible import database as db_mod
    set_config(tmp_config)
    Base.metadata.create_all(bind=db_mod.engine)
    from novel_agent.bible.models import Project
    db = SessionLocal()
    p = Project(title="测试")
    db.add(p); db.commit(); db.refresh(p)
    from novel_agent.bible.repository import BibleRepository
    repo = BibleRepository(db, project_id=p.id)
    yield DeltaApplier(repo)
    db.close()


def test_apply_foreshadow_plant_writes_and_events(applier):
    delta = Delta(
        target="foreshadow", action="plant", chapter=3,
        data=ForeshadowDelta(foreshadow_id="S-001", description="文物箱",
                             plant_chapter=3, planned_resolve_chapter=10),
    )
    result = applier.apply(delta)
    assert result.success
    f = applier.repo.get_foreshadow("S-001")
    assert f is not None
    assert f.status == "planted"
    events = applier.repo.list_events(chapter=3, entity_id="S-001")
    assert len(events) == 1
    assert events[0].type == "foreshadow_planted"


def test_apply_character_state_change(applier):
    # 先建角色
    applier.repo.create_character(name="刘洋")
    delta = Delta(
        target="character", action="state_change", chapter=5,
        data=CharacterDelta(name="刘洋", current_emotion="愤怒", current_location="基地"),
    )
    result = applier.apply(delta)
    assert result.success
    c = applier.repo.get_character("刘洋")
    assert c.current_emotion == "愤怒"
    events = applier.repo.list_events(chapter=5, entity_id="刘洋")
    assert any(e.type == "character_state_change" for e in events)


def test_apply_foreshadow_resolve(applier):
    applier.repo.create_foreshadow(foreshadow_id="S-001", tier="short",
                                   plant_chapter=1, status="planted")
    delta = Delta(
        target="foreshadow", action="resolve", chapter=10,
        data=ForeshadowDelta(foreshadow_id="S-001"),
    )
    result = applier.apply(delta)
    assert result.success
    f = applier.repo.get_foreshadow("S-001")
    assert f.status == "resolved"


def test_apply_unknown_action_raises(applier):
    with pytest.raises(ApplyError):
        applier.apply(Delta(
            target="foreshadow", action="delete", chapter=1,
            data=ForeshadowDelta(foreshadow_id="X"),
        ))
```

- [ ] **Step 2: 运行验证失败**

```bash
set NOVEL_TEST_DB=memory
pytest tests/test_protocol_applier.py -v
```
Expected: FAIL（模块不存在）

- [ ] **Step 3: 创建 novel_agent/protocol/applier.py**

```python
"""Delta applier：校验 → immutable apply → 追加事件流。

spec 2.4 铁律：模型绝不直接写真相源，只产 delta；代码层 apply + 校验。
"""
from __future__ import annotations

from dataclasses import dataclass

from novel_agent.bible.repository import BibleRepository
from novel_agent.protocol.schemas import (
    Delta, ForeshadowDelta, CharacterDelta, SummaryDelta, OutlineDelta,
)


class ApplyError(Exception):
    """delta 校验或 apply 失败。"""


@dataclass
class ApplyResult:
    success: bool
    message: str = ""


class DeltaApplier:
    """把 Delta 应用到圣经。"""

    def __init__(self, repo: BibleRepository):
        self.repo = repo

    def apply(self, delta: Delta) -> ApplyResult:
        handler = {
            ("foreshadow", "plant"): self._plant_foreshadow,
            ("foreshadow", "develop"): self._develop_foreshadow,
            ("foreshadow", "resolve"): self._resolve_foreshadow,
            ("character", "state_change"): self._character_state_change,
            ("character", "create"): self._create_character,
            ("chapter_summary", "create"): self._create_summary,
            ("outline", "create"): self._create_outline,
        }.get((delta.target, delta.action))

        if not handler:
            raise ApplyError(
                f"不支持的 delta: target={delta.target} action={delta.action}"
            )
        return handler(delta)

    def _plant_foreshadow(self, delta: Delta) -> ApplyResult:
        d = ForeshadowDelta(**delta.data) if isinstance(delta.data, dict) else delta.data
        existing = self.repo.get_foreshadow(d.foreshadow_id)
        if existing and existing.status == "planted":
            return ApplyResult(False, f"伏笔 {d.foreshadow_id} 已埋设")
        if existing:
            self.repo.update_foreshadow_status(d.foreshadow_id, "planted")
        else:
            self.repo.create_foreshadow(
                foreshadow_id=d.foreshadow_id, tier=d.tier,
                plant_chapter=d.plant_chapter or delta.chapter,
                description=d.description, depends_on=d.depends_on,
                planned_resolve_chapter=d.planned_resolve_chapter,
                status="planted",
            )
        self.repo.append_event(
            chapter=delta.chapter, type="foreshadow_planted",
            entity_id=d.foreshadow_id,
            payload={"description": d.description, "method": d.implant_method},
        )
        return ApplyResult(True)

    def _develop_foreshadow(self, delta: Delta) -> ApplyResult:
        d = ForeshadowDelta(**delta.data) if isinstance(delta.data, dict) else delta.data
        f = self.repo.get_foreshadow(d.foreshadow_id)
        if not f:
            raise ApplyError(f"伏笔 {d.foreshadow_id} 不存在，无法发展")
        self.repo.update_foreshadow_status(d.foreshadow_id, "developing")
        self.repo.append_event(
            chapter=delta.chapter, type="foreshadow_developed",
            entity_id=d.foreshadow_id, payload={"description": d.description},
        )
        return ApplyResult(True)

    def _resolve_foreshadow(self, delta: Delta) -> ApplyResult:
        d = ForeshadowDelta(**delta.data) if isinstance(delta.data, dict) else delta.data
        f = self.repo.get_foreshadow(d.foreshadow_id)
        if not f:
            raise ApplyError(f"伏笔 {d.foreshadow_id} 不存在，无法回收")
        if f.status == "resolved":
            return ApplyResult(False, f"伏笔 {d.foreshadow_id} 已回收")
        self.repo.update_foreshadow_status(d.foreshadow_id, "resolved")
        self.repo.append_event(
            chapter=delta.chapter, type="foreshadow_resolved",
            entity_id=d.foreshadow_id, payload={"description": d.description},
        )
        return ApplyResult(True)

    def _character_state_change(self, delta: Delta) -> ApplyResult:
        d = CharacterDelta(**delta.data) if isinstance(delta.data, dict) else delta.data
        c = self.repo.get_character(d.name)
        if not c:
            raise ApplyError(f"角色 {d.name} 不存在")
        updates = {}
        if d.current_location:
            updates["current_location"] = d.current_location
        if d.current_emotion:
            updates["current_emotion"] = d.current_emotion
        if d.known_info:
            updates["known_info"] = d.known_info
        if updates:
            self.repo.update_character(d.name, **updates)
        self.repo.append_event(
            chapter=delta.chapter, type="character_state_change",
            entity_id=d.name, payload=updates,
        )
        return ApplyResult(True)

    def _create_character(self, delta: Delta) -> ApplyResult:
        d = CharacterDelta(**delta.data) if isinstance(delta.data, dict) else delta.data
        if self.repo.get_character(d.name):
            return ApplyResult(False, f"角色 {d.name} 已存在")
        self.repo.create_character(
            name=d.name, role=d.role, personality=d.personality,
            motivation=d.motivation, current_location=d.current_location,
            current_emotion=d.current_emotion, known_info=d.known_info,
        )
        self.repo.append_event(
            chapter=delta.chapter, type="character_introduced",
            entity_id=d.name, payload={"role": d.role},
        )
        return ApplyResult(True)

    def _create_summary(self, delta: Delta) -> ApplyResult:
        d = SummaryDelta(**delta.data) if isinstance(delta.data, dict) else delta.data
        if self.repo.get_chapter_summary(delta.chapter):
            return ApplyResult(False, f"第 {delta.chapter} 章摘要已存在")
        self.repo.create_chapter_summary(
            chapter=delta.chapter, title=d.title, word_count=d.word_count,
            time_location=d.time_location, core_events=d.core_events,
            characters_present=d.characters_present, emotion_changes=d.emotion_changes,
            foreshadow_dynamics=d.foreshadow_dynamics,
            subplot_progress=d.subplot_progress, chapter_hook=d.chapter_hook,
        )
        return ApplyResult(True)

    def _create_outline(self, delta: Delta) -> ApplyResult:
        d = OutlineDelta(**delta.data) if isinstance(delta.data, dict) else delta.data
        self.repo.create_outline(
            level=d.level, order=d.order, act=d.act,
            title=d.title, summary=d.summary,
        )
        return ApplyResult(True)
```

- [ ] **Step 4: 运行测试**

```bash
set NOVEL_TEST_DB=memory
pytest tests/test_protocol_applier.py -v
```
Expected: 4 个测试 PASS

- [ ] **Step 5: Commit**

```bash
git add .
git commit -m "feat(protocol): delta applier 校验+apply+事件流"
```

---

## Task 8: 三层记忆 — Core memory 装配

**Files:**
- Create: `novel_agent/memory/__init__.py`, `novel_agent/memory/core.py`
- Test: `tests/test_memory_core.py`

- [ ] **Step 1: 写失败测试 tests/test_memory_core.py**

```python
"""测试 Core memory 装配：每章注入的常驻上下文。"""
import pytest

from novel_agent.bible.database import SessionLocal, set_config
from novel_agent.bible.models import Base, Project
from novel_agent.bible.repository import BibleRepository
from novel_agent.config import Config
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
                        planned_resolve_chapter=3)
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
```

- [ ] **Step 2: 运行验证失败**

```bash
set NOVEL_TEST_DB=memory
pytest tests/test_memory_core.py -v
```
Expected: FAIL（模块不存在）

- [ ] **Step 3: 创建 novel_agent/memory/__init__.py**

```python
"""三层记忆：core / archival / summary / recall。"""
```

- [ ] **Step 4: 创建 novel_agent/memory/core.py**

```python
"""Core memory：每章注入的常驻上下文（~2-4k token）。

包含：项目基础信息 + 当前活跃角色 + 当前卷大纲 + 未回收伏笔子集。
"""
from __future__ import annotations

from novel_agent.bible.repository import BibleRepository


class CoreMemoryAssembler:
    """装配某章生成时的常驻上下文。"""

    def __init__(self, repo: BibleRepository):
        self.repo = repo

    def assemble(self, chapter: int, max_chars: int = 8000) -> str:
        sections: list[str] = []
        project = self.repo.get_project()
        if project:
            sections.append(self._format_project(project))
        # 当前活跃角色（M1 简化：全部角色；M3 优化为按本章出场筛选）
        chars = self.repo.list_characters()
        if chars:
            sections.append(self._format_characters(chars))
        # 本章应埋伏笔
        to_plant = self.repo.get_foreshadows_to_plant(chapter)
        if to_plant:
            sections.append(self._format_to_plant(to_plant))
        # 本章应回收伏笔
        to_resolve = self.repo.get_foreshadows_to_resolve(chapter)
        if to_resolve:
            sections.append(self._format_to_resolve(to_resolve))

        ctx = "\n\n".join(sections)
        if len(ctx) > max_chars:
            ctx = ctx[:max_chars] + "\n[...截断...]"
        return ctx

    def _format_project(self, project) -> str:
        parts = [f"【小说标题】\n{project.title}"]
        if project.genre:
            parts.append(f"【类型】\n{project.genre}")
        if project.summary:
            parts.append(f"【简介】\n{project.summary}")
        if project.style:
            parts.append(f"【风格规范】\n{project.style}")
        return "\n".join(parts)

    def _format_characters(self, chars) -> str:
        lines = ["【当前角色状态】"]
        for c in chars:
            info = f"- {c.name}（{c.role or '角色'}）"
            if c.current_location:
                info += f" | 位置：{c.current_location}"
            if c.current_emotion:
                info += f" | 情绪：{c.current_emotion}"
            if c.personality:
                info += f" | 性格：{c.personality}"
            lines.append(info)
        return "\n".join(lines)

    def _format_to_plant(self, foreshadows) -> str:
        lines = ["【本章应埋伏笔】"]
        for f in foreshadows:
            lines.append(f"- {f.foreshadow_id}：{f.description}（计划第 {f.planned_resolve_chapter} 章回收）")
        return "\n".join(lines)

    def _format_to_resolve(self, foreshadows) -> str:
        lines = ["【本章应回收伏笔】"]
        for f in foreshadows:
            lines.append(f"- {f.foreshadow_id}：{f.description}")
        return "\n".join(lines)
```

- [ ] **Step 5: 运行测试**

```bash
set NOVEL_TEST_DB=memory
pytest tests/test_memory_core.py -v
```
Expected: 3 个测试 PASS

- [ ] **Step 6: Commit**

```bash
git add .
git commit -m "feat(memory): core memory 装配"
```

---

## Task 9: 三层记忆 — Archival（向量检索）

**Files:**
- Create: `novel_agent/memory/archival.py`
- Test: `tests/test_memory_archival.py`

- [ ] **Step 1: 写失败测试 tests/test_memory_archival.py**

```python
"""测试 Archival 向量检索。"""
import pytest

from novel_agent.config import Config
from novel_agent.memory.archival import ArchivalMemory


@pytest.fixture
def archival(tmp_config):
    am = ArchivalMemory(tmp_config)
    yield am
    am.reset()  # 清理临时 chroma


def test_index_and_retrieve(archival):
    archival.index_chapter(chapter=1, title="无声征召",
                           content="刘洋在修理厂修车，贺鸣率灰烬小队突袭征召。")
    archival.index_chapter(chapter=2, title="火种基地",
                           content="刘洋被带到火种基地，见到神秘黑色晶体。")
    archival.index_setting(category="力量体系", title="奇点",
                           content="奇点是异能核心，分 F 到 S 级。")
    results = archival.retrieve(query="黑色晶体是什么", top_k=2)
    assert len(results) >= 1
    # 应该召回含"黑色晶体"的第2章
    found = any("晶体" in r["content"] for r in results)
    assert found


def test_retrieve_with_chapter_filter(archival):
    archival.index_chapter(chapter=1, title="ch1", content="征召事件")
    archival.index_chapter(chapter=2, title="ch2", content="基地见闻")
    results = archival.retrieve(query="征召", top_k=5, chapter_filter=1)
    assert all(r["chapter"] == 1 for r in results)


def test_retrieve_empty(archival):
    results = archival.retrieve(query="不存在的内容", top_k=3)
    assert results == []
```

- [ ] **Step 2: 运行验证失败**

```bash
pytest tests/test_memory_archival.py -v
```
Expected: FAIL（模块不存在）

- [ ] **Step 3: 创建 novel_agent/memory/archival.py**

```python
"""Archival memory：向量库，按需检索章节/设定切片。

spec 2.1：Chroma 存全章节切块 + 设定条目；
检索用 recency × importance × relevance 三因子（M1 简化为 relevance）。
"""
from __future__ import annotations

import uuid
from typing import Any

import chromadb
from chromadb.config import Settings

from novel_agent.config import Config


class ArchivalMemory:
    """Chroma 向量检索。"""

    def __init__(self, config: Config):
        self.config = config
        config.chroma_dir.mkdir(parents=True, exist_ok=True)
        self._client = chromadb.PersistentClient(path=str(config.chroma_dir))
        self._collection = self._client.get_or_create_collection(
            name="novel_archive",
            metadata={"hnsw:space": "cosine"},
        )

    def index_chapter(self, chapter: int, title: str, content: str) -> None:
        doc_id = f"ch{chapter}_{uuid.uuid4().hex[:8]}"
        self._collection.add(
            ids=[doc_id],
            documents=[f"第{chapter}章《{title}》\n{content}"],
            metadatas=[{"type": "chapter", "chapter": chapter, "title": title}],
        )

    def index_setting(self, category: str, title: str, content: str) -> None:
        doc_id = f"set_{uuid.uuid4().hex[:8]}"
        self._collection.add(
            ids=[doc_id],
            documents=[f"【{category}：{title}】\n{content}"],
            metadatas=[{"type": "setting", "category": category, "title": title}],
        )

    def retrieve(self, query: str, top_k: int = 4,
                 chapter_filter: int | None = None) -> list[dict[str, Any]]:
        if self._collection.count() == 0:
            return []
        where = None
        if chapter_filter is not None:
            where = {"chapter": chapter_filter}
        res = self._collection.query(
            query_texts=[query], n_results=top_k, where=where,
        )
        results = []
        ids = res.get("ids", [[]])[0]
        docs = res.get("documents", [[]])[0]
        metas = res.get("metadatas", [[]])[0]
        dists = res.get("distances", [[]])[0]
        for i, doc in enumerate(docs):
            results.append({
                "id": ids[i],
                "content": doc,
                "metadata": metas[i],
                "distance": dists[i],
                "chapter": metas[i].get("chapter"),
            })
        return results

    def reset(self) -> None:
        self._client.delete_collection("novel_archive")
        self._collection = self._client.get_or_create_collection(
            name="novel_archive", metadata={"hnsw:space": "cosine"},
        )
```

- [ ] **Step 4: 运行测试**

```bash
pytest tests/test_memory_archival.py -v
```
Expected: 3 个测试 PASS（首次会下载 chromadb 模型，较慢）

- [ ] **Step 5: Commit**

```bash
git add .
git commit -m "feat(memory): archival 向量检索（Chroma）"
```

---

## Task 10: 三层记忆 — Summary Tree（分层摘要）

**Files:**
- Create: `novel_agent/memory/summary_tree.py`
- Test: `tests/test_memory_summary_tree.py`

- [ ] **Step 1: 写失败测试 tests/test_memory_summary_tree.py**

```python
"""测试摘要树：章→弧→卷→全书。"""
import pytest

from novel_agent.bible.database import SessionLocal, set_config
from novel_agent.bible.models import Base, Project
from novel_agent.bible.repository import BibleRepository
from novel_agent.memory.summary_tree import SummaryTree


@pytest.fixture
def repo(tmp_config):
    from novel_agent.bible import database as db_mod
    set_config(tmp_config)
    Base.metadata.create_all(bind=db_mod.engine)
    db = SessionLocal()
    p = Project(title="测试")
    db.add(p); db.commit(); db.refresh(p)
    r = BibleRepository(db, project_id=p.id)
    # 建几章摘要
    for ch in range(1, 6):
        r.create_chapter_summary(
            chapter=ch, title=f"第{ch}章", core_events=f"第{ch}章事件",
            word_count=2000,
        )
    yield r
    db.close()


def test_get_chapter_summaries(repo):
    tree = SummaryTree(repo)
    summaries = tree.get_recent_chapter_summaries(count=3)
    assert len(summaries) == 3
    # 最近 3 章按章节升序
    assert [s.chapter for s in summaries] == [3, 4, 5]


def test_get_arc_summary_not_implemented_gracefully(repo):
    tree = SummaryTree(repo)
    # M1：弧/卷摘要暂不支持自动生成，返回空
    arc_summary = tree.get_arc_summary(arc_chapters=[1, 2, 3])
    # M1 至少返回章节摘要的拼接
    assert "第1章" in arc_summary


def test_get_full_summary(repo):
    tree = SummaryTree(repo)
    full = tree.get_full_summary()
    assert "测试" in full  # 项目标题
    assert "第5章" in full
```

- [ ] **Step 2: 运行验证失败**

```bash
set NOVEL_TEST_DB=memory
pytest tests/test_memory_summary_tree.py -v
```
Expected: FAIL

- [ ] **Step 3: 创建 novel_agent/memory/summary_tree.py**

```python
"""Summary tree：章→弧→卷→全书分层摘要。

M1：只实现章摘要查询与拼接；弧/卷摘要由 M3 的 Summarizer agent 生成后存库。
"""
from __future__ import annotations

from novel_agent.bible.repository import BibleRepository


class SummaryTree:
    """分层摘要树读取。"""

    def __init__(self, repo: BibleRepository):
        self.repo = repo

    def get_recent_chapter_summaries(self, count: int = 5):
        """最近 N 章摘要，按章节升序。"""
        recent = self.repo.list_chapter_summaries(limit=count)
        return sorted(recent, key=lambda s: s.chapter)

    def get_arc_summary(self, arc_chapters: list[int]) -> str:
        """某弧的摘要。M1：拼接该弧内各章摘要。"""
        parts = []
        for ch in arc_chapters:
            s = self.repo.get_chapter_summary(ch)
            if s:
                parts.append(f"第{ch}章《{s.title}》：{s.core_events}")
        return "\n".join(parts)

    def get_volume_summary(self, volume: int) -> str:
        """某卷摘要。M3 由 Summarizer 生成。M1 返回空串。"""
        return ""

    def get_full_summary(self) -> str:
        """全书摘要：项目标题 + 所有章摘要拼接（M1 简化）。"""
        project = self.repo.get_project()
        parts = [f"《{project.title}》"] if project else []
        summaries = self.repo.list_chapter_summaries(limit=1000)
        for s in sorted(summaries, key=lambda x: x.chapter):
            parts.append(f"第{s.chapter}章《{s.title}》：{s.core_events}")
        return "\n".join(parts)
```

- [ ] **Step 4: 运行测试**

```bash
set NOVEL_TEST_DB=memory
pytest tests/test_memory_summary_tree.py -v
```
Expected: 3 个测试 PASS

- [ ] **Step 5: Commit**

```bash
git add .
git commit -m "feat(memory): summary tree 分层摘要"
```

---

## Task 11: 三层记忆 — Recall（全量原文 + 事件时间线）

**Files:**
- Create: `novel_agent/memory/recall.py`
- Test: `tests/test_memory_recall.py`

- [ ] **Step 1: 写失败测试 tests/test_memory_recall.py**

```python
"""测试 Recall：全量原文 + 事件时间线查询。"""
import pytest
from pathlib import Path

from novel_agent.config import Config
from novel_agent.memory.recall import RecallMemory


@pytest.fixture
def recall(tmp_config):
    recall = RecallMemory(tmp_config)
    # 写一章正文
    recall.save_chapter_text(chapter=1, title="无声征召",
                             content="刘洋在修理厂修车……（正文）")
    yield recall


def test_save_and_read_chapter_text(recall):
    text = recall.read_chapter_text(chapter=1)
    assert "刘洋" in text
    assert "无声征召" in text


def test_read_nonexistent_chapter(recall):
    text = recall.read_chapter_text(chapter=999)
    assert text == ""


def test_list_chapters(recall):
    recall.save_chapter_text(chapter=2, title="火种", content="第二章正文")
    chapters = recall.list_chapters()
    assert 1 in chapters
    assert 2 in chapters
```

- [ ] **Step 2: 运行验证失败**

```bash
pytest tests/test_memory_recall.py -v
```
Expected: FAIL

- [ ] **Step 3: 创建 novel_agent/memory/recall.py**

```python
"""Recall memory：全量原文 + 事件时间线查询（不进上下文，供精确回溯）。"""
from __future__ import annotations

import re
from pathlib import Path

from novel_agent.config import Config


class RecallMemory:
    """章节正文文件读写 + 事件流查询入口。"""

    def __init__(self, config: Config):
        self.config = config
        self.chapters_dir = config.chapters_dir
        self.chapters_dir.mkdir(parents=True, exist_ok=True)

    def save_chapter_text(self, chapter: int, title: str, content: str) -> Path:
        """保存章节正文到 markdown 文件。"""
        safe_title = re.sub(r'[\\/:*?"<>|]', "_", title)
        filename = f"第{chapter:03d}章_{safe_title}.md"
        path = self.chapters_dir / filename
        path.write_text(f"# 第{chapter}章 {title}\n\n{content}", encoding="utf-8")
        return path

    def read_chapter_text(self, chapter: int) -> str:
        """读取章节正文，找不到返回空串。"""
        pattern = f"第{chapter:03d}章_*.md"
        matches = list(self.chapters_dir.glob(pattern))
        if not matches:
            return ""
        return matches[0].read_text(encoding="utf-8")

    def list_chapters(self) -> list[int]:
        """列出所有已写章节号。"""
        chapters = []
        for p in self.chapters_dir.glob("第*章_*.md"):
            m = re.match(r"第(\d+)章_", p.name)
            if m:
                chapters.append(int(m.group(1)))
        return sorted(chapters)
```

- [ ] **Step 4: 运行测试**

```bash
pytest tests/test_memory_recall.py -v
```
Expected: 3 个测试 PASS

- [ ] **Step 5: Commit**

```bash
git add .
git commit -m "feat(memory): recall 全量原文读写"
```

---

## Task 12: LLM 客户端（OpenAI 兼容 + 重试/降级/超时）

**Files:**
- Create: `novel_agent/llm/__init__.py`, `novel_agent/llm/client.py`
- Test: `tests/test_llm_client.py`

- [ ] **Step 1: 写失败测试 tests/test_llm_client.py**

```python
"""测试 LLM 客户端：用 mock httpx 验证调用逻辑。"""
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from novel_agent.config import LLMConfig
from novel_agent.llm.client import LLMClient, LLMError


@pytest.fixture
def client():
    return LLMClient(LLMConfig(
        base_url="https://api.test.com/v1", api_key="sk-test",
        model="test-model", temperature=0.7, max_tokens=1000,
    ))


def test_build_request_payload(client):
    payload = client._build_payload("你好", system="你是助手")
    assert payload["model"] == "test-model"
    assert payload["messages"][0]["role"] == "system"
    assert payload["messages"][0]["content"] == "你是助手"
    assert payload["messages"][1]["content"] == "你好"
    assert payload["temperature"] == 0.7


@pytest.mark.asyncio
async def test_generate_success(client):
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.raise_for_status = MagicMock()
    mock_resp.json.return_value = {
        "choices": [{"message": {"content": "生成结果"}}]
    }
    with patch("novel_agent.llm.client.httpx.AsyncClient") as MockClient:
        instance = MockClient.return_value
        instance.post = AsyncMock(return_value=mock_resp)
        instance.__aenter__ = AsyncMock(return_value=instance)
        instance.__aexit__ = AsyncMock(return_value=None)
        result = await client.generate("你好")
    assert result == "生成结果"


@pytest.mark.asyncio
async def test_generate_retries_on_timeout(client):
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.raise_for_status = MagicMock()
    mock_resp.json.return_value = {
        "choices": [{"message": {"content": "成功"}}]
    }
    call_count = 0

    async def side_effect(*args, **kwargs):
        nonlocal call_count
        call_count += 1
        if call_count < 2:
            raise httpx.TimeoutException("timeout")
        return mock_resp

    with patch("novel_agent.llm.client.httpx.AsyncClient") as MockClient:
        instance = MockClient.return_value
        instance.post = AsyncMock(side_effect=side_effect)
        instance.__aenter__ = AsyncMock(return_value=instance)
        instance.__aexit__ = AsyncMock(return_value=None)
        result = await client.generate("你好", max_retries=3)
    assert result == "成功"
    assert call_count == 2


@pytest.mark.asyncio
async def test_generate_raises_after_max_retries(client):
    import httpx
    with patch("novel_agent.llm.client.httpx.AsyncClient") as MockClient:
        instance = MockClient.return_value
        instance.post = AsyncMock(side_effect=httpx.TimeoutException("timeout"))
        instance.__aenter__ = AsyncMock(return_value=instance)
        instance.__aexit__ = AsyncMock(return_value=None)
        with pytest.raises(LLMError):
            await client.generate("你好", max_retries=2)
```

- [ ] **Step 2: 运行验证失败**

```bash
pytest tests/test_llm_client.py -v
```
Expected: FAIL（模块不存在）

- [ ] **Step 3: 创建 novel_agent/llm/__init__.py**

```python
"""LLM 客户端。"""
```

- [ ] **Step 4: 创建 novel_agent/llm/client.py**

```python
"""OpenAI 兼容客户端：重试/降级/超时。

spec 1.1：不绑死厂商；多模型分层降成本。
"""
from __future__ import annotations

import asyncio
from typing import Any

import httpx

from novel_agent.config import LLMConfig


class LLMError(Exception):
    """LLM 调用失败。"""


class LLMClient:
    """OpenAI 兼容 chat/completions 客户端。"""

    def __init__(self, config: LLMConfig):
        self.config = config

    def _build_payload(self, user_content: str, system: str | None = None) -> dict[str, Any]:
        messages = []
        if system:
            messages.append({"role": "system", "content": system})
        messages.append({"role": "user", "content": user_content})
        return {
            "model": self.config.model,
            "messages": messages,
            "temperature": self.config.temperature,
            "max_tokens": self.config.max_tokens,
        }

    async def generate(self, user_content: str, system: str | None = None,
                       max_retries: int = 3) -> str:
        """生成文本，超时/网络错误指数退避重试。"""
        url = f"{self.config.base_url.rstrip('/')}/chat/completions"
        headers = {
            "Authorization": f"Bearer {self.config.api_key}",
            "Content-Type": "application/json",
        }
        payload = self._build_payload(user_content, system)

        last_err: Exception | None = None
        for attempt in range(max_retries):
            try:
                async with httpx.AsyncClient(timeout=self.config.timeout) as client:
                    resp = await client.post(url, headers=headers, json=payload)
                    resp.raise_for_status()
                    data = resp.json()
                    return data["choices"][0]["message"]["content"]
            except (httpx.TimeoutException, httpx.NetworkError) as e:
                last_err = e
                if attempt < max_retries - 1:
                    await asyncio.sleep(2 ** attempt)  # 指数退避
            except httpx.HTTPStatusError as e:
                raise LLMError(f"AI 接口 HTTP 错误: {e.response.text}") from e
            except Exception as e:
                raise LLMError(f"AI 生成出错: {e}") from e

        raise LLMError(f"重试 {max_retries} 次后仍失败: {last_err}")
```

- [ ] **Step 5: 运行测试**

```bash
pytest tests/test_llm_client.py -v
```
Expected: 4 个测试 PASS（注意 test_llm_client.py 顶部需 import httpx，见 Step 6）

- [ ] **Step 6: 修正测试顶部 import**

在 `tests/test_llm_client.py` 顶部加：
```python
import httpx
```

- [ ] **Step 7: 再次运行测试**

```bash
pytest tests/test_llm_client.py -v
```
Expected: 4 个测试 PASS

- [ ] **Step 8: Commit**

```bash
git add .
git commit -m "feat(llm): OpenAI 兼容客户端 + 重试/超时"
```

---

## Task 13: CLI 入口 + 端到端验证

**Files:**
- Create: `novel_agent/cli.py`
- Test: `tests/test_cli_e2e.py`

- [ ] **Step 1: 写端到端测试 tests/test_cli_e2e.py**

```python
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
```

- [ ] **Step 2: 运行验证失败**

```bash
set NOVEL_TEST_DB=memory
pytest tests/test_cli_e2e.py -v
```
Expected: PASS（该测试依赖前序 Task 3-12 的所有模块，全部就位后应通过；若 FAIL，先单独跑 `pytest tests/test_protocol_applier.py tests/test_memory_core.py tests/test_llm_client.py -v` 确认依赖模块无问题）

- [ ] **Step 3: 创建 novel_agent/cli.py**

```python
"""命令行入口。M1 仅提供 init 命令；生成命令 M2 实现。"""
from __future__ import annotations

import argparse
import sys

from novel_agent.bible.database import SessionLocal, set_config
from novel_agent.bible.models import Base, Project
from novel_agent.bible.repository import BibleRepository
from novel_agent.config import load_config


def cmd_init(args):
    """初始化新小说项目。"""
    from novel_agent.bible import database as db_mod
    cfg = load_config(args.config)
    set_config(cfg)
    Base.metadata.create_all(bind=db_mod.engine)
    db = SessionLocal()
    p = Project(title=args.title, genre=args.genre or "",
                summary=args.summary or "", style=args.style or "")
    db.add(p); db.commit(); db.refresh(p)
    print(f"已创建项目：{p.title} (id={p.id})")
    print(f"数据目录：{cfg.project_data_dir}")
    db.close()


def main():
    parser = argparse.ArgumentParser(prog="novel-agent", description="多 Agent 小说生成")
    sub = parser.add_subparsers(dest="cmd", required=True)

    p_init = sub.add_parser("init", help="初始化新小说项目")
    p_init.add_argument("--title", required=True)
    p_init.add_argument("--genre", default="")
    p_init.add_argument("--summary", default="")
    p_init.add_argument("--style", default="")
    p_init.add_argument("--config", default=None)
    p_init.set_defaults(func=cmd_init)

    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
```

- [ ] **Step 4: 端到端跑通 init 命令**

```bash
.venv\Scripts\activate
novel-agent init --title "测试小说" --genre "科幻" --summary "测试"
```
Expected: 打印"已创建项目"，project_data/bible.db 生成

- [ ] **Step 5: 运行全部测试**

```bash
set NOVEL_TEST_DB=memory
pytest -v
```
Expected: 全部 PASS

- [ ] **Step 6: Commit**

```bash
git add .
git commit -m "feat: CLI init 命令 + M1 端到端验证通过"
```

---

## M1 验收清单

完成 Task 1-13 后，逐项确认：

- [ ] 旧 Electron 代码已删除，git 仓库已初始化
- [ ] `pip install -e ".[dev]"` 成功
- [ ] `pytest` 全部 PASS（约 30+ 测试）
- [ ] `novel-agent init --title X` 能创建项目并生成 bible.db
- [ ] 圣经 9 库 + 事件流表可建表
- [ ] 仓储 CRUD 可读写角色/伏笔/摘要/事件
- [ ] JSON delta 协议能校验 + apply + 追加事件流
- [ ] Core memory 能装配章节上下文
- [ ] Archival 向量库能 index + retrieve
- [ ] Summary tree 能查章摘要
- [ ] Recall 能存/读章节正文
- [ ] LLM 客户端能 mock 调用 + 重试
- [ ] 端到端：设定→core memory→LLM(mock)→存正文→存摘要 跑通

---

## 后续里程碑（M1 跑通后另写计划）

- **M2**：LangGraph 最小编排（1 Writer 节点）+ checkpoint + 真实 LLM 端到端生成单章
- **M3**：7 agent 全实现 + 写审循环 + 审计维度 + Summarizer 回写
- **M4**：interrupt 人审三节点 + FastAPI + SSE + 前端四界面
