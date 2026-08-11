# 蒸馏体系重构计划：维度 ↔ Agent 对齐 + Skill 按 Agent 分发注入

## 一、要解决的问题

1. **生成质量**：35 个 Agent 分工明确（写对话的、写动作的、写内心的、构建世界观的…），但蒸馏 Skill 注入是"一刀切"——所有 writer 拿到同一份 Skill。写对话的 agent 看不到对话精华，写动作的看不到动作精华。
2. **上下文爆炸**：9 本书 × 维度碎片 = 上千 Skill。规则型全量注入会撑爆上下文。
3. **结构混乱**：二级浓缩是"全书 1 个总纲"，没有按维度归类，Agent 不知道该看哪份。

## 二、项目现状（已深度核实）

### 2.1 Agent 系统（35 个，agents.json）
- 正文写作 8 个：novel-writer / single-writer / storyboard-integrator / dialogue-writer / action-writer / internal-writer / description-writer / transition-writer
- 大纲规划 7 个：volume-outliner / director / outliner / story-planner / settler / intent-distributor / style-profiler
- 世界观构建 6 个：worldbuilder-corelaws / spacetime / society / historyculture / existence / information
- 角色 5 个：character-skeleton / belief / deep / voice / maintainer
- 审校 5 个：self-critic / voice-critic / palette-critic / chapter-observer / arbiter
- 润色 2 个：polisher / professional-polisher
- 世界状态 2 个：observer / world-context-trimmer

### 2.2 Skill 注入现状（routes_skills.py + loader.py）
- **规则型（rule）**：全量注入（蒸馏总纲/融合总纲/内置/用户自建）
- **素材库型（material）**：按上下文检索（蒸馏碎片/corpus/拆书，top-6 条、每条 2000 字）
- 注入路径 3 条：①orchestrator 正式写作页（with_context）②交互式创作（with_context）③26-Agent 工作流（只给 writer 角色全量注入）
- **agent 定义有 `visible_skill_group_ids`/`visible_rule_group_ids` 字段，但全项目无代码消费**（35 个 agent 全为空）→ 这是预留的按 agent 分发机制，正好启用

### 2.3 蒸馏现状（distillation/engine.py）
- 15 个维度：1-7 文笔技法 / 8-12 网文实战 / 13-15 人味指纹（节奏句长、禁词表、密度）
- 碎片 Skill → material；二级/三级浓缩总纲 → rule
- 二级浓缩：全书 1 个总纲（不分组）

## 三、方案设计

### 3.1 蒸馏维度 ↔ Agent 映射表（15 → 19，保留旧编号兼容老数据）

**编号策略**：1-15 与现有维度完全一致（已蒸馏的书 round_num 语义不变），新增 16-19 四个专项写手维度。

| # | 维度 | 归属 Agent | 蒸馏目标（要拆出什么） | 模板类型 |
|---|---|---|---|---|
| 1 | 写作风格特征 | style-profiler、polisher | 叙事节奏、对话风格、描写习惯、情感表达方式的整体文风 | 通用 |
| 2 | 语言特征 | writer、single-writer | 用词偏好、句式结构、修辞手法、标点习惯 | 通用 |
| 3 | 故事结构特征 | story-planner、writer | 情节推进方式、冲突设计、伏笔埋设、节奏控制、骨架套路 | 通用 |
| 4 | 叙事引擎 | story-planner | 驱动翻页的核心动力：悬念钩子、信息差、期待感、爽点释放节奏 | 通用 |
| 5 | 信息控制 | director | 作者何时给读者什么信息：悬念吊法、伏笔深度、视角信息差、反转铺垫 | 通用 |
| 6 | 人物塑造技法 | character-skeleton/belief/deep | 角色出场、性格展现、对话辨识度、成长弧线、群像管理 | 通用 |
| 7 | 情感算法 | palette-critic | 情绪曲线、共情锚点、情感落差、读者情绪引导路径 | 通用 |
| 8 | 世界观与设定 | worldbuilder-corelaws/spacetime/society/historyculture/existence/information | 力量体系/金手指规则、舞台规则与禁忌、时代背景质感、设定投放方式 | 世界观模板 |
| 9 | 爽点设计 | writer | 爽点类型、铺垫→释放模式、爽点密度与间隔 | 爽点模板 |
| 10 | 章节钩子 | director | 断章技巧、悬念抛出方式、金句钩子、开篇抓人 | 钩子模板 |
| 11 | 对话与台词 | dialogue-writer、character-voice | 对话占比、角色语言辨识度、对话推动剧情、潜台词 | 对话模板 |
| 12 | 反派与配角 | character-maintainer | 反派动机自洽与不降智、配角功能、工具人规避、关系张力 | 通用 |
| 13 | 节奏与句长指纹 | self-critic | 句长分布、对话占比、段落长短变化（检测器信号） | 指纹模板（已有） |
| 14 | 禁词与套路词表 | polisher、professional-polisher | 原书回避的 AI 高频词与套路句式 | 指纹模板（已有） |
| 15 | 密度目标 | self-critic | 形容词/破折号/连接词/重复词密度控制 | 指纹模板（已有） |
| 16 | 动作与打斗 | **action-writer** | 打斗节奏、动作描写粒度、力量感、紧张感营造 | **动作模板（新）** |
| 17 | 内心与心理 | **internal-writer** | 内心独白风格、情绪层次、内心冲突构建、心理信息投放 | **内心模板（新）** |
| 18 | 环境与描写 | **description-writer** | 氛围营造、感官细节、环境信息借景叙事、描写克制度 | **描写模板（新）** |
| 19 | 过渡与节奏 | **transition-writer**、storyboard-integrator | 场景间过渡方式、衔接技巧、节奏换挡、连续性保持 | **过渡模板（新）** |

### 3.1.1 模板体系（每个维度有确定的输出结构）

**① 通用模板**（维度 1-7、9、12）：沿用现有 v2 结构，所有字段必须从原文实际观察：
```json
{ "name": "≤12字", "description": "一句话",
  "signature_moves": [{"pattern": "可复现手法", "evidence": "原文例证", "apply": "怎么落地", "exception": "何时可违背"}],
  "hard_rules": ["≤3条红线"], "soft_guidelines": [{"rule":"倾向","why":"为什么","flexibility":"例外"}],
  "anti_patterns": ["禁止写法"], "tags": ["2-5个"] }
```

**② 指纹模板**（维度 13-15）：现有专用模板，产出可量化统计信号（rhythm_profile/ban_words/density_targets）。

**③ 钩子模板**（维度 10）：在通用结构上补充：
```json
{ "hook_types": ["断章钩子类型（悬念/危机/转折/金句）", "..."],
  "hook_position": "钩子通常出现的位置与频率",
  "cliffhanger_style": "断章的具体写法（停在动作/对话/信息揭示的哪一刻）",
  "opening_hooks": ["开篇 3 秒抓人的手法"], ...通用字段 }
```

**④ 爽点模板**（维度 9）：补充：
```json
{ "satisfaction_types": ["爽点类型（打脸/碾压/逆袭/收获/智谋）", "..."],
  "setup_release": "铺垫→释放的具体模式（压抑多久、如何引爆）",
  "density": "爽点密度与间隔（每千字几个、间隔多远）", ...通用字段 }
```

**⑤ 对话模板**（维度 11）：补充：
```json
{ "dialogue_ratio": "对话占比", "voice_markers": ["角色语言辨识标志（口头禅/句式/用词）"],
  "subtext_style": "潜台词写法（言外之意如何暗示）",
  "dialogue_action": "对话中如何夹杂动作/神态推进", ...通用字段 }
```

**⑥ 世界观模板**（维度 8）：补充：
```json
{ "power_system": "力量体系/金手指规则（获取/升级/代价/边界）",
  "setting_reveal": "设定投放方式（借对话/行动/环境自然呈现，不写说明书）",
  "terminology": ["本书专属术语与用法"], "consistency": "一致性维护规则", ...通用字段 }
```

**⑦ 动作模板**（维度 16，新增）：
```json
{ "fight_rhythm": "打斗段落节奏（起手→交锋→转折→收束的节拍）",
  "action_beats": "动作描写粒度（招式/身体细节/环境交互的具体写法）",
  "power_feel": "力量感/压迫感的表达手法",
  "tension_techniques": "打斗中紧张感与胜负悬念的营造", ...通用字段 }
```

**⑧ 内心模板**（维度 17，新增）：
```json
{ "inner_voice": "内心独白风格（直接/隐喻/意识流）",
  "emotion_layers": "情绪层次（表层反应→真实动机的递进）",
  "conflict_build": "内心冲突的构建方式（纠结/抉择/成长）",
  "reveal_pacing": "心理信息的投放节奏", ...通用字段 }
```

**⑨ 描写模板**（维度 18，新增）：
```json
{ "atmosphere": "氛围营造手法（光线/声音/气味/温度）",
  "sensory_detail": "感官细节运用", "setting_narrative": "环境如何借景叙事（景随情变）",
  "restraint": "描写克制度（不堆砌、留白）", ...通用字段 }
```

**⑩ 过渡模板**（维度 19，新增）：
```json
{ "transition_types": ["场景过渡方式（时间跳转/地点切换/情绪衔接/黑场）"],
  "scene_link": "场景衔接技巧（承上启下/并行对照）",
  "rhythm_shift": "节奏换挡（紧张↔舒缓的切换点）",
  "continuity": "时间线/视角/空间连续性维护", ...通用字段 }
```

### 3.2 Skill 打标签（归属 Agent）

每个蒸馏 Skill 写入 `agent_roles: ["novel-dialogue-writer", ...]`：
- 碎片 Skill：按维度映射
- 二级总纲：按维度分组，天然对应
- 三级说明书：`["*"]` 全部 agent

### 3.3 二级浓缩改为"按维度分组"（19 个）

当前：全部碎片 → 1 个 level2 总纲。
改为：全部碎片 → 按维度分组 → **每个维度 1 个 level2 总纲**（19 个）→ 再整体浓缩成 **1 个 level3 说明书**（含"维度索引"：告诉模型每个维度对应写作哪个环节）。

### 3.4 注入机制调整（防爆炸关键）

**启用 agent 的 `visible_skill_group_ids`**（35 个 agent 目前全空）：

| Skill 层 | 注入策略 | 实现 |
|---|---|---|
| 三级说明书 | 全局注入（所有 agent 必看） | 现有 rule 全量注入 |
| 二级维度总纲 | **按 agent 过滤**：每个 agent 只注入自己 `visible_skill_group_ids` 对应维度的总纲 | 新增：注入时按 agent 的 visible_skill_group_ids 过滤 rule 型 skill |
| 一级碎片 | 素材库按需检索（现有机制不动） | RAG |

- `visible_skill_group_ids` 填法：每个 agent 填自己对应维度的组 id（如 dialogue-writer → ["dim_dialogue"]）
- 注入函数签名改为 `load_enabled_skills_for_injection_with_context(context, agent_type=None)`，有 agent_type 时按 visible_skill_group_ids 过滤

**注入量测算**：9 本书时，对话写手每次生成 = 9 本三级说明书 + 9 份对话维度二级总纲 + 检索碎片，**可控**。

### 3.5 三级说明书内容升级

三级浓缩额外生成"维度索引"：本书有哪些维度总纲（二级）、每个维度对应写作哪个环节、何时该翻哪份二级/一级。

### 3.6 规模扩展：项目 ↔ 参考书关联（几十本书时的关键闸门）

**问题**：后续可能蒸馏 10-50 本书。即使按 agent 过滤（每 agent 只看自己维度），50 本书 × 本维度总纲 = 50 份 + 50 份说明书，仍会撑爆上下文。

**方案**：给项目加"参考书单"设置——写某本书时，选择参考哪些已蒸馏的书：

```
项目设置 → 参考书单（如选《诡秘》《大王饶命》《庆余年》3 本）
→ 注入范围 = 选中的书 ∩ 当前 agent 的维度
```

| Skill 层 | 注入范围（含按书选择） |
|---|---|
| 三级说明书 | 只注入**选中书**的说明书（如 3 本 → 3 份） |
| 二级维度总纲 | 只注入**选中书 × 当前 agent 维度**（如 3 本 × 1 维度 = 3 份） |
| 一级碎片 | RAG 检索（可限定在选中书内，默认全局） |

**注入量测算**（写新书选 3 本参考）：
- 对话写手 = 3 份说明书 + 3 份对话总纲 + 检索碎片 ≈ **几千字符，完全可控**
- 即使 50 本书蒸馏好了，只要不选进书单，就不会注入

**数据落地**：
- 蒸馏作品表（distill_works）已有 id/title——作为"可选书单"
- 项目加字段 `style_books`（参考书单，存 distill work_id 列表），前端项目设置页可选
- 注入时：说明书/总纲文件名 `distill_w{id}_level2` 可反查 work_id → 判断是否在书单内

## 四、实施步骤

| 步骤 | 内容 | 文件 |
|---|---|---|
| 1 | 维度定义 15→19（加 agent 归属字段） | distillation/engine.py、前端 DistillationPage.tsx |
| 2 | 蒸馏产物写 `agent_roles` 标签 | engine.py、store.py |
| 3 | 二级浓缩按维度分组（19 个总纲） | engine.py |
| 4 | 三级浓缩加"维度索引" | engine.py |
| 5 | 项目加"参考书单"字段 + 前端选择 UI | bible/models.py、routes_bible.py、项目设置页 |
| 6 | 注入按 agent 过滤 + 按参考书单过滤（消费 visible_skill_group_ids） | routes_skills.py、workflows/loader.py、orchestrator/nodes.py、routes_generation.py |
| 7 | agents.json 填 35 个 agent 的 visible_skill_group_ids | workflows/resources/agents.json |
| 8 | 前端蒸馏页维度 UI（显示 agent 归属） | DistillationPage.tsx |
| 9 | 老数据兼容（无 agent_roles 的按名称推断维度→agent） | routes_skills.py |
| 10 | 验证：小书全流程 + 注入量测试（含多书场景） | 手工 |

## 五、验证

1. 一本书跑 3 级：碎片（19×片段）+ 二级（19 个维度总纲）+ 三级（1 本说明书+索引）
2. 模拟生成：某 agent 的 prompt 只含"三级 + 本维度二级 + 命中碎片"，量可控
3. 老数据不报错、可继续用

## 六、待确认

1. **19 维度 ↔ agent 映射表**（第 3.1 节）OK？
2. **二级 19 个总纲 + 三级 1 本**结构确认
3. 世界观维度（18）是否拆成 6 个子维度分别对应 6 个 worldbuilder？（推荐拆，与 build 工作流 6 维对齐）

## 七、实施记录（2026-08-12）

### 已落地

| 步骤 | 内容 | 文件 | 状态 |
|---|---|---|---|
| 1 | 维度 15→19（新增动作/内心/描写/过渡），含 DIMENSION_AGENTS 映射 | engine.py、DistillationPage.tsx | ✅ |
| 2 | 蒸馏产物写 `agent_roles` 标签（二级总纲=rule 按维度打；三级说明书全量；碎片=material 按内容检索，不打） | engine.py | ✅ |
| 3 | 二级浓缩按维度分组（每维度 1 个总纲 `_d{dim}` 后缀），三级单产 1 个说明书 | engine.py | ✅ |
| 4 | 三级说明书加"维度索引"（dimension_index 字段 + 渲染） | engine.py | ✅ |
| 6a | 注入按 agent 过滤（`load_enabled_skills_for_injection*` 加 `agent_type` 参数 + `_matches_agent`） | routes_skills.py | ✅ |
| 6b | 工作流 `_exec_agent` 注入范围：writer 系 + 蒸馏维度覆盖的 agent，按 agent_type 定向注入 | workflows/loader.py | ✅ |
| 8 | 前端蒸馏页维度 UI 15→19 | DistillationPage.tsx | ✅ |

### 与方案偏差说明

**3.4 注入过滤改为 skill 侧 `agent_roles` 标签，未启用 agent 侧 `visible_skill_group_ids`**：
- 原因：35 个 agent 逐个填 visible 列表改动大、易错；skill 侧打标签与蒸馏产出一条龙，注入侧按当前 agent_type 匹配即可，功能等价
- 过滤规则：`agent_roles` 为空/缺失 → 通用 skill 照常注入（内置/自建/老数据全部兼容）；非空且不含当前 agent → 跳过
- 向后兼容：2167 个旧蒸馏 skill 无 `agent_roles` 字段 → 按通用处理，注入行为与旧版一致

**注入范围**：`role=="writer"` 的 8 个写手 + `DIMENSION_AGENTS` 覆盖的 agent（世界观 6 / 角色 5 / 大纲 / 润色 / 专项写手等）参与定向注入；未覆盖 agent（observer/settler/审校系等）保持原行为（不注入）。注入文本按 agent_type 缓存，不重复加载。

### 已验证

1. `py_compile` 4 个改动文件通过；`tsc --noEmit` 前端通过；GetDiagnostics 无报错
2. 单元验证（临时脚本）：
   - `_matches_agent` 六种规则分支全部符合预期
   - 注入集成：worldbuilder 拿到自己维度总纲+通用；writer 不拿世界观维度；agent_type=None 全放行（兼容）
   - 浓缩分组：二级按 round_num 分组产出 3 个总纲（`_d1/_d9/_d16`）；三级单产 1 个说明书
3. 后端重启加载新代码，API `/api/distillation/works` 正常；遗留 3 本 distilling 残留任务已 cancel
4. 测试产生的污染文件（skills 目录 distill_w3_level*）已全部清理

### 未实施（后续轮次）

- 步骤 5：项目"参考书单"字段 + 前端选择 UI（用户确认上下文 100 万够用，暂缓）
- 步骤 7：agents.json 填 visible_skill_group_ids（本次用 skill 侧标签替代）
- orchestrator/nodes.py 与 routes_generation.py 的注入路径：保留无 agent_type 的兼容行为（章节级公共注入不区分 agent）

## 八、完成报告

详见同目录 [蒸馏-Agent对齐-实施报告.md](./蒸馏-Agent对齐-实施报告.md)（完整版含验证结果与使用说明）。
