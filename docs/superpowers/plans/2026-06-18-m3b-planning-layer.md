# M3b：卷级规划层 实现计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development to implement this plan task-by-task.

**Goal:** 在 M3 单章写审之上加卷级规划层：Planner（全书→卷→弧规划）、Architect（设定组：世界观/角色/力量体系）、Outliner（本卷章节细纲 + 伏笔布局）+ 人审①（大纲审核，LangGraph interrupt）。产出经 DeltaApplier 写入圣经，供 M3 的单章流水线消费。

**Architecture:** 新增 `planning/` 包：三个 agent + 卷级 StateGraph。卷级 graph 用 `interrupt` 实现人审①暂停（大纲生成后挂起等用户审核/批注，resume 传回决策）。审核通过后，章节细纲和伏笔台账已在圣经，M3 的 ChapterRunner 可逐章消费。

**Tech Stack:** Python 3.11、LangGraph 1.2（interrupt + Command resume）、复用 M1/M2/M3 全部模块

---

## 前置说明

- 工作目录 `C:\Users\LYY\Desktop\vibe coding`，venv `.venv`，测试 `set NOVEL_TEST_DB=memory`
- M1/M2/M3 已合并 main（77 测试），本计划从 main 拉 `m3b-planning` 分支
- LangGraph interrupt API：`from langgraph.types import interrupt, Command`
- 人审①：大纲生成后 `interrupt({"outline": ...})` 挂起，用户在前端审核后 `Command(resume={"approved": True/False, "edits": ...})` 恢复

## 文件结构（M3b 范围）

```
novel_agent/
├── planning/                        # 新增：卷级规划层
│   ├── __init__.py
│   ├── agents.py                    # Planner/Architect/Outliner 三个 agent
│   ├── state.py                     # 卷级规划状态 schema
│   ├── graph.py                     # 卷级 StateGraph（含 interrupt 人审①）
│   └── runner.py                    # VolumeRunner（建卷级 graph + 跑 + resume）
├── orchestrator/
│   └── cli.py 或 cli.py             # 修改：加 plan 命令
tests/
├── test_planning_agents.py
├── test_planning_graph.py
└── test_planning_runner.py
```

---

## Task 1: 规划 agent（Planner/Architect/Outliner）

**Files:**
- Create: `novel_agent/planning/__init__.py`, `novel_agent/planning/agents.py`
- Test: `tests/test_planning_agents.py`

- [ ] **Step 1: 写失败测试 tests/test_planning_agents.py**

```python
"""测试规划三 agent。"""
import pytest
from unittest.mock import AsyncMock

from novel_agent.planning.agents import Planner, Architect, Outliner
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


@pytest.mark.asyncio
async def test_outliner_produces_chapter_outline(repo):
    mock_llm = AsyncMock()
    mock_llm.generate = AsyncMock(return_value="""```json
{"chapters":[{"chapter":1,"title":"无声征召","summary":"征召事件","foreshadows":[{"id":"S-001","description":"文物箱","plant_chapter":1,"resolve_chapter":3}]}]}
```""")
    outliner = Outliner(mock_llm)
    outline = await planner_outline(outliner, project=repo.get_project(), volume="卷一", chapter_count=5)
    assert "chapters" in outline
    assert len(outline["chapters"]) >= 1


async def planner_outline(outliner, project, volume, chapter_count):
    return await outliner.outline(project=project, volume=volume, chapter_count=chapter_count)
```

- [ ] **Step 2: 运行验证失败**

```bash
.venv\Scripts\python.exe -m pytest tests/test_planning_agents.py -v
```
Expected: FAIL

- [ ] **Step 3: 创建 novel_agent/planning/__init__.py**

```python
"""卷级规划层：Planner/Architect/Outliner + 人审①。"""
```

- [ ] **Step 4: 创建 novel_agent/planning/agents.py**

```python
"""规划三 agent：Planner（卷规划）/Architect（设定）/Outliner（章节细纲+伏笔）。

每个 agent 调 LLM 产出结构化 JSON，经 DeltaApplier 写入圣经。
"""
from __future__ import annotations

import json
import re

from novel_agent.bible.models import Project
from novel_agent.llm.client import LLMClient


def _extract_json(text: str) -> dict:
    """从 LLM 输出提取 JSON（容忍代码块包裹）。"""
    m = re.search(r"```(?:json)?\s*\n?(.*?)\n?```", text, re.DOTALL)
    candidate = m.group(1) if m else text
    try:
        return json.loads(candidate)
    except json.JSONDecodeError:
        start = candidate.find("{")
        end = candidate.rfind("}")
        if start >= 0 and end > start:
            return json.loads(candidate[start:end + 1])
        return {}


PLANNER_SYSTEM = "你是网文总编。规划全书卷次结构、节奏曲线、爽点分布。只输出 JSON。"
ARCHITECT_SYSTEM = "你是网文设定师。设计世界观、角色、力量体系。只输出 JSON。"
OUTLINER_SYSTEM = "你是网文大纲师。规划本卷章节细纲和伏笔布局。只输出 JSON。"


class Planner:
    """总编：全书→卷→弧三级规划。"""
    def __init__(self, llm_client: LLMClient):
        self.llm_client = llm_client

    async def plan(self, project: Project, target_chapters: int = 30) -> dict:
        prompt = (
            f"为以下小说规划卷次结构，目标 {target_chapters} 章。\n\n"
            f"标题：{project.title}\n类型：{project.genre}\n简介：{project.summary}\n\n"
            f"输出 JSON：{{\"volumes\":[{{\"name\":\"\",\"theme\":\"\","
            f"\"chapters\":0,\"summary\":\"\"}}]}}\n只输出 JSON。"
        )
        raw = await self.llm_client.generate(prompt, system=PLANNER_SYSTEM)
        return _extract_json(raw)


class Architect:
    """设定组：世界观/角色/力量体系。"""
    def __init__(self, llm_client: LLMClient):
        self.llm_client = llm_client

    async def design(self, project: Project, volume_plan: dict) -> dict:
        prompt = (
            f"为以下小说设计核心设定。\n\n"
            f"标题：{project.title}\n类型：{project.genre}\n简介：{project.summary}\n"
            f"卷规划：{json.dumps(volume_plan, ensure_ascii=False)}\n\n"
            f"输出 JSON：{{\"characters\":[{{\"name\":\"\",\"role\":\"\","
            f"\"personality\":\"\",\"motivation\":\"\"}}],"
            f"\"world_settings\":[{{\"category\":\"\",\"title\":\"\",\"content\":\"\"}}]}}\n"
            f"只输出 JSON。"
        )
        raw = await self.llm_client.generate(prompt, system=ARCHITECT_SYSTEM)
        return _extract_json(raw)


class Outliner:
    """大纲师：本卷章节细纲 + 伏笔布局。"""
    def __init__(self, llm_client: LLMClient):
        self.llm_client = llm_client

    async def outline(self, project: Project, volume: str,
                      chapter_count: int) -> dict:
        prompt = (
            f"为《{project.title}》的{volume}规划 {chapter_count} 章细纲。\n\n"
            f"类型：{project.genre}\n简介：{project.summary}\n\n"
            f"输出 JSON：{{\"chapters\":[{{\"chapter\":1,\"title\":\"\","
            f"\"summary\":\"\",\"foreshadows\":[{{\"id\":\"S-001\","
            f"\"description\":\"\",\"plant_chapter\":1,\"resolve_chapter\":3}}]}}]}}\n"
            f"只输出 JSON。"
        )
        raw = await self.llm_client.generate(prompt, system=OUTLINER_SYSTEM)
        return _extract_json(raw)
```

- [ ] **Step 5: 运行测试**

```bash
set NOVEL_TEST_DB=memory && .venv\Scripts\python.exe -m pytest tests/test_planning_agents.py -v
```
Expected: 3 PASS

- [ ] **Step 6: Commit**

```bash
git add . && git commit -m "feat(planning): Planner/Architect/Outliner 三 agent"
```

---

## Task 2: 规划状态 schema + 卷级 graph（含 interrupt 人审①）

**Files:**
- Create: `novel_agent/planning/state.py`, `novel_agent/planning/graph.py`
- Test: `tests/test_planning_graph.py`

- [ ] **Step 1: 创建 state.py**

```python
"""卷级规划状态 schema。"""
from __future__ import annotations
from typing import TypedDict


class VolumePlanState(TypedDict, total=False):
    project_id: int
    volume: str               # 卷名
    chapter_count: int        # 本卷章节数
    volume_plan: dict         # Planner 产出的卷规划
    settings: dict            # Architect 产出的设定
    outline: dict             # Outliner 产出的章节细纲
    review_decision: dict     # 人审①的决策（approved/edits）
    status: str               # pending/planned/designed/outlined/reviewing/approved/rejected/failed
    error: str
```

- [ ] **Step 2: 创建 graph.py（含 interrupt 人审①）**

```python
"""卷级 StateGraph：plan→design→outline→[人审① interrupt]→apply_to_bible。

人审①：大纲生成后 interrupt 挂起，用户审核后 Command(resume=...) 恢复。
"""
from __future__ import annotations

from functools import partial
from typing import Any

from langgraph.graph import StateGraph, START, END
from langgraph.types import interrupt

from novel_agent.bible.repository import BibleRepository
from novel_agent.planning.agents import Planner, Architect, Outliner
from novel_agent.planning.state import VolumePlanState
from novel_agent.protocol.applier import DeltaApplier
from novel_agent.protocol.schemas import (
    Delta, CharacterDelta, OutlineDelta, ForeshadowDelta,
)


async def plan_volume(state, planner, repo):
    project = repo.get_project()
    plan = await planner.plan(project, state.get("chapter_count", 30))
    return {"volume_plan": plan, "status": "planned"}


async def design_settings(state, architect, repo):
    project = repo.get_project()
    settings = await architect.design(project, state.get("volume_plan", {}))
    return {"settings": settings, "status": "designed"}


async def outline_chapters(state, outliner, repo):
    project = repo.get_project()
    outline = await outliner.outline(
        project, state.get("volume", "卷一"), state.get("chapter_count", 30))
    return {"outline": outline, "status": "outlined"}


def human_review_outline(state):
    """人审①：interrupt 挂起等用户审核大纲。"""
    decision = interrupt({
        "type": "outline_review",
        "volume_plan": state.get("volume_plan", {}),
        "settings": state.get("settings", {}),
        "outline": state.get("outline", {}),
    })
    return {"review_decision": decision, "status": "approved" if decision.get("approved") else "rejected"}


def route_after_review(state):
    if state.get("review_decision", {}).get("approved"):
        return "apply"
    return "end_rejected"


def apply_to_bible(state, repo, applier):
    """把审核通过的设定/大纲/伏笔写入圣经。"""
    settings = state.get("settings", {})
    # 写角色
    for c in settings.get("characters", []):
        applier.apply(Delta(
            target="character", action="create", chapter=0,
            data=CharacterDelta(**{k: c.get(k, "") for k in
                ("name", "role", "personality", "motivation")}),
        ))
    # 写世界设定
    for ws in settings.get("world_settings", []):
        repo.create_world_setting(**ws) if hasattr(repo, "create_world_setting") else None
    # 写大纲
    for ch in state.get("outline", {}).get("chapters", []):
        applier.apply(Delta(
            target="outline", action="create", chapter=ch.get("chapter", 0),
            data=OutlineDelta(level="chapter", order=ch.get("chapter", 0),
                              title=ch.get("title", ""), summary=ch.get("summary", "")),
        ))
        # 写伏笔
        for f in ch.get("foreshadows", []):
            applier.apply(Delta(
                target="foreshadow", action="plant", chapter=f.get("plant_chapter", 0),
                data=ForeshadowDelta(
                    foreshadow_id=f.get("id", ""), description=f.get("description", ""),
                    plant_chapter=f.get("plant_chapter", 0),
                    planned_resolve_chapter=f.get("resolve_chapter", 0)),
            ))
    return {"status": "approved"}


def build_volume_graph(deps: dict[str, Any] | None = None):
    deps = deps or {}
    graph = StateGraph(VolumePlanState)

    graph.add_node("plan", partial(plan_volume, planner=deps["planner"], repo=deps["repo"]))
    graph.add_node("design", partial(design_settings, architect=deps["architect"], repo=deps["repo"]))
    graph.add_node("outline", partial(outline_chapters, outliner=deps["outliner"], repo=deps["repo"]))
    graph.add_node("review", human_review_outline)
    graph.add_node("apply", partial(apply_to_bible, repo=deps["repo"], applier=deps["applier"]))

    graph.add_edge(START, "plan")
    graph.add_edge("plan", "design")
    graph.add_edge("design", "outline")
    graph.add_edge("outline", "review")
    graph.add_conditional_edges("review", route_after_review,
                                {"apply": "apply", "end_rejected": END})
    graph.add_edge("apply", END)
    return graph.compile()
```

- [ ] **Step 3: 写测试 tests/test_planning_graph.py**

```python
"""测试卷级 graph 结构 + interrupt 人审。"""
from unittest.mock import MagicMock, AsyncMock
from novel_agent.planning.graph import build_volume_graph


def _mock_deps():
    return {
        "planner": MagicMock(), "architect": MagicMock(), "outliner": MagicMock(),
        "repo": MagicMock(), "applier": MagicMock(),
    }


def test_graph_has_five_nodes():
    graph = build_volume_graph(_mock_deps())
    node_ids = set(graph.nodes.keys())
    for name in ["plan", "design", "outline", "review", "apply"]:
        assert name in node_ids, f"缺失节点 {name}"
```

- [ ] **Step 4: 运行测试**

```bash
.venv\Scripts\python.exe -m pytest tests/test_planning_graph.py -v
```
Expected: 1 PASS

- [ ] **Step 5: Commit**

```bash
git add . && git commit -m "feat(planning): 卷级 graph + interrupt 人审①"
```

---

## Task 3: VolumeRunner + 端到端（mock + interrupt resume）

**Files:**
- Create: `novel_agent/planning/runner.py`
- Test: `tests/test_planning_runner.py`

- [ ] **Step 1: 创建 runner.py**

```python
"""VolumeRunner：卷级规划运行器。

跑卷级 graph，遇人审① interrupt 挂起；
用户审核后调 resume(decision) 恢复，决策写入圣经。
"""
from __future__ import annotations

import sqlite3
import uuid

from langgraph.checkpoint.sqlite import SqliteSaver
from langgraph.types import Command

from novel_agent.bible.repository import BibleRepository
from novel_agent.config import Config
from novel_agent.llm.client import LLMClient
from novel_agent.memory.archival import ArchivalMemory
from novel_agent.planning.agents import Planner, Architect, Outliner
from novel_agent.planning.graph import build_volume_graph
from novel_agent.protocol.applier import DeltaApplier


class VolumeRunner:
    def __init__(self, config: Config, repo: BibleRepository,
                 llm_client: LLMClient | None = None):
        self.config = config
        self.repo = repo
        client = llm_client or LLMClient(config.llm)
        self.planner = Planner(client)
        self.architect = Architect(client)
        self.outliner = Outliner(client)
        self.archival = ArchivalMemory(config)
        self.applier = DeltaApplier(repo, archival=self.archival)
        config.project_data_dir.mkdir(parents=True, exist_ok=True)
        self._saver_conn = sqlite3.connect(
            str(config.project_data_dir / "volume_checkpoints.db"),
            check_same_thread=False)
        self.checkpointer = SqliteSaver(self._saver_conn)
        self.checkpointer.setup()
        self.graph = build_volume_graph({
            "planner": self.planner, "architect": self.architect,
            "outliner": self.outliner, "repo": self.repo, "applier": self.applier,
        }).with_config({"checkpointer": self.checkpointer})

    async def run(self, volume: str, chapter_count: int = 30,
                  thread_id: str | None = None) -> dict:
        tid = thread_id or str(uuid.uuid4())
        state = {"project_id": self.repo.project_id, "volume": volume,
                 "chapter_count": chapter_count, "status": "pending"}
        return await self.graph.ainvoke(
            state, config={"configurable": {"thread_id": tid}})

    async def resume(self, decision: dict, thread_id: str) -> dict:
        """人审①后恢复：传 approved/edits。"""
        return await self.graph.ainvoke(
            Command(resume=decision),
            config={"configurable": {"thread_id": thread_id}})

    def close(self):
        self._saver_conn.close()
```

- [ ] **Step 2: 写端到端测试（mock LLM + interrupt resume）**

```python
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
    """跑到人审①应 interrupt 挂起（status=reviewing 或抛 interrupt）。"""
    mock_llm = MagicMock()
    mock_llm.generate = AsyncMock(side_effect=[
        '{"volumes":[{"name":"卷一","chapters":5}]}',  # plan
        '{"characters":[{"name":"刘洋","role":"主角","personality":"冷静"}],"world_settings":[]}',  # design
        '{"chapters":[{"chapter":1,"title":"第一章","summary":"事件","foreshadows":[]}]}',  # outline
    ])
    runner = make_runner(llm_client=mock_llm)

    # 跑到 review 应 interrupt
    result = await runner.run(volume="卷一", chapter_count=5, thread_id="v1")
    # interrupt 后 graph 返回当前状态
    assert result.get("status") in ("outlined", "reviewing") or "outline" in result


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
```

- [ ] **Step 3: 运行测试**

```bash
set NOVEL_TEST_DB=memory && .venv\Scripts\python.exe -m pytest tests/test_planning_runner.py -v
```
Expected: 2 PASS

- [ ] **Step 4: 跑全套无回归**

```bash
set NOVEL_TEST_DB=memory && .venv\Scripts\python.exe -m pytest
```
Expected: M1+M2+M3 77 + M3b 新增

- [ ] **Step 5: Commit**

```bash
git add . && git commit -m "feat(planning): VolumeRunner + interrupt/resume 端到端"
```

---

## Task 4: CLI plan 命令

**Files:**
- Modify: `novel_agent/cli.py`
- Test: 追加到 `tests/test_cli_generate.py` 或新建

- [ ] **Step 1: 给 cli.py 加 plan 命令**

```python
async def cmd_plan(args):
    """卷级规划（M3b）：plan → 人审① → 写入圣经。"""
    from novel_agent.bible import database as db_mod
    from novel_agent.planning.runner import VolumeRunner

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
    runner = VolumeRunner(cfg, repo=repo)
    try:
        result = await runner.run(volume=args.volume, chapter_count=args.chapters, thread_id=args.thread_id)
        print(f"规划完成，等待人审①。thread_id={args.thread_id}")
        print(f"卷规划：{result.get('volume_plan', {})}")
        print(f"用 novel-agent resume --thread-id {args.thread_id} --approve 恢复")
    finally:
        runner.close()
        db.close()


async def cmd_resume(args):
    """人审①后恢复规划。"""
    from novel_agent.bible import database as db_mod
    from novel_agent.planning.runner import VolumeRunner

    cfg = load_config(args.config)
    set_config(cfg)
    Base.metadata.create_all(bind=db_mod.engine)
    db = SessionLocal()
    project = db.query(Project).order_by(Project.id.desc()).first()
    repo = BibleRepository(db, project_id=project.id)
    runner = VolumeRunner(cfg, repo=repo)
    try:
        decision = {"approved": args.approve, "edits": args.edits or ""}
        result = await runner.resume(decision, thread_id=args.thread_id)
        print(f"恢复完成：{result.get('status')}")
    finally:
        runner.close()
        db.close()
```

在 main() 注册：
```python
    p_plan = sub.add_parser("plan", help="卷级规划（M3b）")
    p_plan.add_argument("--volume", required=True)
    p_plan.add_argument("--chapters", type=int, default=30)
    p_plan.add_argument("--thread-id", required=True)
    p_plan.add_argument("--config", default=None)
    p_plan.set_defaults(func=cmd_plan)

    p_resume = sub.add_parser("resume", help="人审①后恢复规划")
    p_resume.add_argument("--thread-id", required=True)
    p_resume.add_argument("--approve", action="store_true")
    p_resume.add_argument("--edits", default="")
    p_resume.add_argument("--config", default=None)
    p_resume.set_defaults(func=cmd_resume)
```

- [ ] **Step 2: 运行全套 + Commit**

```bash
set NOVEL_TEST_DB=memory && .venv\Scripts\python.exe -m pytest
git add . && git commit -m "feat(cli): plan/resume 命令（卷级规划+人审①）"
```

---

## M3b 验收清单

- [ ] Planner/Architect/Outliner 三 agent
- [ ] 卷级 StateGraph（plan→design→outline→review→apply）
- [ ] interrupt 人审①（大纲审核挂起）
- [ ] VolumeRunner + resume
- [ ] 端到端：规划→interrupt→resume(approve)→写入圣经
- [ ] CLI plan/resume 命令
- [ ] 全套测试 PASS（M1+M2+M3 77 + M3b 新增）

## 后续

- **M4**：interrupt 人审②③ + FastAPI + SSE + 前端四界面
