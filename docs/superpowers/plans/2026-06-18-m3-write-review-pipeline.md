# M3：单章写审流水线 实现计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 把 M2 的线性 `assemble→write→save` 扩展为带写审分离 + 反馈循环的单章流水线：`assemble→write→audit→{达标:polish | 不达标:write回环≤3}→summarize`。新增 Auditor（独立审校）、Polisher（润色），升级 Summarizer（真实摘要抽取）。审计维度融合 15维+Fitness+Acid Test。

**Architecture:** 新增 `audit/` 包：审计维度定义 + Auditor agent + 审计报告 schema。扩展 `orchestrator/`：state 加 draft_version/review_iterations/audit_report 字段，nodes 加 audit/polish 节点，graph 改为带条件边的回环结构。写审分离铁律：Auditor 与 Writer 是独立 LLM 调用，Auditor 只看成稿+圣经，不知生成过程。

**Tech Stack:** Python 3.11、LangGraph 1.2（条件边 add_conditional_edges）、复用 M1/M2 全部模块

---

## 前置说明

- 工作目录：`C:\Users\LYY\Desktop\vibe coding`，venv `.venv`，用 `.venv\Scripts\python.exe`
- 测试用 `set NOVEL_TEST_DB=memory`
- M1/M2 已合并 main（57 测试），本计划从 main 拉新分支 `m3-write-review`
- 复用 M2 的 ChapterRunner + SqliteSaver 断点续跑（M3 不重写 runner，只扩展 graph）

## 文件结构（M3 范围）

```
novel_agent/
├── audit/                           # 新增：审计层
│   ├── __init__.py
│   ├── dimensions.py                # 审计维度定义（15维+Fitness+Acid Test 融合）
│   ├── schemas.py                   # AuditReport / Issue / Score pydantic 模型
│   └── auditor.py                   # Auditor agent（调 LLM 产出结构化审计报告）
├── orchestrator/
│   ├── state.py                     # 修改：加 draft_version/review_iterations/audit_report/polished
│   ├── nodes.py                     # 修改：加 audit/polish 节点，升级 summarize
│   ├── graph.py                     # 修改：改条件边回环（write→audit→polish 或 回环≤3）
│   └── runner.py                    # 修改：注入 auditor_client（独立 LLM 配置）
└── protocol/
    └── applier.py                   # 微调：summarize 节点用结构化摘要
tests/
├── test_audit_dimensions.py
├── test_audit_schemas.py
├── test_auditor.py
└── test_orchestrator_write_review.py  # 写审循环集成测试
```

---

## Task 1: 审计维度定义

**Files:**
- Create: `novel_agent/audit/__init__.py`, `novel_agent/audit/dimensions.py`
- Test: `tests/test_audit_dimensions.py`

- [ ] **Step 1: 写失败测试 tests/test_audit_dimensions.py**

```python
"""测试审计维度定义。"""
from novel_agent.audit.dimensions import DIMENSIONS, CRITICAL_DIMENSIONS, AuditCategory


def test_all_dimensions_present():
    """应含一致性/人物/情节/文风/物理/环境/关系 7 类。"""
    categories = {d.category for d in DIMENSIONS}
    assert AuditCategory.CONSISTENCY in categories
    assert AuditCategory.CHARACTER in categories
    assert AuditCategory.PLOT in categories
    assert AuditCategory.STYLE in categories
    assert AuditCategory.PHYSICAL in categories
    assert AuditCategory.ENVIRONMENT in categories
    assert AuditCategory.RELATIONSHIP in categories


def test_critical_dimensions_marked():
    """关键维度（设定一致/OOC/伏笔/信息边界/物理）任一不过直接打回。"""
    crit_names = {d.name for d in CRITICAL_DIMENSIONS}
    assert "设定一致性" in crit_names
    assert "人物OOC" in crit_names
    assert "伏笔准确性" in crit_names
    assert "信息边界" in crit_names
    assert "物理一致性" in crit_names


def test_dimension_has_name_category_check_desc():
    """每个维度有 name/category/check/description。"""
    for d in DIMENSIONS:
        assert d.name
        assert d.category
        assert d.check
```

- [ ] **Step 2: 运行验证失败**

```bash
.venv\Scripts\python.exe -m pytest tests/test_audit_dimensions.py -v
```
Expected: FAIL（模块不存在）

- [ ] **Step 3: 创建 novel_agent/audit/__init__.py**

```python
"""审计层：写审分离的审校维度 + Auditor agent。"""
```

- [ ] **Step 4: 创建 novel_agent/audit/dimensions.py**

```python
"""审计维度定义：融合 spec 15维 + knowrite Fitness 五维 + Acid Test 四维。

spec 第 5 节。关键维度任一不过 → 直接打回重写；次要维度通过率 ≥80% → 通过。
"""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class AuditCategory(str, Enum):
    CONSISTENCY = "一致性"
    CHARACTER = "人物"
    PLOT = "情节"
    STYLE = "文风"
    PHYSICAL = "物理"
    ENVIRONMENT = "环境"
    RELATIONSHIP = "关系"


@dataclass(frozen=True)
class Dimension:
    name: str
    category: AuditCategory
    check: str           # 检查内容描述
    description: str = ""
    critical: bool = False   # True=任一不过直接打回


# spec 15维 + Fitness + Acid Test 融合
DIMENSIONS: list[Dimension] = [
    # 一致性（spec 15维 + knowrite）
    Dimension("设定一致性", AuditCategory.CONSISTENCY, "对照圣经检查设定不崩", critical=True),
    Dimension("伏笔准确性", AuditCategory.CONSISTENCY, "伏笔生命周期验证（埋设/发展/回收）", critical=True),
    Dimension("时间线连贯", AuditCategory.CONSISTENCY, "时间跨度合理性"),
    Dimension("地理正确性", AuditCategory.CONSISTENCY, "地点移动逻辑"),
    Dimension("信息边界", AuditCategory.CONSISTENCY, "角色只说知道的信息（交互矩阵验证）", critical=True),
    Dimension("资源合理性", AuditCategory.CONSISTENCY, "物品消耗/获取/衰减逻辑"),
    # 人物（spec 15维 + Acid Test 心理维）
    Dimension("情感连续性", AuditCategory.CHARACTER, "情感弧线一致性"),
    Dimension("人物OOC", AuditCategory.CHARACTER, "MAR 法则对照，行为符合人设", critical=True),
    Dimension("对话真实性", AuditCategory.CHARACTER, "对话符合角色身份"),
    Dimension("视角一致性", AuditCategory.CHARACTER, "第三人称限制视角"),
    # 情节（spec 15维 + Fitness）
    Dimension("支线推进度", AuditCategory.PLOT, "支线进度板更新"),
    Dimension("节奏控制", AuditCategory.PLOT, "每 300-500 字一个转折"),
    Dimension("爽点分布", AuditCategory.PLOT, "高潮间隔合理性"),
    Dimension("读者期待管理", AuditCategory.PLOT, "章末钩子强度"),
    Dimension("大纲偏离度", AuditCategory.PLOT, "是否偏离本章大纲"),
    # 文风（spec 15维）
    Dimension("文风统一", AuditCategory.STYLE, "文风指纹一致性"),
    Dimension("AI标记词检测", AuditCategory.STYLE, "禁止句式/转折词限频"),
    # 物理（Acid Test 物理维）
    Dimension("物理一致性", AuditCategory.PHYSICAL, "身体/伤/年龄/生死（死后不能行动）", critical=True),
    # 环境（Acid Test 环境维）
    Dimension("环境一致性", AuditCategory.ENVIRONMENT, "符合地点时代+lore"),
    # 关系（Acid Test 化学维）
    Dimension("关系铺垫", AuditCategory.RELATIONSHIP, "关系变化有铺垫不突兀"),
]

CRITICAL_DIMENSIONS = [d for d in DIMENSIONS if d.critical]
```

- [ ] **Step 5: 运行测试**

```bash
.venv\Scripts\python.exe -m pytest tests/test_audit_dimensions.py -v
```
Expected: 3 PASS

- [ ] **Step 6: Commit**

```bash
git add . && git commit -m "feat(audit): 审计维度定义（15维+Fitness+Acid Test 融合）"
```

---

## Task 2: 审计报告 schema

**Files:**
- Create: `novel_agent/audit/schemas.py`
- Test: `tests/test_audit_schemas.py`

- [ ] **Step 1: 写失败测试 tests/test_audit_schemas.py**

```python
"""测试审计报告 schema。"""
import pytest
from pydantic import ValidationError

from novel_agent.audit.schemas import Issue, AuditReport


def test_issue_valid():
    i = Issue(dimension="设定一致性", severity="critical", message="主角能力前后矛盾")
    assert i.severity == "critical"


def test_issue_invalid_severity():
    with pytest.raises(ValidationError):
        Issue(dimension="x", severity="unknown", message="y")


def test_audit_report_passed():
    r = AuditReport(passed=True, overall_score=85, issues=[], summary="达标")
    assert r.passed is True
    assert r.overall_score == 85


def test_audit_report_with_issues():
    r = AuditReport(
        passed=False, overall_score=60,
        issues=[
            Issue(dimension="人物OOC", severity="critical", message="角色反应不符人设"),
            Issue(dimension="节奏控制", severity="minor", message="转折过密"),
        ],
        summary="关键问题：OOC",
    )
    assert len(r.issues) == 2
    assert any(i.severity == "critical" for i in r.issues)


def test_audit_report_requires_fields():
    with pytest.raises(ValidationError):
        AuditReport(passed=True)  # 缺 overall_score
```

- [ ] **Step 2: 运行验证失败**

```bash
.venv\Scripts\python.exe -m pytest tests/test_audit_schemas.py -v
```
Expected: FAIL

- [ ] **Step 3: 创建 novel_agent/audit/schemas.py**

```python
"""审计报告 schema：Auditor 产出的结构化报告。

spec 第 5.2 节：关键维度任一不过直接打回；次要维度通过率 ≥80% 通过。
Fitness 总分 = 字数/重复率/审阅通过率/读者分/大纲偏离 加权。
"""
from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field


class Issue(BaseModel):
    """单个审计问题。"""
    dimension: str
    severity: Literal["critical", "important", "minor"]
    message: str
    location: str = ""       # 段落/行号引用


class AuditReport(BaseModel):
    """章节审计报告。"""
    passed: bool             # 是否达标（关键维度全过 + 次要通过率≥80%）
    overall_score: int = Field(ge=0, le=100)   # Fitness 总分
    issues: list[Issue] = Field(default_factory=list)
    summary: str = ""        # 总评
    suggestions: list[str] = Field(default_factory=list)  # 给 Writer 的修订建议
```

- [ ] **Step 4: 运行测试**

```bash
.venv\Scripts\python.exe -m pytest tests/test_audit_schemas.py -v
```
Expected: 5 PASS

- [ ] **Step 5: Commit**

```bash
git add . && git commit -m "feat(audit): 审计报告 schema（Issue/AuditReport）"
```

---

## Task 3: Auditor agent

**Files:**
- Create: `novel_agent/audit/auditor.py`
- Test: `tests/test_auditor.py`

- [ ] **Step 1: 写失败测试 tests/test_auditor.py**

```python
"""测试 Auditor agent：独立审校，产出结构化审计报告。"""
import pytest
from unittest.mock import AsyncMock

from novel_agent.audit.auditor import Auditor
from novel_agent.audit.schemas import AuditReport
from novel_agent.bible.database import SessionLocal, set_config
from novel_agent.bible.models import Base, Project
from novel_agent.bible.repository import BibleRepository
from novel_agent.llm.client import LLMClient
from novel_agent.config import LLMConfig


@pytest.fixture
def repo(tmp_config):
    from novel_agent.bible import database as db_mod
    set_config(tmp_config)
    Base.metadata.create_all(bind=db_mod.engine)
    db = SessionLocal()
    p = Project(title="测试", genre="科幻")
    db.add(p); db.commit(); db.refresh(p)
    r = BibleRepository(db, project_id=p.id)
    r.create_character(name="刘洋", role="主角", personality="冷静")
    yield r
    db.close()


@pytest.mark.asyncio
async def test_auditor_returns_report(repo):
    """Auditor 应返回结构化 AuditReport（mock LLM 返回 JSON）。"""
    mock_llm = AsyncMock()
    mock_llm.generate = AsyncMock(return_value="""```json
{"passed": true, "overall_score": 85, "issues": [], "summary": "达标", "suggestions": []}
```""")
    auditor = Auditor(mock_llm)
    report = await auditor.audit(
        chapter=1, title="第一章", draft="正文内容……", repo=repo,
    )
    assert isinstance(report, AuditReport)
    assert report.passed is True
    assert report.overall_score == 85


@pytest.mark.asyncio
async def test_auditor_flags_failed(repo):
    """LLM 返回不达标时，report.passed 为 False。"""
    mock_llm = AsyncMock()
    mock_llm.generate = AsyncMock(return_value="""```json
{"passed": false, "overall_score": 55, "issues": [{"dimension":"人物OOC","severity":"critical","message":"反应不符"}], "summary": "OOC", "suggestions": ["重写对话"]}
```""")
    auditor = Auditor(mock_llm)
    report = await auditor.audit(
        chapter=1, title="第一章", draft="正文", repo=repo,
    )
    assert report.passed is False
    assert len(report.issues) == 1
    assert report.issues[0].severity == "critical"


@pytest.mark.asyncio
async def test_auditor_handles_malformed_json(repo):
    """LLM 返回非 JSON 时，Auditor 应返回 failed 报告而非崩溃。"""
    mock_llm = AsyncMock()
    mock_llm.generate = AsyncMock(return_value="这不是 JSON")
    auditor = Auditor(mock_llm)
    report = await auditor.audit(
        chapter=1, title="第一章", draft="正文", repo=repo,
    )
    assert report.passed is False
    assert report.overall_score == 0
    assert "解析" in report.summary or "失败" in report.summary
```

- [ ] **Step 2: 运行验证失败**

```bash
set NOVEL_TEST_DB=memory && .venv\Scripts\python.exe -m pytest tests/test_auditor.py -v
```
Expected: FAIL

- [ ] **Step 3: 创建 novel_agent/audit/auditor.py**

```python
"""Auditor agent：独立审校，产出结构化审计报告。

写审分离铁律（spec 第 0.3 节）：Auditor 与 Writer 是独立 LLM 调用，
Auditor 只看成稿 + 圣经，不知生成过程，防自我背书。
"""
from __future__ import annotations

import json
import re

from novel_agent.audit.dimensions import DIMENSIONS, CRITICAL_DIMENSIONS
from novel_agent.audit.schemas import AuditReport, Issue
from novel_agent.bible.repository import BibleRepository
from novel_agent.llm.client import LLMClient

AUDITOR_SYSTEM_PROMPT = (
    "你是一位严苛的网文审校编辑。独立审阅章节草稿，对照圣经设定检查一致性。"
    "只看成稿和设定，不知生成过程。按维度产出结构化 JSON 审计报告。"
)


def _build_dimensions_text() -> str:
    """把审计维度格式化为 prompt 文本。"""
    lines = []
    for d in DIMENSIONS:
        tag = "【关键】" if d.critical else ""
        lines.append(f"- {tag}{d.name}（{d.category.value}）：{d.check}")
    return "\n".join(lines)


def _extract_json(text: str) -> dict | None:
    """从 LLM 输出中提取 JSON（容忍 markdown 代码块包裹）。"""
    # 先尝试提取 ```json ... ``` 块
    m = re.search(r"```(?:json)?\s*\n?(.*?)\n?```", text, re.DOTALL)
    candidate = m.group(1) if m else text
    try:
        return json.loads(candidate)
    except json.JSONDecodeError:
        # 尝试找第一个 { 到最后一个 }
        start = candidate.find("{")
        end = candidate.rfind("}")
        if start >= 0 and end > start:
            try:
                return json.loads(candidate[start:end + 1])
            except json.JSONDecodeError:
                return None
        return None


class Auditor:
    """独立审校 agent。"""

    def __init__(self, llm_client: LLMClient):
        self.llm_client = llm_client

    async def audit(self, chapter: int, title: str, draft: str,
                    repo: BibleRepository) -> AuditReport:
        """审阅章节草稿，返回结构化审计报告。"""
        # 装配审校上下文：角色状态 + 伏笔 + 审计维度
        chars = repo.list_characters()
        char_text = "\n".join(
            f"- {c.name}（{c.role}）：{c.personality}，位置={c.current_location}"
            for c in chars
        ) or "无角色记录"
        to_plant = repo.get_foreshadows_to_plant(chapter)
        to_resolve = repo.get_foreshadows_to_resolve(chapter)
        foreshadow_text = ""
        if to_plant:
            foreshadow_text += "应埋：" + "；".join(f"{f.foreshadow_id}:{f.description}" for f in to_plant)
        if to_resolve:
            foreshadow_text += "应回收：" + "；".join(f"{f.foreshadow_id}:{f.description}" for f in to_resolve)

        prompt = (
            f"审阅第{chapter}章《{title}》草稿。\n\n"
            f"【角色状态】\n{char_text}\n\n"
            f"【伏笔要求】\n{foreshadow_text or '无'}\n\n"
            f"【审计维度】\n{_build_dimensions_text()}\n\n"
            f"【草稿正文】\n{draft}\n\n"
            f"要求：按上述维度审阅，输出 JSON：\n"
            f'{{"passed": bool, "overall_score": 0-100, '
            f'"issues": [{{"dimension":"","severity":"critical|important|minor",'
            f'"message":"","location":""}}], "summary": "", "suggestions": []}}\n'
            f"关键维度任一不过则 passed=false。只输出 JSON。"
        )
        try:
            raw = await self.llm_client.generate(prompt, system=AUDITOR_SYSTEM_PROMPT)
        except Exception as e:
            return AuditReport(passed=False, overall_score=0,
                               summary=f"LLM 调用失败: {e}")

        data = _extract_json(raw)
        if data is None:
            return AuditReport(passed=False, overall_score=0,
                               summary="审计报告解析失败：LLM 未返回有效 JSON")
        try:
            return AuditReport(**data)
        except Exception as e:
            return AuditReport(passed=False, overall_score=0,
                               summary=f"审计报告字段校验失败: {e}")
```

- [ ] **Step 4: 运行测试**

```bash
set NOVEL_TEST_DB=memory && .venv\Scripts\python.exe -m pytest tests/test_auditor.py -v
```
Expected: 3 PASS

- [ ] **Step 5: Commit**

```bash
git add . && git commit -m "feat(audit): Auditor agent（独立审校 + JSON 解析容错）"
```

---

## Task 4: 扩展编排状态 + 升级 summarize 节点

**Files:**
- Modify: `novel_agent/orchestrator/state.py`, `novel_agent/orchestrator/nodes.py`
- Test: `tests/test_orchestrator_nodes.py`（追加）

- [ ] **Step 1: 扩展 state.py 加字段**

修改 `novel_agent/orchestrator/state.py`，ChapterGenState 加：

```python
    draft_version: int          # 当前草稿版本（写审循环计数）
    review_iterations: int      # 已审阅次数（≤3）
    audit_report: dict          # 最近一次审计报告（序列化）
    polished: str               # 润色后正文
```

完整新版 state.py：

```python
"""流水线状态 schema（LangGraph StateGraph 用 TypedDict）。

状态在节点间传递，每个节点读取所需字段、写回产出字段。
M3 扩展：写审循环相关字段。
"""
from __future__ import annotations

from typing import TypedDict


class ChapterGenState(TypedDict, total=False):
    """单章生成的流水线状态。"""
    project_id: int
    chapter: int
    title: str
    context: str               # 装配的上下文
    draft: str                 # Writer 产出的正文草稿
    draft_version: int         # 当前草稿版本（写审循环计数）
    review_iterations: int     # 已审阅次数（≤3）
    audit_report: dict         # 最近一次审计报告（序列化）
    polished: str              # 润色后正文
    status: str                # pending/assembled/drafted/audited/polished/saved/completed/failed
    error: str
    word_count: int
```

- [ ] **Step 2: 给 nodes.py 加 audit/polish 节点 + 升级 summarize**

在 `novel_agent/orchestrator/nodes.py` 追加：

```python
from novel_agent.audit.auditor import Auditor
from novel_agent.audit.schemas import AuditReport


async def audit_chapter(state: ChapterGenState, auditor: Auditor,
                        repo: BibleRepository) -> dict:
    """节点：独立审校草稿，返回审计报告。"""
    report = await auditor.audit(
        chapter=state["chapter"], title=state.get("title", ""),
        draft=state["draft"], repo=repo,
    )
    iterations = state.get("review_iterations", 0) + 1
    return {
        "audit_report": report.model_dump(),
        "review_iterations": iterations,
        "status": "audited" if report.passed else "needs_rewrite",
    }


def route_after_audit(state: ChapterGenState) -> str:
    """条件边：审计达标→polish；不达标且未超3次→write 回环；超3次→failed。"""
    report = AuditReport(**state.get("audit_report", {}))
    if report.passed:
        return "polish"
    if state.get("review_iterations", 0) >= 3:
        return "end_failed"
    return "rewrite"


async def rewrite_chapter(state: ChapterGenState, llm_client: LLMClient) -> dict:
    """节点：基于审计建议重写（第2轮起注入历史审阅痕迹）。"""
    report = AuditReport(**state.get("audit_report", {}))
    suggestions = "\n".join(f"- {s}" for s in report.suggestions) or "无具体建议"
    issues = "\n".join(f"- {i.dimension}({i.severity}): {i.message}" for i in report.issues) or "无"
    prompt = (
        f"重写第{state['chapter']}章《{state.get('title', '')}》。\n\n"
        f"【上下文】\n{state.get('context', '')}\n\n"
        f"【上一版草稿】\n{state.get('draft', '')}\n\n"
        f"【审计问题】\n{issues}\n\n"
        f"【修订建议】\n{suggestions}\n\n"
        f"要求：针对问题重写，只输出正文。"
    )
    try:
        draft = await llm_client.generate(prompt, system=WRITER_SYSTEM_PROMPT)
        return {"draft": draft, "draft_version": state.get("draft_version", 1) + 1,
                "word_count": len(draft), "status": "drafted"}
    except Exception as e:
        return {"status": "failed", "error": str(e)}


async def polish_chapter(state: ChapterGenState, llm_client: LLMClient) -> dict:
    """节点：润色优化（文风统一 + AI 痕迹清除）。"""
    POLISH_SYSTEM = (
        "你是网文润色编辑。优化语言表达，清除 AI 痕迹词（忽然/竟然/不禁等限频），"
        "保持原意和情节，增强画面感。只输出润色后正文。"
    )
    prompt = f"润色以下章节正文：\n\n{state.get('draft', '')}"
    try:
        polished = await llm_client.generate(prompt, system=POLISH_SYSTEM)
        return {"polished": polished, "status": "polished",
                "word_count": len(polished)}
    except Exception as e:
        # 润色失败不影响主流程，用原草稿
        return {"polished": state.get("draft", ""), "status": "polished",
                "error": f"润色失败用原稿: {e}"}


def save_text_polished(state: ChapterGenState, recall: RecallMemory) -> dict:
    """节点：保存润色后正文到文件。"""
    content = state.get("polished") or state.get("draft", "")
    recall.save_chapter_text(
        chapter=state["chapter"], title=state.get("title", ""),
        content=content,
    )
    return {"status": "saved"}


async def summarize_chapter(state: ChapterGenState, llm_client: LLMClient,
                            applier: DeltaApplier) -> dict:
    """节点：调 LLM 抽取结构化摘要并存入圣经（升级 M2 的简化版）。"""
    content = state.get("polished") or state.get("draft", "")
    prompt = (
        f"为以下章节抽取摘要，输出 JSON：\n"
        f'{{"core_events":"","characters_present":"","emotion_changes":"",'
        f'"foreshadow_dynamics":"","chapter_hook":""}}\n\n{content}\n\n只输出 JSON。'
    )
    SUM_SYSTEM = "你是网文摘要助手。精炼抽取章节核心信息。只输出 JSON。"
    import json, re
    try:
        raw = await llm_client.generate(prompt, system=SUM_SYSTEM)
        m = re.search(r"\{.*\}", raw, re.DOTALL)
        data = json.loads(m.group(0)) if m else {}
    except Exception:
        data = {}

    delta = Delta(
        target="chapter_summary", action="create", chapter=state["chapter"],
        data=SummaryDelta(
            title=state.get("title", ""),
            word_count=state.get("word_count", len(content)),
            core_events=data.get("core_events", content[:200]),
            characters_present=data.get("characters_present", ""),
            emotion_changes=data.get("emotion_changes", ""),
            foreshadow_dynamics=data.get("foreshadow_dynamics", ""),
            subplot_progress=data.get("subplot_progress", ""),
            chapter_hook=data.get("chapter_hook", ""),
        ),
    )
    result = applier.apply(delta)
    if not result.success:
        return {"status": "failed", "error": result.message}
    return {"status": "completed"}
```

- [ ] **Step 3: 追加节点测试到 tests/test_orchestrator_nodes.py**

```python
@pytest.mark.asyncio
async def test_audit_node(repo):
    from novel_agent.orchestrator.nodes import audit_chapter
    from novel_agent.audit.auditor import Auditor
    from unittest.mock import AsyncMock
    mock_auditor = AsyncMock()
    mock_auditor.audit = AsyncMock(return_value=__import__(
        "novel_agent.audit.schemas", fromlist=["AuditReport"]).AuditReport(
        passed=True, overall_score=85, summary="达标"))
    state = ChapterGenState(
        project_id=repo.project_id, chapter=1, title="第一章",
        draft="正文", draft_version=1, review_iterations=0,
    )
    result = await audit_chapter(state, auditor=mock_auditor, repo=repo)
    assert result["status"] == "audited"
    assert result["review_iterations"] == 1


@pytest.mark.asyncio
async def test_polish_node():
    from novel_agent.orchestrator.nodes import polish_chapter
    from unittest.mock import AsyncMock, MagicMock
    mock_client = MagicMock()
    mock_client.generate = AsyncMock(return_value="润色后正文")
    state = ChapterGenState(chapter=1, title="x", draft="原稿", status="audited")
    result = await polish_chapter(state, llm_client=mock_client)
    assert result["polished"] == "润色后正文"
    assert result["status"] == "polished"


def test_route_after_audit_pass():
    from novel_agent.orchestrator.nodes import route_after_audit
    state = ChapterGenState(
        audit_report={"passed": True, "overall_score": 85, "issues": []},
        review_iterations=1,
    )
    assert route_after_audit(state) == "polish"


def test_route_after_audit_fail_under_limit():
    from novel_agent.orchestrator.nodes import route_after_audit
    state = ChapterGenState(
        audit_report={"passed": False, "overall_score": 50, "issues": []},
        review_iterations=1,
    )
    assert route_after_audit(state) == "rewrite"


def test_route_after_audit_fail_over_limit():
    from novel_agent.orchestrator.nodes import route_after_audit
    state = ChapterGenState(
        audit_report={"passed": False, "overall_score": 50, "issues": []},
        review_iterations=3,
    )
    assert route_after_audit(state) == "end_failed"
```

- [ ] **Step 4: 运行测试**

```bash
set NOVEL_TEST_DB=memory && .venv\Scripts\python.exe -m pytest tests/test_orchestrator_nodes.py -v
```
Expected: 原 4 + 新 5 = 9 PASS

- [ ] **Step 5: Commit**

```bash
git add . && git commit -m "feat(orchestrator): audit/polish/rewrite/summarize 节点 + 路由"
```

---

## Task 5: 写审循环 StateGraph

**Files:**
- Modify: `novel_agent/orchestrator/graph.py`
- Test: `tests/test_orchestrator_graph.py`（追加）

- [ ] **Step 1: 重写 graph.py 为写审回环结构**

```python
"""StateGraph 定义：assemble→write→audit→{达标:polish→save→summarize | 不达标≤3:rewrite→audit | 超3:END}

写审分离铁律：Writer 与 Auditor 独立；反馈循环 ≤3 次。
"""
from __future__ import annotations

from functools import partial
from typing import Any

from langgraph.graph import StateGraph, START, END

from novel_agent.orchestrator.nodes import (
    assemble_context, write_chapter, audit_chapter, rewrite_chapter,
    polish_chapter, save_text_polished, summarize_chapter, route_after_audit,
)
from novel_agent.orchestrator.state import ChapterGenState

NODE_NAMES = ["assemble", "write", "audit", "rewrite", "polish", "save_text", "summarize"]


def build_graph(deps: dict[str, Any] | None = None):
    """构建写审循环流水线图。"""
    deps = deps or {}
    graph = StateGraph(ChapterGenState)

    assemble_fn = partial(assemble_context, repo=deps["repo"], archival=deps.get("archival"))
    write_fn = partial(write_chapter, llm_client=deps["llm_client"])
    audit_fn = partial(audit_chapter, auditor=deps["auditor"], repo=deps["repo"])
    rewrite_fn = partial(rewrite_chapter, llm_client=deps["llm_client"])
    polish_fn = partial(polish_chapter, llm_client=deps["llm_client"])
    save_fn = partial(save_text_polished, recall=deps["recall"])
    summarize_fn = partial(summarize_chapter, llm_client=deps["llm_client"], applier=deps["applier"])

    graph.add_node("assemble", assemble_fn)
    graph.add_node("write", write_fn)
    graph.add_node("audit", audit_fn)
    graph.add_node("rewrite", rewrite_fn)
    graph.add_node("polish", polish_fn)
    graph.add_node("save_text", save_fn)
    graph.add_node("summarize", summarize_fn)

    graph.add_edge(START, "assemble")
    graph.add_edge("assemble", "write")
    graph.add_edge("write", "audit")
    # 审计后条件路由
    graph.add_conditional_edges(
        "audit", route_after_audit,
        {"polish": "polish", "rewrite": "rewrite", "end_failed": END},
    )
    graph.add_edge("rewrite", "audit")     # 重写后回审计
    graph.add_edge("polish", "save_text")
    graph.add_edge("save_text", "summarize")
    graph.add_edge("summarize", END)

    return graph.compile()
```

- [ ] **Step 2: 更新 tests/test_orchestrator_graph.py**

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
        "auditor": MagicMock(),
    }


def test_graph_has_seven_nodes():
    graph = build_graph(_mock_deps())
    node_ids = set(graph.nodes.keys())
    for name in NODE_NAMES:
        assert name in node_ids, f"缺失节点 {name}"


def test_node_names_complete():
    assert NODE_NAMES == ["assemble", "write", "audit", "rewrite", "polish", "save_text", "summarize"]
```

- [ ] **Step 3: 运行测试**

```bash
.venv\Scripts\python.exe -m pytest tests/test_orchestrator_graph.py -v
```
Expected: 2 PASS

- [ ] **Step 4: Commit**

```bash
git add . && git commit -m "feat(orchestrator): 写审循环 StateGraph（条件边回环≤3）"
```

---

## Task 6: Runner 注入 Auditor + 端到端写审测试

**Files:**
- Modify: `novel_agent/orchestrator/runner.py`
- Test: `tests/test_orchestrator_write_review.py`（新建集成测试）

- [ ] **Step 1: 修改 runner.py 注入 auditor**

在 `ChapterRunner.__init__` 加 auditor。Auditor 用独立 LLMClient（写审分离：可配不同模型/温度）。

修改 `novel_agent/orchestrator/runner.py`：

```python
from novel_agent.audit.auditor import Auditor

class ChapterRunner:
    def __init__(self, config: Config, repo: BibleRepository,
                 llm_client: LLMClient | None = None,
                 auditor: Auditor | None = None):
        # ... 原有初始化 ...
        self.llm_client = llm_client or LLMClient(config.llm)
        # Auditor 用独立 client（写审分离；M3 默认复用同 client，M4 可配不同模型）
        auditor_client = LLMClient(config.llm)
        self.auditor = auditor or Auditor(auditor_client)
        # graph deps 加 auditor
        self.graph = build_graph({
            "repo": self.repo, "llm_client": self.llm_client,
            "recall": self.recall, "applier": self.applier,
            "archival": self.archival, "auditor": self.auditor,
        }).with_config({"checkpointer": self.checkpointer})
```

- [ ] **Step 2: 写集成测试 tests/test_orchestrator_write_review.py**

```python
"""写审循环端到端集成测试。"""
import pytest
from unittest.mock import AsyncMock, MagicMock

from novel_agent.audit.auditor import Auditor
from novel_agent.audit.schemas import AuditReport, Issue
from novel_agent.bible.database import SessionLocal, set_config
from novel_agent.bible.models import Base, Project
from novel_agent.bible.repository import BibleRepository
from novel_agent.orchestrator.runner import ChapterRunner


@pytest.fixture
def make_runner(tmp_config):
    from novel_agent.bible import database as db_mod
    set_config(tmp_config)
    Base.metadata.create_all(bind=db_mod.engine)
    db = SessionLocal()
    p = Project(title="测试", genre="科幻", summary="末日")
    db.add(p); db.commit(); db.refresh(p)
    r = BibleRepository(db, project_id=p.id)
    r.create_character(name="刘洋", role="主角")
    runners = []

    def _make(llm_client=None, auditor=None):
        runner = ChapterRunner(tmp_config, repo=r, llm_client=llm_client, auditor=auditor)
        runners.append(runner)
        return runner

    yield _make
    for rn in runners:
        rn.close()
    db.close()


@pytest.mark.asyncio
async def test_write_review_pass_on_first_audit(make_runner):
    """审计一次达标 → polish → save → summarize 全流程。"""
    mock_llm = MagicMock()
    # write/polish/summarize 各调一次 generate，用 side_effect 区分
    mock_llm.generate = AsyncMock(side_effect=[
        "草稿正文",           # write
        "润色后正文",         # polish
        '{"core_events":"事件","characters_present":"刘洋"}',  # summarize
    ])
    mock_auditor = MagicMock()
    mock_auditor.audit = AsyncMock(return_value=AuditReport(
        passed=True, overall_score=85, summary="达标"))
    runner = make_runner(llm_client=mock_llm, auditor=mock_auditor)

    result = await runner.run(chapter=1, title="第一章")

    assert result["status"] == "completed"
    assert result["review_iterations"] == 1
    assert "润色后正文" in runner.recall.read_chapter_text(1)
    assert runner.repo.get_chapter_summary(1) is not None


@pytest.mark.asyncio
async def test_write_review_rewrite_once_then_pass(make_runner):
    """审计不达标 → 重写 → 再审达标。"""
    mock_llm = MagicMock()
    mock_llm.generate = AsyncMock(side_effect=[
        "初版草稿",           # write v1
        "重写草稿",           # rewrite v2
        "润色后",             # polish
        '{"core_events":"事件"}',  # summarize
    ])
    mock_auditor = MagicMock()
    mock_auditor.audit = AsyncMock(side_effect=[
        AuditReport(passed=False, overall_score=50, issues=[
            Issue(dimension="人物OOC", severity="critical", message="不符")],
            suggestions=["重写对话"]),  # 第一次审：不达标
        AuditReport(passed=True, overall_score=85, summary="达标"),  # 第二次：达标
    ])
    runner = make_runner(llm_client=mock_llm, auditor=mock_auditor)

    result = await runner.run(chapter=1, title="第一章")

    assert result["status"] == "completed"
    assert result["review_iterations"] == 2
    assert result["draft_version"] == 2


@pytest.mark.asyncio
async def test_write_review_fail_after_three(make_runner):
    """连续 3 次审计不达标 → 失败结束（不进 polish）。"""
    mock_llm = MagicMock()
    mock_llm.generate = AsyncMock(side_effect=[
        "草稿v1", "草稿v2", "草稿v3",  # write + 2 次 rewrite
    ])
    mock_auditor = MagicMock()
    fail_report = AuditReport(passed=False, overall_score=40, summary="始终不达标")
    mock_auditor.audit = AsyncMock(return_value=fail_report)
    runner = make_runner(llm_client=mock_llm, auditor=mock_auditor)

    result = await runner.run(chapter=1, title="第一章")

    assert result["review_iterations"] == 3
    # 超过 3 次进 end_failed，status 应非 completed
    assert result["status"] != "completed"
```

- [ ] **Step 3: 运行测试**

```bash
set NOVEL_TEST_DB=memory && .venv\Scripts\python.exe -m pytest tests/test_orchestrator_write_review.py -v
```
Expected: 3 PASS

- [ ] **Step 4: 跑全套确认无回归**

```bash
set NOVEL_TEST_DB=memory && .venv\Scripts\python.exe -m pytest -v
```
Expected: M1+M2 的 57 + M3 新增 ≈ 70+ PASS

- [ ] **Step 5: Commit**

```bash
git add . && git commit -m "feat(orchestrator): runner 注入 auditor + 写审循环端到端"
```

---

## M3 验收清单

- [ ] 审计维度定义（15维+Fitness+Acid Test 融合，关键维度标注）
- [ ] 审计报告 schema（Issue/AuditReport）
- [ ] Auditor agent（独立审校 + JSON 解析容错）
- [ ] 状态扩展（draft_version/review_iterations/audit_report/polished）
- [ ] audit/polish/rewrite/summarize 节点 + route_after_audit 路由
- [ ] 写审循环 StateGraph（条件边回环 ≤3）
- [ ] Runner 注入 Auditor（写审分离）
- [ ] 端到端：一次达标 / 重写后达标 / 3次失败 三场景
- [ ] 全套测试 PASS（M1+M2 57 + M3 新增）

## 后续里程碑

- **M3b**：卷级规划层（Planner/Architect/Outliner + 人审①大纲）
- **M4**：interrupt 人审节点 + FastAPI + SSE + 前端四界面
