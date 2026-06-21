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

**总计约1300行，4阶段每阶段独立可验证。建议按顺序逐阶段实施，每阶段完成后用真实LLM跑5章验证。**
