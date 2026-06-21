# 百万字网文生成系统 · 优化方案（v2）

> 基于原方案（2026-06-21-million-word-plan.md）+ 5轮多agent对抗讨论收敛。
> 工程师可直接按此执行。当前基线：132测试通过，5章生成质量已验证。

## 与原方案的核心差异

原方案4阶段（回写闭环→快照→爽点供应链→元认知监控）方向正确，但5轮对抗讨论暴露了5个根本性问题：

| 问题 | 原方案 | 本方案修正 |
|---|---|---|
| 数据流方向 | 自底向上（写正文→从正文抽12字段状态） | **自顶向下**（大纲带约束→正文满足约束→summarize校验而非抽取） |
| 快照保真度 | 假设LLM抽取可信，无校验 | 加**text-vs-snapshot一致性校验** + 周期性全量重摘要 |
| 爽点新鲜度 | 只查gap频率，不查重复 | 用**方舟Embedding做跨章语义去重**，检测"这场景写没写过" |
| summarize角色 | 从正文抽12个结构化字段（抽取器） | 核对正文是否满足大纲规范（**校验器**），大幅减少抽取字段 |
| 产业及格线 | 只做"不崩"，延后黄金三章/上架 | **黄金三章/上架节奏提前到阶段3**，不延后 |

## 设计原则（修订）

1. **不建"中枢"概念**——用具体的表/函数/节点
2. **确定性检查>LLM判断**——能SQL算的硬编码，不交给LLM
3. **软信号vs硬门禁**——LLM判断的=软信号+人审兜底；确定性可验证的=硬门禁
4. **大纲规范>正文抽取**——大纲带约束载荷，正文满足规范，summarize校验而非抽取
5. **快照>向量检索**（热路径）——写作上下文用状态快照O(1)读当前态
6. **向量检索>关键词匹配**（冷路径）——跨章语义去重/按需检索用方舟Embedding
7. **每阶段真跑LLM+人读验收**——不靠mock单测判定成功
8. **渐进改造不推翻**——保留现有好资产（LangGraph/bible/applier/132测试/写审分离）

---

## 阶段0：数据流掉头（先改方向，再补功能）

**目标**：让大纲节点承载约束载荷，summarize从"抽取器"改"校验器"。这一步消除原方案大半复杂度。
**工作量**：3文件改造，约150行

### 0.1 Outline表加约束字段

**文件**：`novel_agent/bible/models.py`

Outline表（约175行）加列：
```python
class Outline(Base):
    # ... 现有字段 ...
    # 新增：约束载荷（大纲带规范，正文满足规范）
    required_beats = Column(Text, default="")    # JSON: [{"tier":"small","type":"打脸","intensity":5}]
    owed_debts = Column(Text, default="")        # JSON: [{"type":"复仇","desc":"...","pressure":3}]
    required_hooks = Column(Text, default="")    # JSON: {"type":"悬念","target_strength":7}
    character_constraints = Column(Text, default="")  # JSON: {"陆辰":{"location":"基地","emotion":"愤怒"}}
```

`migrate_db`（约349行）会自动加列。

### 0.2 Outliner产出约束载荷

**文件**：`novel_agent/planning/agents.py`（约76行outline方法）

prompt JSON追加：
```
"required_beats":[{"tier":"small","type":"打脸","intensity":5}],
"owed_debts":[{"type":"复仇","desc":"反派欠主角","pressure":3}],
"required_hooks":{"type":"悬念","target_strength":7}
```

`apply_to_bible`（`planning/graph.py:59`）把这些写入Outline的约束字段。

### 0.3 summarize从"抽取器"改"校验器"

**文件**：`novel_agent/orchestrator/nodes.py`（约186行summarize_chapter）

**核心改变**：summarize不再从正文抽12个字段。改为：
1. 读本章Outline的约束载荷（required_beats/owed_debts/required_hooks）
2. 让LLM核对：正文是否满足了这些约束？哪些满足/哪些没满足？
3. 回写：章摘要（保留，但简化为core_events+hook_strength两个字段）+ 约束满足状态

```python
async def summarize_chapter(state, llm_client, applier, repo=None):
    content = state.get("polished") or state.get("draft", "")
    chapter = state["chapter"]

    # 读本章大纲约束
    outline = repo.get_outline_by_chapter(chapter) if repo else None
    constraints = {}
    if outline:
        import json
        constraints = {
            "beats": json.loads(outline.required_beats or "[]"),
            "debts": json.loads(outline.owed_debts or "[]"),
            "hooks": json.loads(outline.required_hooks or "{}"),
        }

    # LLM核对：正文是否满足约束（校验器，非抽取器）
    prompt = f"""核对第{chapter}章正文是否满足以下写作约束。

【写作约束】
{json.dumps(constraints, ensure_ascii=False, indent=2)}

【正文】
{content[:3000]}

输出JSON：
{{"core_events":"","hook_strength":0,"beats_delivered":[{{"tier":"","delivered":false,"intensity":0}}],"debts_resolved":["D-001"],"character_states":[{{"name":"","location":"","emotion":""}}]}}
只输出JSON。"""

    # ... LLM调用 + JSON解析（保留现有容错）...

    # 回写（大幅简化：不再抽emotion_arcs/subplot_updates/character_interactions等）
    # 只写：章摘要 + 角色位置/情绪（走applier）+ beat交付状态 + debt偿还
```

**关键改变**：
- summarize的JSON从12字段降到5字段（core_events/hook_strength/beats_delivered/debts_resolved/character_states）
- 不再抽emotion_arcs/subplot_updates/character_interactions（这些改为从大纲约束推导，不从正文反推）
- character_states只更新location/emotion（走applier写StateChange+TruthEvent）

### 0.4 回写覆盖率探针（防silent失败）

**文件**：`novel_agent/orchestrator/nodes.py`（summarize末尾）

```python
# 回写覆盖率探针：统计本章实际写入的表数
coverage = {
    "summary": 1 if repo.get_chapter_summary(chapter) else 0,
    "state_changes": len(repo.list_events(chapter=chapter, type_filter="character_state_change")) if hasattr(repo, "list_events") else 0,
    "beats_delivered": sum(1 for b in data.get("beats_delivered", []) if b.get("delivered")),
}
if repo:
    import logging
    logging.getLogger("novel_agent.coverage").info(
        f"ch{chapter} 回写覆盖: {coverage}")
```

### 验证标准（必须真跑LLM）
```bash
# 真跑3章LLM后检查：
# 1. Outline的required_beats/owed_debts字段有数据（非空JSON）
# 2. summarize日志显示回写覆盖率（beats_delivered>0 / character_states有值）
# 3. 如果覆盖率探针显示beats_delivered=0连续3章 → 停下来调prompt，不进阶段1
```

---

## 阶段1：回写闭环（精简版）

**目标**：summarize走applier写StateChange/TruthEvent，补EmotionArc/CharacterMatrix/SubplotBoard写入。
**工作量**：4文件改造，约200行（比原方案少50行，因阶段0已减少抽取字段）

### 1.1-1.3 同原方案
（schemas.py加Delta类型 / applier加handler / repository加写入方法）

### 1.4 summarize_chapter回写（精简版）

**文件**：`novel_agent/orchestrator/nodes.py`

阶段0已把summarize改成校验器，回写字段从12个降到5个。这里只需：
- 角色location/emotion变更走applier（包try/except + 角色不存在跳过，P0-1）
- beats_delivered回写PleasureBeat表（阶段3建表后）
- debts_resolved回写PlotDebt表（阶段3建表后）

**注意**：阶段1先不做EmotionArc/SubplotBoard/CharacterMatrix的回写——阶段0的"校验器"模式下，这些表的数据从大纲约束推导而非正文抽取，放到阶段3随爽点/欠账一起做。

### 1.5 commit_chapter合流

**文件**：`novel_agent/api/routes_generation.py`

同原方案：commit_chapter的直写改走applier。但**保留commit的archival全文索引**（P1-6），applier的摘要索引改为可选。

### 验证标准
```bash
# 真跑3章后：truth_events有character_state_change类型事件
# 角色位置变更走applier → StateChange表有记录
```

---

## 阶段2：状态快照 + 快照保真度校验

**目标**：O(1)读当前世界状态 + 防止快照与正文漂移。
**工作量**：2文件新增 + 3文件改造，约350行

### 2.1-2.3 同原方案
（StateSnapshot表 / snapshot.py / repository快照读写）

### 2.2修正：snapshot.py用EntityAppearance替代last_active_chapter（P1-1）

```python
def build_snapshot(repo, chapter):
    # 用get_active_entities_for_chapter（已有，返回dict）查活跃角色
    active_result = repo.get_active_entities_for_chapter(chapter)
    active_char_names = set(active_result.get("characters", []))
    chars = [c for c in repo.list_characters()
             if c.role in ("主角", "反派") or c.name in active_char_names]
    # ... 伏笔/支线/势力 ...
```

### 2.4 CoreMemoryAssembler优先读快照

同原方案，但**8000字符预算优先级明确**（P1-3）：
1. 本章细纲+约束载荷（不压缩）
2. 角色状态快照（不压缩）
3. 前文摘要（5章，可压缩）
4. 逾期伏笔/欠账（top5，可截断）
5. archival检索（最低，可全删）

### 2.5 快照保真度校验（新增，原方案没有）

**文件**：`novel_agent/memory/snapshot.py`

```python
def validate_snapshot_fidelity(repo, chapter, draft_text) -> dict:
    """校验快照与正文的一致性，返回漂移报告。"""
    snap = repo.get_latest_state_snapshot(chapter)
    if not snap:
        return {"valid": True, "reason": "无快照，跳过"}

    issues = []
    # 检查角色位置：快照说"基地"，正文是否提到角色在基地
    for char in snap.get("characters", []):
        name = char.get("name", "")
        location = char.get("location", "")
        if location and location not in draft_text and name in draft_text:
            issues.append(f"角色{name}快照位置={location}但正文未提及该地点")

    # 检查伏笔状态：快照说planted，正文是否真的埋了
    for fs in snap.get("foreshadows", []):
        if fs.get("id") in draft_text and fs.get("status") == "pending":
            issues.append(f"伏笔{fs['id']}快照=pending但正文提及，可能已埋设未更新")

    return {
        "valid": len(issues) == 0,
        "issues": issues,
        "drift_score": len(issues),  # 漂移分数，metacog可监控
    }
```

**调用时机**：每章summarize后调一次，drift_score > 阈值时触发周期性全量重摘要。

### 2.6 周期性全量重摘要（防误差复利）

**文件**：`novel_agent/orchestrator/nodes.py`（summarize内）

每20章触发一次全量重摘要（而非增量抽取）：
```python
if chapter % 20 == 0 and chapter > 0:
    # 全量重摘要：重新从正文抽取当前状态，覆盖快照
    # 这比每章增量抽取更准，因为不累积误差
    full_resummary = await _full_resummary(llm_client, repo, chapter)
    repo.save_state_snapshot(chapter, full_resummary)
```

### 验证标准
```bash
# 连续生成20章后：
# 1. state_snapshots每章1条
# 2. core memory字符数稳定（不随章数增长）
# 3. 第20章触发全量重摘要（日志可见）
# 4. validate_snapshot_fidelity的drift_score < 3
```

---

## 阶段3：爽点供应链 + 欠账账本 + 新鲜度检测

**目标**：档位规划/断层检测/欠账累积/跨章语义去重 + 黄金三章/上架节奏。
**工作量**：2表新增 + 6文件改造 + 1文件新增，约600行

### 3.1-3.2 同原方案
（PleasureBeat/PlotDebt表 / repository CRUD）

### 3.3 爽点阈值从CSV读取（P2-1）

**文件**：`novel_agent/audit/validator.py`

```python
import csv
from pathlib import Path

def _load_pleasure_thresholds():
    """从references/csv/爽点与节奏.csv读取阈值。"""
    csv_path = Path(__file__).parent.parent / "references" / "csv" / "爽点与节奏.csv"
    thresholds = {"small_gap": 5, "medium_gap": 12, "large_gap": 30}
    try:
        with open(csv_path, encoding="utf-8") as f:
            for row in csv.DictReader(f):
                if "小高潮间隔" in row.get("规则", ""):
                    thresholds["small_gap"] = int(row.get("数值", 5))
    except Exception:
        pass
    return thresholds
```

### 3.4 压抑章不累加gap（P2-2）

**文件**：`novel_agent/audit/validator.py`

```python
def check_pleasure_gap(repo, chapter) -> list:
    thresholds = _load_pleasure_thresholds()
    # 查本章是否有beat计划——无beat=压抑章，不累加gap
    beats_this_ch = repo.list_beats_for_chapter(chapter)
    if not beats_this_ch:
        return []  # 压抑章，不报断层
    # 有beat但未交付 → 检查gap
    gap = repo.get_pleasure_gap(chapter)
    # ... 同原方案 ...
```

### 3.5 跨章语义去重（方舟Embedding，新增）

**文件**：`novel_agent/audit/dedup_scanner.py`（新增）

```python
"""跨章语义去重扫描器：用方舟Embedding检测重复场景。
冷路径运行，不进写作热路径。"""
from novel_agent.memory.archival import ArchivalMemory
from novel_agent.config import Config

class DedupScanner:
    def __init__(self, config: Config):
        self.archival = ArchivalMemory(config)

    def scan_chapter(self, chapter: int, draft_text: str, top_k: int = 5) -> list[dict]:
        """扫描本章正文是否和已有章节语义重复。"""
        # 用正文前500字检索历史章节
        results = self.archival.retrieve(
            query=draft_text[:500], top_k=top_k)
        duplicates = []
        for r in results:
            if r.get("distance", 1.0) < 0.3:  # 余弦距离<0.3=高度相似
                duplicates.append({
                    "chapter": r.get("chapter"),
                    "similarity": 1 - r["distance"],
                    "matched_content": r["content"][:80],
                })
        return duplicates

    def check_beat_freshness(self, chapter: int, beat_type: str,
                              beat_desc: str) -> bool:
        """检查这个爽点类型最近有没有写过相似的。"""
        results = self.archival.retrieve(
            query=f"{beat_type} {beat_desc}", top_k=3)
        for r in results:
            if r.get("distance", 1.0) < 0.25:
                return False  # 最近写过相似的，不新鲜
        return True
```

**调用时机**：审计阶段（audit节点后），作为软信号注入audit_report。不阻塞生成。

### 3.6 黄金三章/上架节奏（从P3提前）

**文件**：`novel_agent/bible/models.py`

PleasureBeat表加`phase`字段：
```python
phase = Column(String(20), default="regular")  # opening/shangjia/regular
```

**文件**：`novel_agent/planning/agents.py`（Outliner）

前3章强制phase=opening，密度加密（每章一个小爽）；上架章（可配置，默认第20章）phase=shangjia，强制大爽。

**文件**：`novel_agent/audit/validator.py`

```python
def check_golden_three(repo, chapter) -> list:
    """黄金三章检查：前3章必须有主角登场/核心冲突/世界观钩子。"""
    if chapter > 3:
        return []
    issues = []
    beats = repo.list_beats_for_chapter(chapter)
    if chapter <= 3 and not beats:
        issues.append(Issue(dimension="爽点分布", severity="critical",
            message=f"第{chapter}章是黄金三章但无爽点计划"))
    return issues
```

### 3.7 pressure非线性 + 卷高潮分长短线（P2-3/P2-4）

同原方案修订项。

### 验证标准
```bash
# 规划一卷8章后：
# 1. pleasure_beats表有数据，前3章phase=opening
# 2. plot_debts表有open状态数据
# 3. 连续3章无beat交付 → validator报断层（但压抑章不报）
# 4. DedupScanner检测到相似场景 → audit_report有dedup警告
# 5. 卷高潮章只有本卷欠账被判critical（长线不判）
```

---

## 阶段4：跨卷编排 + 元认知监控（拆4a/4b）

### 4a：BookRunner + 卷摘要激活

**目标**：跨卷编排 + 卷摘要存库注入下一卷。
**工作量**：1文件新增 + 3文件改造，约250行

同原方案4.4-4.5，但修正：
- `generate_volume_summary`传`llm_client`（P1-5）
- BookRunner初始化`summary_tree`
- BookRunner给每章传`thread_id`（断点续跑）
- 异常时不break，而是记录失败章节+跳过继续（防太监）

### 4b：元认知监控 + resume（后置）

**目标**：异常interrupt + resume端点。
**工作量**：2文件新增 + 3文件改造，约250行

**前提**：必须先实现resume端点 + 章节runner迁移到AsyncSqliteSaver。

metacog先用**日志告警**替代interrupt（阶段4a时），resume端点就位后再启用interrupt（阶段4b）。

### 验证标准
```bash
# 4a：BookRunner跑完卷一8章 → 卷摘要存库 → 卷二core memory注入卷一摘要
# 4b：metacog检测到异常 → interrupt → chapter-resume命令恢复
```

---

## Embedding重定位（方舟模型）

### 当前状态
- 方舟Embedding已接入（`archival.py:19-51`），但缺`openai`包导致回退到chromadb默认
- `core.py:54-58/130-132`在热路径注入archival切片——违反"快照>向量检索"原则

### 改造

**1. 修openai包 + config**（5行）
```bash
pip install openai
# config.yaml已有embedding配置（api_key/base_url/model）
```

**2. 从热路径移出archival**（删core.py:54-58/130-132的注入）

**3. 重定位为冷路径工具**：
- `dedup_scanner.py`（阶段3.5）——跨章语义去重
- auditor按需检索工具——审校时查"这个设定以前提过吗"
- Outliner欠账发现——规划时查"这个欠账能还吗"

**4. 修复真实成本**：~5行config + 删2段core.py注入 + dedup_scanner.py（阶段3已含）

---

## 产业及格线补强（不延后到P3）

### 必须在阶段3做的（不延后）

| 补强项 | 做法 | 不做的后果 |
|---|---|---|
| **黄金三章** | PleasureBeat加phase=opening，前3章密度加密 | 没人看下去 |
| **章末钩** | Outline加required_hooks字段，summarize校验hook_strength | 读者不追更 |
| **完本保障** | BookRunner异常不break，记录失败章节跳过继续 | 太监=死书 |

### 后续补强（P3，不阻塞百万字地基）

| 补强项 | 优先级 |
|---|---|
| 书名/简介/封面生成 | 中（影响点击率但不影响生成） |
| 上架章强制大爽 | 中（phase=shangjia已设计，阈值待调） |
| 日更/连载调度器 | 低（BookRunner是批量模式，连载模式是产品形态选择） |
| 读者反馈闭环 | 低（需接平台API，是v2功能） |
| 配角上限护栏 | 中（快照chars[:15]已有截断，退场机制待补） |
| 角色声音指纹 | 中（Character加catchphrase/speech_style字段，validator加漂移检测） |
| 力量体系追踪 | 中（Character加power_level字段，StateChange追踪） |
| "不写什么"裁剪 | 低（cut_rules表，validator加水戏检测） |

---

## 修订后的工作量估算

| 阶段 | 内容 | 工作量 | 比原方案 |
|---|---|---|---|
| 0 | 数据流掉头 | ~150行 | 新增（消除后续复杂度） |
| 1 | 回写闭环（精简） | ~200行 | -50行（阶段0减少了抽取字段） |
| 2 | 快照+保真度校验 | ~350行 | +50行（加保真度校验+全量重摘要） |
| 3 | 爽点+欠账+去重+黄金三章 | ~600行 | +200行（加去重+黄金三章+CSV阈值） |
| 4a | BookRunner+卷摘要 | ~250行 | 同原方案 |
| 4b | metacog+resume（后置） | ~250行 | 同原方案 |
| Embedding | 重定位 | ~30行 | -70行（从100行降到30行） |
| **总计** | | **~1830行** | |

**实际工作量（含测试+调试+prompt调优）预计3500-4500行。**

---

## P0/P1修订项（继承原方案，全部保留）

所有原方案的P0必改项（5个）和P1必改项（6个）在本方案中全部保留，具体见原方案末尾。核心：
- P0-1：角色回写包try/except + 角色不存在跳过
- P0-2：阶段4拆4a/4b，resume先于interrupt
- P0-3：repo方法先实现单测
- P0-4：串行依赖链，严格按序
- P0-5：schema与handler原子提交
- P1-1：snapshot用EntityAppearance替代last_active_chapter
- P1-2：validator签名兼容
- P1-3：8000预算优先级明确
- P1-4：章末钩改LLM判断
- P1-5：generate_volume_summary传llm_client
- P1-6：archival双路径不删commit全文索引

---

## 验证策略（防"测试绿灯但跑不通"）

每阶段做完必须：
1. **真跑LLM 3-5章**（不用mock）
2. **人读验收**（不只看表有没有数据，读生成的正文判断质量）
3. **回写覆盖率探针**（统计6表实际写入行数，不达标停下来调prompt）
4. **快照保真度校验**（drift_score < 阈值）

**阶段验证清单**：
- [ ] 阶段0：Outline约束字段有数据 + summarize日志显示校验模式（非抽取模式）
- [ ] 阶段1：truth_events有character_state_change事件 + 角色位置变更走applier
- [ ] 阶段2：core memory字数稳定 + 第20章触发全量重摘要 + drift_score<3
- [ ] 阶段3：前3章phase=opening + 断层检测工作 + DedupScanner检测到重复
- [ ] 阶段4a：卷摘要存库 + 卷二注入卷一摘要 + 异常不break
- [ ] 阶段4b：metacog interrupt + chapter-resume恢复

---

## 最关键的三件事（不补百万字就是空谈）

1. **数据流掉头**（阶段0）——不补，summarize是12字段抽取怪兽，不可靠
2. **快照保真度校验**（阶段2.5）——不补，第200章快照与正文渐行渐远，metacog还报正常
3. **爽点新鲜度检测**（阶段3.5 DedupScanner）——不补，500章按档位排打脸=必然腻

---

## 明确不做的事

- ❌ 不做向量检索历史片段注入热路径（archival移出core.py）
- ❌ 不做情感引擎state machine（情感由处境emergent）
- ❌ 不做每角色独立agent（只核心角色建模）
- ❌ 不做审美判断硬门禁（降级为软信号+人审）
- ❌ 不推翻现有代码（渐进改造，保留132测试基线）
- ❌ 不做读者反馈闭环（v2功能，需接平台API）
- ❌ 不做日更/连载调度器（产品形态选择，非技术问题）
