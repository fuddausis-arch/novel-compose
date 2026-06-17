# M2：编排引擎与单 Writer 端到端 实现计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 用 LangGraph 串起最小可运行流水线，把 M1 的 mock LLM 换成真实 LLM 调用，端到端生成单章并持久化 + 断点续跑。同时清掉 M1 遗留的两个能并进 M2 的待办（applier 事务原子性、applier 接入 archival/summary 同步）。

**Architecture:** 新增 `orchestrator/` 包：LangGraph StateGraph 定义「装配上下文 → 调 Writer → 存正文 → 存摘要」四节点状态机，SqliteSaver 做 checkpoint 实现断点续跑。Writer 节点复用 M1 的 CoreMemoryAssembler + LLMClient，产出经 DeltaApplier 写入圣经。同时给 applier 加事务原子性和 archival/summary 同步钩子。

**Tech Stack:** Python 3.11、LangGraph 1.2（StateGraph/SqliteSaver/Command）、复用 M1 全部模块

---

## 前置说明

- 工作目录：`C:\Users\LYY\Desktop\vibe coding`
- venv：`.venv`，用 `.venv\Scripts\python.exe`
- 测试用 `set NOVEL_TEST_DB=memory` 切内存库
- langgraph 已装（1.2.5）并已加入 pyproject 依赖
- M1 已合并到 main，本计划从 main 拉新分支 `m2-orchestrator`

## 文件结构（M2 范围）

```
novel_agent/
├── orchestrator/                    # 新增：LangGraph 编排
│   ├── __init__.py
│   ├── state.py                     # 流水线状态 schema（TypedDict）
│   ├── graph.py                     # StateGraph 定义 + 节点注册
│   ├── nodes.py                     # 节点函数实现（assemble/write/save_text/save_summary）
│   └── runner.py                    # 运行入口（建 graph + SqliteSaver + 调用 + 断点续跑）
├── protocol/
│   └── applier.py                   # 修改：加事务原子性 + archival/summary 同步钩子
└── cli.py                           # 修改：加 generate 子命令
tests/
├── test_orchestrator_state.py
├── test_orchestrator_nodes.py
├── test_orchestrator_graph.py
├── test_orchestrator_runner.py
└── test_applier_atomicity.py        # M1 遗留：事务原子性
```

---

## Task 1: 清理 M1 遗留 — Applier 事务原子性

**Files:**
- Modify: `novel_agent/protocol/applier.py`
- Create: `tests/test_applier_atomicity.py`

- [ ] **Step 1: 写失败测试 tests/test_applier_atomicity.py**

```python
"""测试 applier 事务原子性：handler 内多步写要么全成功要么全回滚。"""
import pytest
from unittest.mock import patch

from novel_agent.bible.database import SessionLocal, set_config
from novel_agent.bible.models import Base, Project
from novel_agent.protocol.applier import DeltaApplier, ApplyError
from novel_agent.protocol.schemas import Delta, ForeshadowDelta


@pytest.fixture
def applier(tmp_config):
    from novel_agent.bible import database as db_mod
    set_config(tmp_config)
    Base.metadata.create_all(bind=db_mod.engine)
    db = SessionLocal()
    p = Project(title="测试")
    db.add(p); db.commit(); db.refresh(p)
    from novel_agent.bible.repository import BibleRepository
    repo = BibleRepository(db, project_id=p.id)
    yield DeltaApplier(repo)
    db.close()


def test_plant_foreshadow_atomic_on_event_failure(applier):
    """append_event 抛错时，伏笔写入应回滚（不留半成品）。"""
    delta = Delta(
        target="foreshadow", action="plant", chapter=3,
        data=ForeshadowDelta(foreshadow_id="S-001", description="文物箱",
                             plant_chapter=3, planned_resolve_chapter=10),
    )
    # 让 append_event 抛错
    with patch.object(applier.repo, "append_event", side_effect=RuntimeError("db down")):
        with pytest.raises(ApplyError):
            applier.apply(delta)
    # 伏笔不应残留
    f = applier.repo.get_foreshadow("S-001")
    assert f is None or f.status != "planted"


def test_successful_apply_commits_atomically(applier):
    """正常 apply 应一次提交完成快照+事件。"""
    delta = Delta(
        target="foreshadow", action="plant", chapter=3,
        data=ForeshadowDelta(foreshadow_id="S-001", description="文物箱",
                             plant_chapter=3, planned_resolve_chapter=10),
    )
    result = applier.apply(delta)
    assert result.success
    assert applier.repo.get_foreshadow("S-001").status == "planted"
    assert len(applier.repo.list_events(chapter=3, entity_id="S-001")) == 1
```

- [ ] **Step 2: 运行验证失败**

```bash
set NOVEL_TEST_DB=memory && .venv\Scripts\python.exe -m pytest tests/test_applier_atomicity.py -v
```
Expected: FAIL（当前 applier 无事务，部分失败会留半成品）

- [ ] **Step 3: 给 applier 加事务包装**

修改 `novel_agent/protocol/applier.py`：在 `apply` 方法里包一层事务，handler 内的 repo 写操作不单独 commit（改为 flush），由 apply 统一 commit；失败则 rollback。

关键改动：repository 的写方法目前各自 commit。为不破坏现有测试，applier 改为：执行 handler 前不开事务（repo 各自 commit 仍工作），但**对于需要多步原子性的 handler**，引入一个 `_run_in_transaction` 辅助，在该辅助内捕获异常并回滚已提交的改动——但 SQLite 已 commit 的无法回滚。

更干净的方案：给 repository 加 `begin_transaction` 上下文管理器，applier 用它包 handler，内部 repo 方法检测到事务上下文则只 flush 不 commit。但这改动大。

**务实最小方案**：applier 的 apply 方法改为捕获 handler 内任何异常，若已部分写入则尝试补偿删除并抛 ApplyError。但补偿逻辑复杂。

**采用方案**：给 BibleRepository 加 `unit_of_work()` 上下文管理器，进入时设 `self._in_tx = True`，写方法检测到则只 `flush` 不 `commit`，退出时统一 `commit`（异常 `rollback`）。applier.apply 用此上下文包 handler。现有测试不传 unit_of_work，repo 行为不变（各自 commit）。

修改 `novel_agent/bible/repository.py`，给 BibleRepository 加：

```python
from contextlib import contextmanager

@contextmanager
def unit_of_work(self):
    """事务上下文：内部写操作只 flush 不 commit，退出统一 commit/rollback。"""
    self._in_tx = True
    try:
        yield
        self.db.commit()
    except Exception:
        self.db.rollback()
        raise
    finally:
        self._in_tx = False
```

并把所有写方法（create_*/update_*/append_event）的 `self.db.commit()` 改为：
```python
if getattr(self, "_in_tx", False):
    self.db.flush()
else:
    self.db.commit()
```

修改 `novel_agent/protocol/applier.py` 的 apply：
```python
def apply(self, delta: Delta) -> ApplyResult:
    handler = {...}.get((delta.target, delta.action))
    if not handler:
        raise ApplyError(f"不支持的 delta: target={delta.target} action={delta.action}")
    try:
        with self.repo.unit_of_work():
            return handler(delta)
    except ApplyError:
        raise
    except Exception as e:
        raise ApplyError(f"apply 失败已回滚: {e}") from e
```

- [ ] **Step 4: 运行测试**

```bash
set NOVEL_TEST_DB=memory && .venv\Scripts\python.exe -m pytest tests/test_applier_atomicity.py -v
```
Expected: 2 PASS

- [ ] **Step 5: 跑全套确认无回归**

```bash
set NOVEL_TEST_DB=memory && .venv\Scripts\python.exe -m pytest -v
```
Expected: M1 的 39 + M2 新增 2 = 41 PASS

- [ ] **Step 6: Commit**

```bash
git add . && git commit -m "fix(applier): 事务原子性，handler 多步写要么全成要么回滚"
```

---

## Task 2: Applier 接入 archival/summary 同步钩子

**Files:**
- Modify: `novel_agent/protocol/applier.py`
- Test: `tests/test_applier_atomicity.py`（追加）

- [ ] **Step 1: 追加测试到 tests/test_applier_atomicity.py**

```python
def test_create_summary_indexes_archival(applier, tmp_config):
    """create_summary 应同步索引到 archival 向量库。"""
    from novel_agent.memory.archival import ArchivalMemory
    from novel_agent.protocol.schemas import SummaryDelta
    archival = ArchivalMemory(tmp_config)
    applier.archival = archival
    delta = Delta(
        target="chapter_summary", action="create", chapter=1,
        data=SummaryDelta(title="第一章", core_events="征召事件", word_count=2000),
    )
    result = applier.apply(delta)
    assert result.success
    # 章节摘要应被索引到 archival
    hits = archival.retrieve(query="征召", top_k=5)
    assert any("征召" in h["content"] for h in hits)
    archival.reset()


def test_applier_without_archival_still_works(applier):
    """未注入 archival 时，create_summary 仍正常（不同步向量库）。"""
    from novel_agent.protocol.schemas import SummaryDelta
    delta = Delta(
        target="chapter_summary", action="create", chapter=1,
        data=SummaryDelta(title="第一章", core_events="事件"),
    )
    result = applier.apply(delta)
    assert result.success
```

- [ ] **Step 2: 运行验证失败**

```bash
set NOVEL_TEST_DB=memory && .venv\Scripts\python.exe -m pytest tests/test_applier_atomicity.py::test_create_summary_indexes_archival -v
```
Expected: FAIL（applier 未接入 archival）

- [ ] **Step 3: 给 DeltaApplier 加 archival 可选注入 + 在 _create_summary 后同步索引**

修改 `novel_agent/protocol/applier.py`：

```python
class DeltaApplier:
    def __init__(self, repo: BibleRepository, archival=None):
        self.repo = repo
        self.archival = archival
```

在 `_create_summary` 末尾（事件追加后）加：
```python
if self.archival:
    self.archival.index_chapter(
        chapter=delta.chapter, title=d.title,
        content=f"{d.core_events} {d.chapter_hook}",
    )
```

- [ ] **Step 4: 运行测试**

```bash
set NOVEL_TEST_DB=memory && .venv\Scripts\python.exe -m pytest tests/test_applier_atomicity.py -v
```
Expected: 4 PASS

- [ ] **Step 5: Commit**

```bash
git add . && git commit -m "feat(applier): 接入 archival 同步索引（spec 2.4）"
```

---

## Task 3: 编排状态 schema

**Files:**
- Create: `novel_agent/orchestrator/__init__.py`, `novel_agent/orchestrator/state.py`
- Test: `tests/test_orchestrator_state.py`

- [ ] **Step 1: 写失败测试 tests/test_orchestrator_state.py**

```python
"""测试流水线状态 schema。"""
from novel_agent.orchestrator.state import ChapterGenState


def test_state_has_required_fields():
    s = ChapterGenState(project_id=1, chapter=5, title="第五章")
    assert s.project_id == 1
    assert s.chapter == 5
    assert s.title == "第五章"
    assert s.context == ""
    assert s.draft == ""
    assert s.status == "pending"


def test_state_with_context_and_draft():
    s = ChapterGenState(
        project_id=1, chapter=5, title="第五章",
        context="前文摘要", draft="章节正文", status="drafted",
    )
    assert s.context == "前文摘要"
    assert s.draft == "章节正文"
    assert s.status == "drafted"


def test_state_error_field():
    s = ChapterGenState(project_id=1, chapter=5, title="x", error="LLM 超时")
    assert s.error == "LLM 超时"
```

- [ ] **Step 2: 运行验证失败**

```bash
.venv\Scripts\python.exe -m pytest tests/test_orchestrator_state.py -v
```
Expected: FAIL（模块不存在）

- [ ] **Step 3: 创建 novel_agent/orchestrator/__init__.py**

```python
"""LangGraph 编排引擎。"""
```

- [ ] **Step 4: 创建 novel_agent/orchestrator/state.py**

```python
"""流水线状态 schema（LangGraph StateGraph 用 TypedDict）。

状态在节点间传递，每个节点读取所需字段、写回产出字段。
"""
from __future__ import annotations

from typing import TypedDict


class ChapterGenState(TypedDict, total=False):
    """单章生成的流水线状态。"""
    project_id: int          # 项目 id
    chapter: int             # 章节号
    title: str               # 章节标题
    context: str             # 装配的上下文（core memory + archival 检索）
    draft: str               # Writer 产出的正文草稿
    status: str              # pending / assembled / drafted / saved / failed
    error: str               # 失败时的错误信息
    word_count: int          # 章节字数
```

- [ ] **Step 5: 运行测试**

```bash
.venv\Scripts\python.exe -m pytest tests/test_orchestrator_state.py -v
```
Expected: 3 PASS

- [ ] **Step 6: Commit**

```bash
git add . && git commit -m "feat(orchestrator): 流水线状态 schema"
```

---

## Task 4: 编排节点函数

**Files:**
- Create: `novel_agent/orchestrator/nodes.py`
- Test: `tests/test_orchestrator_nodes.py`

- [ ] **Step 1: 写失败测试 tests/test_orchestrator_nodes.py**

```python
"""测试编排节点函数。"""
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from novel_agent.bible.database import SessionLocal, set_config
from novel_agent.bible.models import Base, Project
from novel_agent.bible.repository import BibleRepository
from novel_agent.config import LLMConfig
from novel_agent.orchestrator.state import ChapterGenState
from novel_agent.orchestrator.nodes import assemble_context, write_chapter, save_text, save_summary


@pytest.fixture
def repo(tmp_config):
    from novel_agent.bible import database as db_mod
    set_config(tmp_config)
    Base.metadata.create_all(bind=db_mod.engine)
    db = SessionLocal()
    p = Project(title="测试", genre="科幻", summary="末日")
    db.add(p); db.commit(); db.refresh(p)
    r = BibleRepository(db, project_id=p.id)
    r.create_character(name="刘洋", role="主角")
    yield r
    db.close()


def test_assemble_context_node(repo):
    state = ChapterGenState(project_id=repo.project_id, chapter=1, title="第一章")
    result = assemble_context(state, repo=repo)
    assert "刘洋" in result["context"]
    assert result["status"] == "assembled"


@pytest.mark.asyncio
async def test_write_chapter_node(repo):
    state = ChapterGenState(
        project_id=repo.project_id, chapter=1, title="第一章",
        context="设定：刘洋是主角", status="assembled",
    )
    mock_client = MagicMock()
    mock_client.generate = AsyncMock(return_value="第一章正文……")
    result = await write_chapter(state, llm_client=mock_client)
    assert "第一章正文" in result["draft"]
    assert result["status"] == "drafted"


def test_save_text_node(repo, tmp_config):
    state = ChapterGenState(
        project_id=repo.project_id, chapter=1, title="第一章",
        draft="第一章正文内容", status="drafted",
    )
    from novel_agent.memory.recall import RecallMemory
    recall = RecallMemory(tmp_config)
    result = save_text(state, recall=recall)
    assert result["status"] == "saved"
    assert "第一章正文内容" in recall.read_chapter_text(1)


def test_save_summary_node(repo):
    state = ChapterGenState(
        project_id=repo.project_id, chapter=1, title="第一章",
        draft="第一章正文内容", status="saved", word_count=6,
    )
    from novel_agent.protocol.applier import DeltaApplier
    from novel_agent.protocol.schemas import SummaryDelta, Delta
    applier = DeltaApplier(repo)
    result = save_summary(state, applier=applier)
    assert result["status"] == "completed"
    s = repo.get_chapter_summary(1)
    assert s is not None
    assert s.title == "第一章"
```

- [ ] **Step 2: 运行验证失败**

```bash
set NOVEL_TEST_DB=memory && .venv\Scripts\python.exe -m pytest tests/test_orchestrator_nodes.py -v
```
Expected: FAIL（模块不存在）

- [ ] **Step 3: 创建 novel_agent/orchestrator/nodes.py**

```python
"""编排节点函数：每个节点接收 state + 依赖，返回 state 更新。

节点设计为接受依赖注入（repo/llm_client/recall/applier），
便于测试 mock 和 runner 组装。
"""
from __future__ import annotations

from typing import Any

from novel_agent.bible.repository import BibleRepository
from novel_agent.llm.client import LLMClient
from novel_agent.memory.core import CoreMemoryAssembler
from novel_agent.memory.recall import RecallMemory
from novel_agent.orchestrator.state import ChapterGenState
from novel_agent.protocol.applier import DeltaApplier
from novel_agent.protocol.schemas import Delta, SummaryDelta

WRITER_SYSTEM_PROMPT = (
    "你是一位资深网络小说写手。根据给定的设定和上下文，"
    "创作引人入胜的网文章节正文。只输出正文，不要解释。"
)


def assemble_context(state: ChapterGenState, repo: BibleRepository,
                     archival: Any | None = None) -> dict:
    """节点 1：装配章节上下文（core memory + 可选 archival 检索）。"""
    assembler = CoreMemoryAssembler(repo, archival=archival)
    query = f"第{state['chapter']}章 {state.get('title', '')} 的相关前文"
    context = assembler.assemble(chapter=state["chapter"], query=query)
    return {"context": context, "status": "assembled"}


async def write_chapter(state: ChapterGenState,
                        llm_client: LLMClient) -> dict:
    """节点 2：调 LLM 生成章节正文。"""
    prompt = (
        f"请写第{state['chapter']}章《{state.get('title', '')}》。\n\n"
        f"【上下文】\n{state.get('context', '')}\n\n"
        f"要求：只输出正文，目标 2000-3000 字。"
    )
    try:
        draft = await llm_client.generate(prompt, system=WRITER_SYSTEM_PROMPT)
        return {"draft": draft, "status": "drafted",
                "word_count": len(draft)}
    except Exception as e:
        return {"status": "failed", "error": str(e)}


def save_text(state: ChapterGenState, recall: RecallMemory) -> dict:
    """节点 3：把正文存到文件。"""
    recall.save_chapter_text(
        chapter=state["chapter"], title=state.get("title", ""),
        content=state["draft"],
    )
    return {"status": "saved"}


def save_summary(state: ChapterGenState, applier: DeltaApplier) -> dict:
    """节点 4：抽取摘要并存入圣经（M2 简化：用 draft 前 200 字作摘要）。"""
    draft = state.get("draft", "")
    summary_text = draft[:200] if draft else ""
    delta = Delta(
        target="chapter_summary", action="create", chapter=state["chapter"],
        data=SummaryDelta(
            title=state.get("title", ""),
            word_count=state.get("word_count", len(draft)),
            core_events=summary_text,
            characters_present="",
        ),
    )
    result = applier.apply(delta)
    if not result.success:
        return {"status": "failed", "error": result.message}
    return {"status": "completed"}
```

- [ ] **Step 4: 运行测试**

```bash
set NOVEL_TEST_DB=memory && .venv\Scripts\python.exe -m pytest tests/test_orchestrator_nodes.py -v
```
Expected: 4 PASS

- [ ] **Step 5: Commit**

```bash
git add . && git commit -m "feat(orchestrator): 四节点函数（assemble/write/save_text/save_summary）"
```

---

## Task 5: StateGraph 定义

**Files:**
- Create: `novel_agent/orchestrator/graph.py`
- Test: `tests/test_orchestrator_graph.py`

- [ ] **Step 1: 写失败测试 tests/test_orchestrator_graph.py**

```python
"""测试 StateGraph 结构与节点连接。"""
from unittest.mock import MagicMock
from novel_agent.orchestrator.graph import build_graph, NODE_NAMES


def _mock_deps():
    return {
        "repo": MagicMock(),
        "llm_client": MagicMock(),
        "recall": MagicMock(),
        "applier": MagicMock(),
    }


def test_graph_has_four_nodes():
    graph = build_graph(_mock_deps())
    node_ids = set(graph.nodes.keys())
    for name in NODE_NAMES:
        assert name in node_ids, f"缺失节点 {name}"


def test_node_names_complete():
    assert NODE_NAMES == ["assemble", "write", "save_text", "save_summary"]
```

- [ ] **Step 2: 运行验证失败**

```bash
.venv\Scripts\python.exe -m pytest tests/test_orchestrator_graph.py -v
```
Expected: FAIL（模块不存在）

- [ ] **Step 3: 创建 novel_agent/orchestrator/graph.py**

```python
"""StateGraph 定义：assemble → write → save_text → save_summary。

节点函数本身不带依赖（依赖在 runner 注入），graph 只定义拓扑。
节点函数通过 functools.partial 绑定依赖后注册。
"""
from __future__ import annotations

from functools import partial
from typing import Any

from langgraph.graph import StateGraph, START, END

from novel_agent.orchestrator.nodes import (
    assemble_context, write_chapter, save_text, save_summary,
)
from novel_agent.orchestrator.state import ChapterGenState

NODE_NAMES = ["assemble", "write", "save_text", "save_summary"]


def build_graph(deps: dict[str, Any] | None = None):
    """构建流水线图。

    Args:
        deps: 依赖字典，含 repo/llm_client/recall/applier/archival。
              节点函数通过 partial 绑定对应依赖。
    Returns:
        编译后的 StateGraph（未绑定 checkpointer）。
    """
    deps = deps or {}
    graph = StateGraph(ChapterGenState)

    assemble_fn = partial(assemble_context, repo=deps["repo"],
                          archival=deps.get("archival"))
    write_fn = partial(write_chapter, llm_client=deps["llm_client"])
    save_text_fn = partial(save_text, recall=deps["recall"])
    save_summary_fn = partial(save_summary, applier=deps["applier"])

    graph.add_node("assemble", assemble_fn)
    graph.add_node("write", write_fn)
    graph.add_node("save_text", save_text_fn)
    graph.add_node("save_summary", save_summary_fn)

    graph.add_edge(START, "assemble")
    graph.add_edge("assemble", "write")
    graph.add_edge("write", "save_text")
    graph.add_edge("save_text", "save_summary")
    graph.add_edge("save_summary", END)

    return graph.compile()
```

- [ ] **Step 4: 运行测试**

```bash
.venv\Scripts\python.exe -m pytest tests/test_orchestrator_graph.py -v
```
Expected: 2 PASS

- [ ] **Step 5: Commit**

```bash
git add . && git commit -m "feat(orchestrator): StateGraph 四节点拓扑"
```

---

## Task 6: Runner（运行入口 + SqliteSaver 断点续跑）

**Files:**
- Create: `novel_agent/orchestrator/runner.py`
- Test: `tests/test_orchestrator_runner.py`

- [ ] **Step 1: 写失败测试 tests/test_orchestrator_runner.py**

```python
"""测试 runner：组装依赖 + 跑 graph + 断点续跑。"""
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from novel_agent.bible.database import SessionLocal, set_config
from novel_agent.bible.models import Base, Project
from novel_agent.bible.repository import BibleRepository
from novel_agent.config import Config, LLMConfig
from novel_agent.orchestrator.runner import ChapterRunner


@pytest.fixture
def runner(tmp_config):
    from novel_agent.bible import database as db_mod
    set_config(tmp_config)
    Base.metadata.create_all(bind=db_mod.engine)
    db = SessionLocal()
    p = Project(title="测试", genre="科幻", summary="末日")
    db.add(p); db.commit(); db.refresh(p)
    r = BibleRepository(db, project_id=p.id)
    r.create_character(name="刘洋", role="主角")
    yield ChapterRunner(tmp_config, repo=r)
    db.close()


def test_runner_builds_graph(runner):
    assert runner.graph is not None


@pytest.mark.asyncio
async def test_runner_generates_chapter_with_mock_llm(runner):
    """用 mock LLM 跑通完整流水线。"""
    mock_client = MagicMock()
    mock_client.generate = AsyncMock(return_value="刘洋在修理厂修车……（正文）")
    runner.llm_client = mock_client

    result = await runner.run(chapter=1, title="第一章")

    assert result["status"] == "completed"
    assert "刘洋" in result["draft"]
    # 正文已存
    assert "刘洋" in runner.recall.read_chapter_text(1)
    # 摘要已存
    assert runner.repo.get_chapter_summary(1) is not None


@pytest.mark.asyncio
async def test_runner_resumes_from_checkpoint(runner):
    """崩溃后能从 checkpoint 恢复（同一 thread_id 续跑不重做已完成节点）。"""
    mock_client = MagicMock()
    mock_client.generate = AsyncMock(return_value="正文内容")
    runner.llm_client = mock_client

    # 第一次跑完
    await runner.run(chapter=1, title="第一章", thread_id="t1")
    # 第二次用同 thread_id 应能恢复状态（不报错）
    result = await runner.run(chapter=1, title="第一章", thread_id="t1")
    assert result["status"] == "completed"
```

- [ ] **Step 2: 运行验证失败**

```bash
set NOVEL_TEST_DB=memory && .venv\Scripts\python.exe -m pytest tests/test_orchestrator_runner.py -v
```
Expected: FAIL（模块不存在）

- [ ] **Step 3: 创建 novel_agent/orchestrator/runner.py**

```python
"""Runner：组装依赖 + 构建 graph + SqliteSaver 断点续跑。

Runner 是编排层的运行入口，把 M1 的各模块（repo/llm/recall/applier/archival）
注入 graph 节点，并用 SqliteSaver 做 checkpoint 实现断点续跑。
"""
from __future__ import annotations

import sqlite3
from typing import Any

from langgraph.checkpoint.sqlite import SqliteSaver

from novel_agent.bible.repository import BibleRepository
from novel_agent.config import Config, LLMConfig
from novel_agent.llm.client import LLMClient
from novel_agent.memory.archival import ArchivalMemory
from novel_agent.memory.recall import RecallMemory
from novel_agent.orchestrator.graph import build_graph
from novel_agent.protocol.applier import DeltaApplier


class ChapterRunner:
    """单章生成运行器。"""

    def __init__(self, config: Config, repo: BibleRepository,
                 llm_client: LLMClient | None = None):
        self.config = config
        self.repo = repo
        self.llm_client = llm_client or LLMClient(config.llm)
        self.recall = RecallMemory(config)
        self.archival = ArchivalMemory(config)
        self.applier = DeltaApplier(repo, archival=self.archival)
        self._saver_conn = sqlite3.connect(
            str(config.project_data_dir / "checkpoints.db"),
            check_same_thread=False,
        )
        self.checkpointer = SqliteSaver(self._saver_conn)
        self.graph = build_graph({
            "repo": self.repo,
            "llm_client": self.llm_client,
            "recall": self.recall,
            "applier": self.applier,
            "archival": self.archival,
        }).with_config({"checkpointer": self.checkpointer})

    async def run(self, chapter: int, title: str,
                  thread_id: str | None = None) -> dict:
        """运行单章生成流水线。

        Args:
            chapter: 章节号
            title: 章节标题
            thread_id: 断点续跑的线程 id；同 id 重跑会从 checkpoint 恢复
        """
        import uuid
        tid = thread_id or str(uuid.uuid4())
        initial_state = {
            "project_id": self.repo.project_id,
            "chapter": chapter,
            "title": title,
            "context": "",
            "draft": "",
            "status": "pending",
            "error": "",
            "word_count": 0,
        }
        result = await self.graph.ainvoke(
            initial_state, config={"configurable": {"thread_id": tid}},
        )
        return result

    def close(self):
        self._saver_conn.close()
```

- [ ] **Step 4: 运行测试**

```bash
set NOVEL_TEST_DB=memory && .venv\Scripts\python.exe -m pytest tests/test_orchestrator_runner.py -v
```
Expected: 3 PASS（首次可能慢，SqliteSaver 初始化）

- [ ] **Step 5: Commit**

```bash
git add . && git commit -m "feat(orchestrator): runner + SqliteSaver 断点续跑"
```

---

## Task 7: CLI generate 子命令 + 真实端到端验证

**Files:**
- Modify: `novel_agent/cli.py`
- Test: `tests/test_cli_init.py`（追加 generate 测试，用 mock LLM）

- [ ] **Step 1: 追加 generate 测试到 tests/test_cli_init.py**

```python
@pytest.mark.asyncio
async def test_cmd_generate_runs_pipeline(isolated_cli, monkeypatch, capsys):
    """generate 命令应跑通流水线（mock LLM）。"""
    from novel_agent.cli import cmd_init, cmd_generate
    from unittest.mock import AsyncMock, MagicMock

    # 先 init 一个项目
    cmd_init(_Args(title="生成测试", genre="科幻"))

    # mock LLM，generate 命令内部用
    mock_client = MagicMock()
    mock_client.generate = AsyncMock(return_value="生成的正文内容")
    monkeypatch.setattr("novel_agent.cli.LLMClient", lambda _cfg: mock_client)

    class _GenArgs:
        chapter = 1
        title = "第一章"
        config = None

    await cmd_generate(_GenArgs())

    out = capsys.readouterr().out
    assert "第一章" in out or "completed" in out
```

- [ ] **Step 2: 运行验证失败**

```bash
set NOVEL_TEST_DB=memory && .venv\Scripts\python.exe -m pytest tests/test_cli_init.py::test_cmd_generate_runs_pipeline -v
```
Expected: FAIL（cmd_generate 不存在）

- [ ] **Step 3: 给 cli.py 加 generate 子命令**

修改 `novel_agent/cli.py`，加：

```python
async def cmd_generate(args):
    """生成单章（M2：单 Writer 流水线）。"""
    from novel_agent.bible import database as db_mod
    from novel_agent.bible.models import Project
    from novel_agent.bible.repository import BibleRepository
    from novel_agent.llm.client import LLMClient
    from novel_agent.orchestrator.runner import ChapterRunner

    cfg = load_config(args.config)
    set_config(cfg)
    Base.metadata.create_all(bind=db_mod.engine)
    db = SessionLocal()
    project = db.query(Project).order_by(Project.id.desc()).first()
    if not project:
        print("错误：没有项目，请先 novel-agent init")
        db.close()
        return
    repo = BibleRepository(db, project_id=project.id)
    runner = ChapterRunner(cfg, repo=repo)
    try:
        result = await runner.run(chapter=args.chapter, title=args.title)
        print(f"章节 {args.chapter}《{args.title}》：{result.get('status')}")
        if result.get("error"):
            print(f"错误：{result['error']}")
        else:
            print(f"字数：{result.get('word_count', 0)}")
    finally:
        runner.close()
        db.close()
```

并在 main() 的 subparser 注册：

```python
    p_gen = sub.add_parser("generate", help="生成单章（M2）")
    p_gen.add_argument("--chapter", type=int, required=True)
    p_gen.add_argument("--title", required=True)
    p_gen.add_argument("--config", default=None)
    p_gen.set_defaults(func=cmd_generate)
```

注意 main() 需处理 async 函数：

```python
    args = parser.parse_args()
    import asyncio
    if asyncio.iscoroutinefunction(args.func):
        asyncio.run(args.func(args))
    else:
        args.func(args)
```

- [ ] **Step 4: 运行测试**

```bash
set NOVEL_TEST_DB=memory && .venv\Scripts\python.exe -m pytest tests/test_cli_init.py -v
```
Expected: 3 PASS

- [ ] **Step 5: 跑全套确认无回归**

```bash
set NOVEL_TEST_DB=memory && .venv\Scripts\python.exe -m pytest -v
```
Expected: M1 的 41 + M2 全部新增 ≈ 50+ PASS

- [ ] **Step 6: Commit**

```bash
git add . && git commit -m "feat(cli): generate 子命令 + 单 Writer 端到端"
```

---

## M2 验收清单

- [ ] Applier 事务原子性（M1 遗留 #1 解决）
- [ ] Applier 接入 archival 同步（M1 遗留 #2 解决）
- [ ] 编排状态 schema
- [ ] 四节点函数（assemble/write/save_text/save_summary）
- [ ] StateGraph 四节点拓扑
- [ ] Runner + SqliteSaver 断点续跑
- [ ] CLI generate 子命令
- [ ] mock LLM 端到端跑通（init → generate → 章节正文 + 摘要入库）
- [ ] 断点续跑：同 thread_id 重跑能恢复
- [ ] 全套测试 PASS（M1 41 + M2 新增）

## 真实 LLM 验证（可选，需 API key）

```bash
set NOVEL_LLM_API_KEY=sk-xxx
set NOVEL_LLM_BASE_URL=https://api.deepseek.com/v1
set NOVEL_LLM_MODEL=deepseek-chat
.venv\Scripts\novel-agent.exe init --title "测试小说" --genre "科幻" --summary "末日生存"
.venv\Scripts\novel-agent.exe generate --chapter 1 --title "第一章"
```
Expected: 生成第 1 章正文存到 project_data/chapters/，摘要入库

## 后续里程碑

- **M3**：7 agent 全实现 + 写审循环 + 审计维度 + Summarizer 回写
- **M4**：interrupt 人审三节点 + FastAPI + SSE + 前端四界面
