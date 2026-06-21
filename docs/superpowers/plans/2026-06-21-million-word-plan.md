# 百万字网文生成系统 · 落地方案

> 基于4轮多agent对抗讨论收敛。工程师可直接按此执行。
> 当前基线：132测试通过，5章生成质量已验证。

## 背景

当前系统能生成单卷5章且质量不错，但无法支撑百万字。四轮多agent讨论（网文作者/架构师/质疑者/认知科学家/产品经理）收敛出以下根因和方案。

**百万字的三个致命瓶颈**：
1. **回写闭环断裂**——`summarize_chapter`只写摘要+伏笔+角色位置，不写StateChange/TruthEvent/EntityAppearance/EmotionArc/CharacterMatrix/SubplotBoard，不索引archival正文。第50章后事件流/状态变更接近空。
2. **上下文膨胀**——无状态快照，core memory全量查角色+1000章摘要拉取。第150章后对全书90%中段失忆。
3. **无爽点供应链**——audit只有"高潮间隔合理性"空话，无档位规划/断层检测/欠账累积。百万字=百万字流水账。

## 设计原则

1. **不建"中枢"概念**——用具体的表/函数/节点，不起拟人名字
2. **确定性检查>LLM判断**——能SQL算的硬编码，不交给LLM
3. **软信号vs硬门禁**——LLM判断的=软信号+人审兜底；确定性可验证的=硬门禁
4. **快照>向量检索**——写作热路径用状态快照O(1)读当前态，不用向量检索历史
5. **渐进改造不推翻**——4阶段每阶段独立可验证，不破坏现有可用基线

---

## 阶段1：补回写闭环（地基，不修全是空中楼阁）

**目标**：`summarize_chapter`向6张表回写动态状态，全部走applier不直写repo。
**工作量**：5文件改造，约250行

### 1.1 新增Delta schema

**文件**：`novel_agent/protocol/schemas.py`

新增4个pydantic模型：
```python
class EmotionArcDelta(BaseModel):
    character_name: str
    chapter: int = 0
    event: str = ""
    emotion_before: str = ""
    emotion_after: str = ""
    growth: str = ""

class SubplotDelta(BaseModel):
    name: str
    status: str = "active"  # active/paused/resolved
    progress: int = 0
    next_goal: str = ""

class MatrixDelta(BaseModel):
    chapter: int = 0
    character_a: str
    character_b: str = ""
    interaction_type: str = ""  # meeting/conflict/cooperation/info_share
    info_exchanged: str = ""

class StateChangeDelta(BaseModel):
    entity_type: str  # character/faction/foreshadow
    entity_id: str
    field: str
    old_value: str = ""
    new_value: str = ""
```

`Delta.target` Literal追加：`"emotion_arc"`, `"subplot"`, `"character_matrix"`, `"state_change"`

### 1.2 applier注册新handler

**文件**：`novel_agent/protocol/applier.py`

在handler字典（约41行）追加：
```python
("emotion_arc", "create"): self._record_emotion_arc,
("subplot", "update"): self._update_subplot,
("character_matrix", "create"): self._record_matrix,
("state_change", "create"): self._state_change,
```

每个handler内部调`repo.append_event`写TruthEvent（与现有`_plant_foreshadow`一致风格）。

### 1.3 repository补写入方法

**文件**：`novel_agent/bible/repository.py`

新增（仿现有`create_state_change`约611行）：
- `create_emotion_arc(**kwargs) -> EmotionArc`
- `create_or_update_subplot(name, **kwargs) -> SubplotBoard`
- `create_character_matrix(**kwargs) -> CharacterMatrix`

### 1.4 summarize_chapter全量回写

**文件**：`novel_agent/orchestrator/nodes.py`（核心改动，约186-266行）

**改prompt**（约205-211行）：JSON schema追加字段：
```
"emotion_arcs":[{"name":"","event":"","emotion_before":"","emotion_after":"","growth":""}],
"subplot_updates":[{"name":"","status":"","progress":0,"next_goal":""}],
"character_interactions":[{"character_a":"","character_b":"","interaction_type":"","info_exchanged":""}],
"known_info_updates":[{"name":"","new_known_info":""}]
```

**改角色更新**（约252-264行）：
- **删除第264行** `repo.update_character(name, **updates)` 直写
- 改为走applier：
```python
for cs in data.get("character_states", []) or []:
    name = cs.get("name", "").strip()
    if name and repo:
        char = repo.get_character(name)
        if char:
            if cs.get("location") and cs["location"] != char.current_location:
                applier.apply(Delta(
                    target="state_change", action="create", chapter=chapter,
                    data=StateChangeDelta(entity_type="character", entity_id=name,
                        field="current_location", old_value=char.current_location,
                        new_value=cs["location"])))
                applier.apply(Delta(
                    target="character", action="state_change", chapter=chapter,
                    data=CharacterDelta(name=name, current_location=cs["location"])))
            # 同理处理 emotion 和 known_info
```

**追加新表回写**（266行return前）：
```python
# 回写EmotionArc
for ea in data.get("emotion_arcs", []) or []:
    try:
        applier.apply(Delta(target="emotion_arc", action="create", chapter=chapter,
            data=EmotionArcDelta(**{k: ea.get(k, "") for k in
                ("character_name", "event", "emotion_before", "emotion_after", "growth")})))
    except Exception: pass

# 回写SubplotBoard
for sp in data.get("subplot_updates", []) or []:
    try:
        applier.apply(Delta(target="subplot", action="update", chapter=chapter,
            data=SubplotDelta(name=sp.get("name",""), status=sp.get("status","active"),
                progress=sp.get("progress",0), next_goal=sp.get("next_goal",""))))
    except Exception: pass

# 回写CharacterMatrix
for ci in data.get("character_interactions", []) or []:
    try:
        applier.apply(Delta(target="character_matrix", action="create", chapter=chapter,
            data=MatrixDelta(character_a=ci.get("character_a",""),
                character_b=ci.get("character_b",""),
                interaction_type=ci.get("interaction_type",""),
                info_exchanged=ci.get("info_exchanged",""))))
    except Exception: pass
```

### 1.5 commit_chapter合流applier

**文件**：`novel_agent/api/routes_generation.py`（约851-984行）

`commit_chapter`内的`repo.create_state_change`/`repo.append_event`/`repo.update_foreshadow_status`直写，改为`applier.apply(...)`，与summarize同源。删除独立的`archival.index_chapter`（applier已索引）。

### 验证标准
```bash
# 跑1章生成后检查6张表有数据
python -c "
from novel_agent.bible.database import SessionLocal, set_config
from novel_agent.config import load_config
from novel_agent.bible.models import Base
set_config(load_config())
from novel_agent.bible import database as db_mod
Base.metadata.create_all(bind=db_mod.engine)
db = SessionLocal()
from sqlalchemy import text
for t in ['truth_events','state_changes','emotion_arcs','character_matrix','subplot_board']:
    print(f'{t}:', db.execute(text(f'SELECT COUNT(*) FROM {t}')).scalar())
db.close()
"
# 预期：6张表COUNT > 0（至少有1章的数据）
```

---

## 阶段2：状态快照（百万字不爆上下文）

**目标**：用"当前状态投影"替代全量查询。每章commit时物化一份世界状态快照。
**工作量**：1文件新增 + 3文件改造，约300行

### 2.1 新增StateSnapshot表

**文件**：`novel_agent/bible/models.py`

```python
class StateSnapshot(Base):
    """世界状态快照：每章物化一份，O(1)读当前态。"""
    __tablename__ = "state_snapshots"
    id = Column(Integer, primary_key=True, index=True)
    project_id = Column(Integer, ForeignKey("projects.id"), nullable=False, index=True)
    chapter = Column(Integer, nullable=False, index=True)
    snapshot_json = Column(JSON, default=dict)
    created_at = Column(DateTime, default=datetime.utcnow)
```

`migrate_db`（约349行）会自动建表。

### 2.2 新增快照构建模块

**文件**：`novel_agent/memory/snapshot.py`（新增）

```python
"""世界状态快照：从现有库投影当前态，替代全量查询。"""
from novel_agent.bible.repository import BibleRepository

def build_snapshot(repo: BibleRepository, chapter: int) -> dict:
    """构建第chapter章的世界状态快照。"""
    # 活跃角色（最近3章出场 + 主角/反派）
    active = repo.get_active_entities_for_chapter(chapter) if hasattr(repo, "get_active_entities_for_chapter") else []
    chars = []
    for c in repo.list_characters():
        if c.role in ("主角", "反派") or (hasattr(c, "last_active_chapter") and c.last_active_chapter and c.last_active_chapter >= chapter - 3):
            chars.append({
                "name": c.name, "role": c.role,
                "location": c.current_location, "emotion": c.current_emotion,
                "known_info": (c.known_info or "")[:80],
            })
    # 活跃伏笔（planted + developing）
    foreshadows = []
    for f in repo.get_foreshadows_by_status("planted") + repo.get_foreshadows_by_status("developing"):
        foreshadows.append({"id": f.foreshadow_id, "desc": (f.description or "")[:50],
                           "plant_ch": f.plant_chapter, "resolve_ch": f.planned_resolve_chapter})
    # 活跃支线
    subplots = []
    # 活跃势力
    return {
        "chapter": chapter,
        "characters": chars[:15],  # 最多15个活跃角色
        "foreshadows": foreshadows[:20],  # 最多20个活跃伏笔
        "subplots": subplots,
    }

def render_snapshot(snap: dict) -> str:
    """渲染快照为core memory文本段。"""
    lines = [f"【世界状态快照·第{snap['chapter']}章】"]
    lines.append("角色：" + "；".join(
        f"{c['name']}({c['role']})@{c['location']}[{c['emotion']}]" for c in snap.get("characters", [])))
    lines.append("活跃伏笔：" + "；".join(
        f"{f['id']}:{f['desc']}" for f in snap.get("foreshadows", [])) or "无")
    return "\n".join(lines)
```

### 2.3 repository加快照读写

**文件**：`novel_agent/bible/repository.py`

```python
def save_state_snapshot(self, chapter: int, payload: dict) -> None:
    """保存世界状态快照（覆盖同章）。"""
    from novel_agent.bible.models import StateSnapshot
    existing = self.db.query(StateSnapshot).filter(
        StateSnapshot.project_id == self.project_id,
        StateSnapshot.chapter == chapter,
    ).first()
    if existing:
        existing.snapshot_json = payload
    else:
        self.db.add(StateSnapshot(project_id=self.project_id, chapter=chapter, snapshot_json=payload))
    self._commit_or_flush()

def get_latest_state_snapshot(self, before_chapter: int) -> dict | None:
    """取最近一次快照。"""
    from novel_agent.bible.models import StateSnapshot
    s = self.db.query(StateSnapshot).filter(
        StateSnapshot.project_id == self.project_id,
        StateSnapshot.chapter < before_chapter,
    ).order_by(StateSnapshot.chapter.desc()).first()
    return s.snapshot_json if s else None
```

### 2.4 CoreMemoryAssembler优先读快照

**文件**：`novel_agent/memory/core.py`（约28行assemble开头）

```python
def assemble(self, chapter: int, ...):
    # 优先读快照
    snap = self.repo.get_latest_state_snapshot(chapter)
    if snap:
        from novel_agent.memory.snapshot import render_snapshot
        sections.append(render_snapshot(snap))
        # 不再全量查角色
        chars = []  # 快照已有
    else:
        chars = self._filter_characters_for_chapter(chapter, self.repo.list_characters())
    # 前文摘要：跨卷时只注入卷摘要+最近5章，不再limit=1000
    recent = self.repo.list_chapter_summaries(limit=5)  # 改为5，不是10
```

### 2.5 summarize末尾存快照

**文件**：`novel_agent/orchestrator/nodes.py`（266行return前）

```python
# 存世界状态快照
from novel_agent.memory.snapshot import build_snapshot
if repo:
    repo.save_state_snapshot(chapter, build_snapshot(repo, chapter))
```

### 验证标准
```bash
# 连续生成10章后检查：
# 1. state_snapshots每章1条
# 2. core memory字符数从第5章起稳定（不随章数线性增长）
```

---

## 阶段3：爽点供应链 + 欠账账本（从流水账变成网文）

**目标**：加"爽点天花板"——档位规划+断层检测+欠账累积+卷高潮强制还。
**工作量**：2表新增 + 6文件改造，约400行

### 3.1 新增数据表

**文件**：`novel_agent/bible/models.py`

```python
class PleasureBeat(Base):
    """爽点档位：规划期产，生成期核对。"""
    __tablename__ = "pleasure_beats"
    id = Column(Integer, primary_key=True, index=True)
    project_id = Column(Integer, ForeignKey("projects.id"), nullable=False, index=True)
    chapter = Column(Integer, nullable=False, index=True)
    tier = Column(String(10), nullable=False)  # small/medium/large
    beat_type = Column(String(50), default="")  # 打脸/装逼/突破/收获/复仇/反转
    target_intensity = Column(Integer, default=5)  # 1-10
    delivered_intensity = Column(Integer, default=0)  # 0=未交付
    status = Column(String(20), default="planned")  # planned/delivered/skipped
    created_at = Column(DateTime, default=datetime.utcnow)

class PlotDebt(Base):
    """欠账账本：复仇/突破/打脸/感情承诺。"""
    __tablename__ = "plot_debts"
    id = Column(Integer, primary_key=True, index=True)
    project_id = Column(Integer, ForeignKey("projects.id"), nullable=False, index=True)
    debt_id = Column(String(20), nullable=False)  # D-001
    debt_type = Column(String(30), nullable=False)  # 复仇/突破/打脸/感情/恩怨
    creditor = Column(String(100), default="")  # 谁欠谁
    description = Column(Text, default="")
    created_chapter = Column(Integer, default=0)
    promised_resolve_chapter = Column(Integer, default=0)
    actual_resolve_chapter = Column(Integer, default=0)
    weight = Column(Integer, default=5)  # 1-10
    pressure = Column(Integer, default=0)  # 压抑积累，随章递增
    status = Column(String(20), default="open")  # open/resolved/waived
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
```

### 3.2 repository补CRUD

**文件**：`novel_agent/bible/repository.py`

仿现有foreshadow三件套（约162-185行），新增：
- `create_pleasure_beat(**kwargs)` / `list_beats_for_chapter(ch)` / `list_beats_for_volume(vol_start, vol_end)` / `update_beat_delivered(ch, intensity)`
- `create_plot_debt(**kwargs)` / `list_open_debts()` / `get_overdue_debts(ch)` / `resolve_debt(debt_id, ch)` / `increment_debt_pressure(ch)`
- `get_pleasure_gap(ch)` —— 返回距上次各档交付的章距

### 3.3 Outliner规划爽点+欠账

**文件**：`novel_agent/planning/agents.py`（约76行outline方法）

prompt JSON追加每章：
```
"satisfactions":[{"tier":"small","beat_type":"打脸","intensity":5}],
"debts":[{"debt_id":"D-001","debt_type":"复仇","creditor":"反派欠主角","description":"..."}]
```

### 3.4 apply_to_bible写入

**文件**：`novel_agent/planning/graph.py`（约59行apply_to_bible）

在写foreshadows的循环后，加写beats和debts的循环（照抄foreshadow写入结构）。

### 3.5 core.py注入爽点+欠账

**文件**：`novel_agent/memory/core.py`（assemble内，紧随本章细纲后注入）

```python
# 爽点档位注入
beats = self.repo.list_beats_for_chapter(chapter)
if beats:
    beat_lines = ["【本章爽点档位】"]
    for b in beats:
        beat_lines.append(f"- {b.tier}爽·{b.beat_type}（目标强度≥{b.target_intensity}）")
    sections.append("\n".join(beat_lines))
else:
    sections.append("【本章爽点档位】压抑章，禁止交付大爽，可埋新欠账/养pressure")

# 欠账注入
open_debts = self.repo.list_open_debts()
due_debts = [d for d in open_debts if d.promised_resolve_chapter <= chapter]
if due_debts:
    debt_lines = ["【本章应还欠账】"]
    for d in due_debts[:3]:  # top3按pressure排序
        debt_lines.append(f"- {d.debt_id}·{d.debt_type}: {d.description[:40]}（pressure={d.pressure}）")
    sections.append("\n".join(debt_lines))
overdue_debts = self.repo.get_overdue_debts(chapter)
if overdue_debts:
    sections.append("【逾期欠账】" + "；".join(f"{d.debt_id}:{d.debt_type}" for d in overdue_debts[:5]))
```

### 3.6 validator确定性检测

**文件**：`novel_agent/audit/validator.py`（run_deterministic_checks内）

```python
def check_pleasure_gap(repo, chapter) -> list[Issue]:
    """爽点断层检测：距上次各档交付的章距。"""
    gap = repo.get_pleasure_gap(chapter)
    issues = []
    if gap.get("small_gap", 0) > 4:
        issues.append(Issue(dimension="爽点分布", severity="important",
            message=f"爽点断层：连续{gap['small_gap']}章无小爽以上交付"))
    if gap.get("medium_gap", 0) > 12:
        issues.append(Issue(dimension="爽点分布", severity="important",
            message=f"中爽断档超12章，读者疲劳"))
    return issues

def check_overdue_debts(repo, chapter) -> list[Issue]:
    """卷高潮欠账强制还。"""
    overdue = repo.get_overdue_debts(chapter)
    if overdue:
        return [Issue(dimension="支线推进度", severity="critical",
            message=f"卷高潮有{len(overdue)}笔欠账未还: {[d.debt_id for d in overdue]}")]
    return []

def check_chapter_hook(draft_text) -> list[Issue]:
    """章末钩强度检查。"""
    tail = draft_text[-200:] if len(draft_text) > 200 else draft_text
    # 启发式：末尾含疑问/未完成动作/危机/新信息
    hook_signals = ["？", "！", "……", "突然", "就在这时", "然而"]
    if not any(s in tail for s in hook_signals):
        return [Issue(dimension="读者期待管理", severity="important",
            message="章末无钩子，读者无追读理由")]
    return []
```

### 3.7 summarize回填交付状态

**文件**：`novel_agent/orchestrator/nodes.py`（summarize内）

prompt JSON追加`"delivered_satisfactions":[{"tier":"","intensity":0}]`和`"resolved_debts":["D-001"]`。
回填：
```python
for ds in data.get("delivered_satisfactions", []) or []:
    repo.update_beat_delivered(chapter, ds.get("intensity", 0))
for did in data.get("resolved_debts", []) or []:
    repo.resolve_debt(did, chapter)
# 逾期欠账pressure递增
repo.increment_debt_pressure(chapter)
```

### 验证标准
```bash
# 规划一卷8章后：
# 1. pleasure_beats表有数据（每章档位）
# 2. plot_debts表有数据（open状态）
# 连续3章无爽点交付 → validator报"爽点断层"
# 卷高潮章有open欠账 → validator报critical
```

---

## 阶段4：元认知监控 + 跨卷编排

**目标**：加"编排者"和卷级流程。
**工作量**：2文件新增 + 4文件改造，约350行

### 4.1 元认知监控节点

**文件**：`novel_agent/orchestrator/metacog.py`（新增）

```python
"""元认知监控环：跨章趋势检测，超阈值挂起异常审。"""
from langgraph.types import interrupt

def compute_indicators(repo, chapter: int) -> dict:
    """计算跨章趋势指标。"""
    open_debts = len(repo.list_open_debts())
    overdue_debts = len(repo.get_overdue_debts(chapter))
    gap = repo.get_pleasure_gap(chapter)
    return {
        "open_debts": open_debts,
        "overdue_debts": overdue_debts,
        "small_gap": gap.get("small_gap", 0),
        "medium_gap": gap.get("medium_gap", 0),
    }

def metacog_node(state, repo) -> dict:
    """元认知节点：summarize后执行，超阈值interrupt。"""
    ind = compute_indicators(repo, state["chapter"])
    anomalies = []
    if ind["overdue_debts"] > 3:
        anomalies.append(f"欠账堆积{ind['overdue_debts']}笔")
    if ind["small_gap"] > 6:
        anomalies.append(f"爽点断档{ind['small_gap']}章")
    if ind["open_debts"] > 10:
        anomalies.append(f"在途欠账{ind['open_debts']}笔，可能失控")
    if anomalies:
        interrupt({"type": "anomaly_review", "chapter": state["chapter"],
                   "anomalies": anomalies, "indicators": ind})
    return {"status": "completed"}
```

### 4.2 graph加metacog节点

**文件**：`novel_agent/orchestrator/graph.py`

```python
# summarize → metacog → END
graph.add_node("metacog", partial(metacog_node, repo=deps["repo"]))
graph.add_edge("summarize", "metacog")
graph.add_edge("metacog", END)
# 移除每章human_review必经节点，改为metacog按需interrupt
```

### 4.3 章级人审改真interrupt

**文件**：`novel_agent/orchestrator/nodes.py`（约269行human_review）

```python
def human_review(state: ChapterGenState) -> dict:
    """人审节点：改为真interrupt（仅metacog触发异常时才到这）。"""
    from langgraph.types import interrupt
    decision = interrupt({
        "type": "chapter_review",
        "chapter": state["chapter"],
        "draft": state.get("polished") or state.get("draft", ""),
        "audit_report": state.get("audit_report", {}),
    })
    return {"review_decision": decision,
            "status": "approved" if decision.get("approved") else "rejected"}
```

### 4.4 卷摘要激活

**文件**：`novel_agent/memory/summary_tree.py`（约49行generate_volume_summary）

存库（当前只return不存）：
```python
def generate_volume_summary(self, volume: int) -> str:
    # ... 现有LLM压缩逻辑 ...
    # 存库
    from novel_agent.bible.models import Outline
    vol_outline = self.repo.db.query(Outline).filter(
        Outline.project_id == self.repo.project_id,
        Outline.level == "volume", Outline.order == volume,
    ).first()
    if vol_outline:
        vol_outline.summary = summary  # 存到卷大纲的summary字段
        self.repo._commit_or_flush()
    return summary
```

core.py跨卷注入卷摘要：
```python
# _format_previous_summaries内
prev_volume_summary = self.summary_tree.get_volume_summary(prev_vol)
if prev_volume_summary:
    sections.append(f"【上一卷摘要】\n{prev_volume_summary[:500]}")
```

### 4.5 BookRunner跨卷编排

**文件**：`novel_agent/planning/book_runner.py`（新增）

```python
"""跨卷编排：卷规划→人审①→逐章生成→卷末审→卷摘要→下一卷。"""
class BookRunner:
    def __init__(self, config, repo, llm_client=None):
        self.config = config
        self.repo = repo
        self.llm_client = llm_client or LLMClient(config.llm)
        self.volume_runner = VolumeRunner(config, repo, self.llm_client)
        self.chapter_runner = ChapterRunner(config, repo, self.llm_client)

    async def run_volume(self, volume_name: str, chapter_count: int, thread_id: str):
        """跑一整卷：规划→人审→逐章→卷末。"""
        # 1. 卷规划+人审①
        plan = await self.volume_runner.run(volume_name, chapter_count, thread_id)
        # 2. 逐章生成
        for ch in range(1, chapter_count + 1):
            outline = self.repo.list_outlines(level="chapter")
            ch_outline = next((o for o in outline if o.order == ch), None)
            title = ch_outline.title if ch_outline else f"第{ch}章"
            result = await self.chapter_runner.run(chapter=ch, title=title)
            if result.get("status") not in ("completed", "approved"):
                break  # 异常停止
        # 3. 卷末：卷摘要 + 卷末审（metacog触发）
        self.summary_tree.generate_volume_summary(current_volume)
        # 4. 下一卷由调用方决定
```

**文件**：`novel_agent/cli.py` 新增 `book` 子命令。

### 验证标准
```bash
# BookRunner跑完卷一8章后：
# 1. 卷摘要存入Outline(level=volume)的summary字段
# 2. 卷二的core memory注入"上一卷摘要"而非8章全文
# 3. 异常时（欠账>3/爽点断档>6章）metacog触发interrupt
```

---

## 保留/废弃清单

| 文件 | 处置 | 理由 |
|---|---|---|
| `memory/memory_pack.py` | **删除** | 死代码，零调用者，两套记忆产出不一致 |
| `bible/models.py` EmotionArc/SubplotBoard/CharacterMatrix | **激活**（阶段1补写入） | 死表，阶段1补写入路径后激活 |
| `memory/summary_tree.py:generate_volume_summary` | **激活**（阶段4存库） | 死代码，存库后激活 |
| `orchestrator/nodes.py:save_text/save_summary`（280-305行） | **删除** | M2兼容节点，仅旧测试引用 |
| `protocol/applier.py:61` 兜底db.commit() | **保留** | 当前实际需要它落盘，阶段1统一后可移除 |
| `audit/dimensions.py` 19维平铺 | **阶段3改** | 补爽点断层/欠账/钩子确定性检查，不删LLM维度 |

## 不做的事（明确排除）

- ❌ 不建"八大中枢"概念——用具体表/函数
- ❌ 不做向量检索历史片段——写作热路径用状态快照
- ❌ 不做情感引擎state machine——情感由处境emergent
- ❌ 不做每角色独立agent——只核心角色建模
- ❌ 不做审美判断硬门禁——降级为软信号+人审
- ❌ 不推翻现有代码——4阶段渐进，每阶段可验证

## 优先级总结

| 阶段 | 内容 | 不做的后果 | 工作量 |
|---|---|---|---|
| 1 | 回写闭环 | 事件流/状态变更全丢，第50章失忆 | ~250行 |
| 2 | 状态快照 | 第150章后对全书90%中段失忆 | ~300行 |
| 3 | 爽点供应链+欠账 | 百万字=百万字流水账 | ~400行 |
| 4 | 元认知+跨卷 | 无编排者，每章人审太累，无卷末止损 | ~350行 |

**总计约1300行。4阶段是串行依赖链（非独立可验证），必须按顺序逐阶段实施，每阶段完成后用真实LLM跑5章验证。**

---

## 对抗审查修订项（工程师必读）

> 以下为多agent对抗审查发现的致命问题，**必须在实现时遵守**，否则方案执行到一半会崩盘。

### P0 必改项（不改会崩）

#### P0-1. 阶段1角色回写必须包 try/except + 角色不存在时跳过
**问题**：方案1.4把`repo.update_character`直写改为applier.apply，但applier的`_character_state_change`在角色不存在时抛`ApplyError`，且角色回写块**没有try/except包裹**。LLM常返回圣经里没有的角色名 → 整章生成失败。
**修法**：角色回写块（方案1.4第106-121行）必须像emotion/matrix块一样包`try/except Exception: pass`，且在apply前先`if not repo.get_character(name): continue`：
```python
for cs in data.get("character_states", []) or []:
    name = cs.get("name", "").strip()
    if not name or not repo or not repo.get_character(name):
        continue  # 角色不存在则跳过，不崩
    try:
        # ... applier.apply 逻辑 ...
    except Exception:
        pass  # 单条失败不崩整章
```

#### P0-2. 阶段4拆为4a（BookRunner无interrupt）+ 4b（metacog+resume）
**问题**：metacog的interrupt没有resume端点。`cli.py`无章节级resume；`runner.py`不处理`GraphInterrupt`。metacog触发interrupt → 章节永久挂起。
**修法**：
- **4a**：BookRunner + 卷摘要激活（不含metacog interrupt）。BookRunner串行跑卷，每章用ChapterRunner现有流程（不interrupt）。
- **4b**：metacog + resume。**必须先实现resume端点**（CLI `chapter-resume` 子命令 + API `/api/chapters/resume` 端点），再启用metacog的interrupt。`runner.py`的`run`方法必须捕获`GraphInterrupt`并返回`{"status":"interrupted","interrupt_data":...}`而非崩溃。
- 4a可独立上线验证，4b在resume端点就位后再做。

#### P0-3. 阶段3/4的repo方法必须先实现并单测
**问题**：`get_pleasure_gap`/`get_overdue_debts`/`list_open_debts`/`list_beats_for_chapter`/`update_beat_delivered`/`increment_debt_pressure`/`resolve_debt`/`create_pleasure_beat`/`create_or_update_subplot` 全库零存在。阶段3/4的core.py注入/validator检查/metacog指标直接调这些方法 → AttributeError。
**修法**：阶段3落地**第一步**就是实现方案3.2的全部repo方法 + 写单测（`tests/test_repository_debts.py`），确认方法存在且返回正确，再接core.py/validator/metacog。

#### P0-4. "4阶段独立可验证"改为"串行依赖链"
**问题**：阶段3爽点注入依赖阶段2快照（活跃伏笔），阶段2快照依赖阶段1回写（SubplotBoard/StateChange），阶段4 metacog依赖阶段3数据（欠账/爽点gap）。**不是独立的**。
**修法**：必须严格按1→2→3→4顺序。每阶段做完用真实LLM跑5章验证上游产出正确，再做下一阶段。不能跳阶段或并行做。

#### P0-5. Delta.target Literal 与 handler 必须同一commit原子提交
**问题**：先改applier后改schema（或反之），pydantic在`Delta(...)`构造时即抛ValidationError，发生在summarize主路径无except兜底 → 整章失败。
**修法**：方案1.1（schemas.py加Literal值）和1.2（applier.py加handler）必须在**同一个git commit**里提交，不能分两次。

### P1 必改项（不改会有严重bug）

#### P1-1. snapshot.py 不能用 `last_active_chapter`（字段不存在）
**问题**：Character表无`last_active_chapter`列，`hasattr`恒False → 配角从快照消失。
**修法**：用`EntityAppearance`表查最近3章出场的角色（`get_active_entities_for_chapter`已有），或给Character加`last_active_chapter`列（migrate_db自动加列）。推荐前者——不改表结构。
```python
# 替代方案2.2的角色过滤
active_result = repo.get_active_entities_for_chapter(chapter)  # 返回dict
active_char_names = set(active_result.get("characters", []))
chars = [c for c in repo.list_characters()
         if c.role in ("主角", "反派") or c.name in active_char_names]
```

#### P1-2. validator 新check签名必须兼容现有 run_deterministic_checks
**问题**：现有`run_deterministic_checks(draft, foreshadows_to_plant, word_min, word_max)`不接受repo/chapter。方案3.6的`check_pleasure_gap(repo, chapter)`接不进去。
**修法**：改`run_deterministic_checks`签名加`repo=None, chapter=None`可选参数，保持向后兼容：
```python
def run_deterministic_checks(draft, foreshadows_to_plant, word_min=2000, word_max=5000,
                              repo=None, chapter=None):
    issues = [...现有3项检查...]
    if repo and chapter:
        issues.extend(check_pleasure_gap(repo, chapter))
        issues.extend(check_overdue_debts(repo, chapter))
    return issues
```

#### P1-3. 8000字符预算优先级必须明确
**问题**：爽点档位+欠账注入可能800-1200字，挤占角色段导致OOC。
**修法**：明确优先级序列（从高到低）：
1. 本章细纲（最高，不压缩）
2. 爽点档位（硬约束，不压缩）
3. 角色状态快照（不压缩）
4. 应还欠账（可截断到top3）
5. 前文摘要（可压缩到5章）
6. 逾期伏笔/欠账提醒（可截断到top5）
7. archival检索（最低，可全删）

#### P1-4. 章末钩检查改LLM判断，不用关键词硬门禁
**问题**：方案3.6用"？/！/……/突然"关键词检查——违反方案自身原则"LLM判断的=软信号"。且会教模型刷分（硬塞"？！"过检查）。
**修法**：章末钩改由auditor的LLM判断（已有"读者期待管理"维度），validator不加关键词检查。章末钩强度由summarize抽取的`hook_strength`回填，metacog监控连续低钩子章节。

#### P1-5. generate_volume_summary 签名必须传 llm_client
**问题**：实际`generate_volume_summary(self, volume, llm_client)`需要llm_client参数，方案4.4省略了。BookRunner未初始化summary_tree。
**修法**：
```python
# BookRunner.__init__ 里
from novel_agent.memory.summary_tree import SummaryTree
self.summary_tree = SummaryTree(repo)

# 调用时传 llm_client
summary = await self.summary_tree.generate_volume_summary(current_volume, self.llm_client)
```

#### P1-6. archival 双路径不能删commit的全文索引
**问题**：applier索引的是`core_events+chapter_hook`（摘要拼接），commit索引的是正文全文。方案1.5说"删除commit的archival.index_chapter"会丢失全文检索能力。
**修法**：保留commit的全文索引，applier的摘要索引改为可选（或删除applier的索引避免重复）。两条路径索引不同内容，都有价值。

### P2 应改项（不改会有质量问题）

#### P2-1. 爽点阈值和类型从自家CSV读取，不硬编码
**问题**：方案small_gap>4断层，但自家`references/csv/爽点与节奏.csv` R-005说"每5-10章一个小高潮"。beat_type六类也太粗，CSV有更全的类型。
**修法**：
- 阈值从CSV读取：`small_gap_threshold = int(csv_config.get("small_gap", 5))`
- beat_type从CSV的爽点类型列读取，不硬编码六类
- 不同题材不同阈值（CSV有"适用题材"列）

#### P2-2. 压抑章不累加gap
**问题**：压抑章delivered_intensity=0 → gap+1 → 报断层 → 逼系统硬塞爽点，破坏"压抑-爆发"结构。
**修法**：`check_pleasure_gap`区分压抑章和断档章。如果本章大纲标记为"压抑/铺垫"且有意为之，不累加gap。或：gap计算时跳过`status=skipped`的beat行（压抑章不产beat行）。

#### P2-3. pressure非线性累积
**问题**：线性+1是玩具模型，长线欠账会涨到天文数字无信息量。
**修法**：
```python
# pressure 累积公式
urgency = 2.0 if chapter > debt.promised_resolve_chapter else 1.0  # 逾期翻倍
decay = 0.5 if chapter - debt.created_chapter > 60 else 1.0  # 超60章衰减（读者已遗忘）
debt.pressure = int(debt.weight * (1 + min(chapter - debt.created_chapter, 30) * 0.1) * urgency * decay)
```

#### P2-4. 卷高潮只强制还本卷欠账，长线欠账保留
**问题**：方案`check_overdue_debts`在卷高潮把所有overdue判critical——会逼系统把长线大欠账（身世/总BOSS）也在卷末还掉。
**修法**：`get_overdue_debts(chapter)`加`scope`参数：
```python
def get_overdue_debts(self, chapter: int, scope: str = "volume") -> list:
    """scope=volume只取本卷欠账，scope=all取全部。卷高潮用volume。"""
    # 按 created_chapter >= volume_start 过滤
```

#### P2-5. 接入方舟Embedding模型替代bge-small-zh
**背景**：方舟Coding Plan提供Embedding模型，用于语义向量检索。
**修法**：见下方"Embedding接入"专节。

### P3 后续补强（不阻塞百万字地基，但影响质量上限）

- **开篇/上架节奏曲线**：前3章密度加密（2章一爽）、上架章强制大爽、之后转常规。需要PleasureBeat表加`phase`字段（opening/shangjia/regular）
- **配角上限护栏**：Character加`residence_status`（resident/guest/exited），超8个resident强制最低importance退场
- **角色声音指纹**：Character加`catchphrase/avg_sentence_len/speech_style/voice_sample`字段，validator加漂移检测
- **力量体系追踪**：Character加`power_level`字段，StateChange追踪power_level变化，validator检查"只能升不能降除非有剧情事件"
- **"不写什么"裁剪**：新增`cut_rules`表，validator加水戏/配角戏超载/支线膨胀检测

---

## Embedding接入（方舟模型）

### 背景
方舟Coding Plan提供Embedding模型，替代当前archival的bge-small-zh（本地模型，加载慢、占内存）。

### 改造文件
**`novel_agent/memory/archival.py`**

当前archival用Chroma默认的`all-MiniLM-L6-v2`或`bge-small-zh`（本地）。改为调方舟Embedding API：

```python
import httpx
from novel_agent.config import Config

class ArkEmbeddingFunction:
    """方舟Embedding模型适配器，替代Chroma默认的本地embedding。"""

    def __init__(self, config: Config):
        self.base_url = config.llm.base_url.rstrip("/")
        self.api_key = config.llm.api_key
        # 方舟embedding端点（具体model名按方舟文档）
        self.model = "ep-xxx-embedding"  # TODO: 填方舟embedding模型ID

    def __call__(self, input: list[str]) -> list[list[float]]:
        """批量文本转向量。Chroma的embedding_function接口。"""
        resp = httpx.post(
            f"{self.base_url}/embeddings",
            headers={"Authorization": f"Bearer {self.api_key}",
                     "Content-Type": "application/json"},
            json={"model": self.model, "input": input},
            timeout=60.0,
        )
        resp.raise_for_status()
        data = resp.json()
        return [item["embedding"] for item in data["data"]]
```

ArchivalMemory初始化时注入：
```python
class ArchivalMemory:
    def __init__(self, config: Config):
        # ...
        self._embedding_fn = ArkEmbeddingFunction(config)
        self._collection = self._client.get_or_create_collection(
            name="novel_archive",
            embedding_function=self._embedding_fn,  # 用方舟模型
            metadata={"hnsw:space": "cosine"},
        )
```

### 注意事项
1. **写作热路径仍优先用状态快照**，archival仅作"快照不足时的可选补充"和"用户主动检索"场景
2. 方舟Embedding是API调用（有网络延迟+成本），不像bge是本地推理。大批量索引时注意限流
3. 需要在`config.yaml`加embedding模型配置项（或复用llm的base_url/api_key）
4. 方舟embedding的具体model ID需要查方舟控制台获取（如`ep-202404xxxxxx-xxxxx`）

### 验证标准
```bash
# 索引一章后检索，确认向量来自方舟模型
python -c "
from novel_agent.memory.archival import ArchivalMemory
from novel_agent.config import load_config
am = ArchivalMemory(load_config())
am.index_chapter(1, '测试', '主角在废墟中觉醒异能')
results = am.retrieve(query='异能觉醒', top_k=2)
print('results:', len(results))
# 预期：能召回，且不报本地模型加载错误
"
```

---

## 修订后的工作量估算

| 阶段 | 原估算 | 修订后 | 增加原因 |
|---|---|---|---|
| 1 | ~250行 | ~300行 | +try/except兜底 +atomic提交约束 |
| 2 | ~300行 | ~350行 | +EntityAppearance替代last_active +fallback修正 |
| 3 | ~400行 | ~550行 | +repo方法先实现单测 +CSV阈值 +压抑章处理 +pressure非线性 |
| 4 | ~350行 | ~500行 | +拆4a/4b +resume端点 +llm_client传递 |
| Embedding | 0 | ~100行 | 新增方舟模型适配 |
| **总计** | ~1300行 | **~1800行** | |

**实际工作量（含测试+调试+prompt调优）预计3000-4000行。建议每阶段做完真实LLM验证再进下一阶段。**
