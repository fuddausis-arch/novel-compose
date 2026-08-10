# NovelCompose（织谱）· 多 Agent AI 小说创作平台

> 多 Agent 协作的 AI 长篇小说创作平台：你负责想法和判断，AI 负责规划和写作，**写、审、改分离**，支持浏览器、Electron 桌面和安卓手机。

**开源协议：GNU AGPL v3**（详见 [LICENSE](LICENSE)）。本仓库不包含任何 API Key 或个人数据；所有模型密钥通过 `.env` 配置（已被 .gitignore 忽略，永不进入仓库）。

---

## 一、这是什么

NovelCompose 是一个完整的 AI 小说创作系统，后端（FastAPI）负责全部 AI 编排与数据管理，前端（React）提供可视化的创作界面。

它和"直接让大模型写小说"的区别：

- **多 Agent 分工**：规划、写正文、审校、润色、提炼设定由不同角色协作完成，写和审使用不同模型，避免"自己写自己审"。
- **设定库驱动**：角色、势力、世界观、伏笔、大纲都结构化存储，正文生成时自动带上，保证前后一致、不写崩设定。
- **人审检查点**：每一章生成后先过三视角审校，再由你确认通过/驳回，**质量大权始终在你手里**。
- **持续学习**：可以从参考作品"蒸馏"出写作风格技能（skill），越用越贴合你想要的味道。

---

## 二、核心功能

| 功能 | 说明 |
|---|---|
| **双模式对话页** | 一个页面两种模式：**对话模式**（与 AI 闲聊/问设定）+ **创作模式**（流式写正文），历史各自独立 |
| **交互式创作** | 像聊天一样创作：日常对话、随时要求"创作第几章"、"下一章"；支持**抽卡**——一次生成多个候选版本供你挑选 |
| **正式章节流水线** | 卷纲 → 细纲 → 章纲 → 正文 → 三视角审校 → 人审确认 → 润色 → 提交设定库（12 节点 LangGraph，崩溃可续跑） |
| **三视角审校** | 读者 / 专业 / 编辑三个视角独立打分，输出问题清单；不通过时触发 AI 对抗性讨论 |
| **人审检查点** | 审校通过后暂停等你确认：**通过**或**驳回重写**（写作页）；创作模式还支持**再润色**。驳回时你的意见作为最高优先级注入重写 |
| **多重质量防线** | 写审分离 + AI 味句级检测 + 7 道去 AI 味后处理 + 跨章语义去重 + 幻觉过滤 + 命名权威 + 限频词等确定性校验 |
| **设定库** | 角色 / 势力 / 怪物 / 副本 / 物品 / 关系 / 世界观 / 伏笔 / 梗 / 红线 / 事件时间线，全结构化管理 |
| **大纲系统** | 卷 → 细纲 → 章 三级大纲，支持 AI 生成、人工编辑、内容不足时 AI 自动扩充剧情 |
| **内容图谱** | 人物关系 / 势力关系 / 伏笔网络 / 章节脉络 / 世界地图 五类图谱，点节点看详情，支持自动布局与编辑 |
| **圆桌会议** | 多个 AI 角色围坐讨论剧情走向（席位可配、可暂停/恢复/插话），生成会议纪要与结构化结论供你采纳 |
| **自定义工作流** | 可视化编排生成流程（节点拖拽连线：agent / 脚本 / 网关 / 起止），满足非标准创作需求 |
| **风格蒸馏** | 导入参考作品，AI 按 **7 个维度**（风格/语言/结构/叙事引擎/信息控制/人物塑造/情感算法）多轮蒸馏出 skill |
| **拆书生成技能** | 上传一本小说，逐章提炼技法生成 book-to-skill，写对应场景时自动按需注入 |
| **Skills 技能库** | 可复用写作技能，内置 6 个 + 自建/蒸馏/拆书；支持**语义搜索**（关键词优先 + 向量补漏），写作时自动注入 |
| **记忆系统** | 每章常驻上下文 + 向量语义检索（Chroma）+ 全文精确回溯 + 分层摘要树，长篇小说不忘前情 |
| **参考文件与语料** | 上传写作参考自动注入；内置 11 个写作规则 CSV（限频词/桥段/爽点节奏/命名规则…）+ 真实小说章末钩子语料 |
| **多端运行** | 浏览器（开发/局域网）、Electron 桌面安装包、安卓（Capacitor 壳 + 竖屏适配） |

---

## 三、快速开始

### 环境要求

- Python 3.11+（后端）
- Node.js 18+（前端）

### 第 1 步：安装后端依赖

```bash
python -m venv .venv
# Windows: .venv\Scripts\activate    macOS/Linux: source .venv/bin/activate
pip install -r requirements.txt
```

> 如需本地向量模型回退，另装 `pip install sentence-transformers`（可选）。

### 第 2 步：安装前端依赖

```bash
cd frontend
npm install
cd ..
```

### 第 3 步：配置 API Key

1. 复制配置模板：`cp config.yaml.example config.yaml`（Windows：`copy config.yaml.example config.yaml`）
2. 在项目根目录创建 `.env` 文件，填入你的密钥（`.env` 永不进 git）：

```bash
DEEPSEEK_API_KEY=sk-你的DeepSeek密钥
ARK_API_KEY=ark-你的火山方舟密钥
ARK_EMBEDDING_API_KEY=ark-你的方舟Embedding密钥
```

- DeepSeek 申请：https://platform.deepseek.com/api_keys
- 火山方舟申请：https://console.volcengine.com/ark
- 不配 `ARK_EMBEDDING_API_KEY` 也能用（语义检索自动降级为关键词搜索），配了效果更好

### 第 4 步：启动（开发模式）

```bash
# 终端 1：后端
python -m uvicorn novel_agent.api.app:app --host 0.0.0.0 --port 8000 --reload

# 终端 2：前端（带热更新）
cd frontend && npm run dev
```

浏览器访问 **http://localhost:5173** 即可使用。

> 小贴士：手机和电脑连同一个 Wi-Fi，手机浏览器访问 `http://电脑局域网IP:8000`（后端已挂载前端页面）也能用；`--host 0.0.0.0` 就是为此开启的。

### 其他运行方式

| 方式 | 命令 | 说明 |
|---|---|---|
| 打包桌面安装包 | `build_release.bat` | PyInstaller 打包后端 + electron-builder 生成 `release5/` 下的 `NovelCompose Setup *.exe` |
| Electron 桌面开发 | `cd frontend && npm run electron:dev` | 桌面窗口开发模式（需先起后端 8000 与前端 5173） |
| 安卓打包 | `cd frontend && npm run app:build` | 构建前端 + 同步 Capacitor 壳，用 Android Studio 打开 `frontend/android` 生成 APK |
| 命令行 | `novel-agent init` / `generate` / `plan` / `resume` / `serve` | 不打开界面也能建项目、生成单章、跑卷级规划；`serve` 直接起服务 |

---

## 四、使用指南（从建项目到写完一本书）

### 1. 创建项目
打开首页 → 左上角「选择作品」→ 新建项目 → 填标题 / 题材 / 简介 / 风格。没有项目时首页会引导你创建。题材可选模板（内置 15 个题材模板）。

### 2. 搭框架
- **规划页**：让 AI 生成卷级规划（可选，长篇小说建议做）
- **大纲页**：卷大纲 → 每卷细纲 → 每章章纲。大纲质量决定正文质量，建议每级都人工看一眼、不满意就重新生成

### 3. 开始写
- **对话页（默认首页）**：切到创作模式，说"创作第一章"或"下一章"，AI 流式写正文并自动走审校。要对比多个写法？开**抽卡**一次生成几个候选。审校后弹窗出现：**通过 / 驳回重写 / 再润色**。
- **写作台**：人工精修章节正文（多标签、2 秒自动保存），手动触发生成、保存、删除。

### 4. 让 AI 越写越合口味
- **设置 → 蒸馏技能**：导入参考作品提炼风格 skill；上传一本书做**拆书**生成技法技能；还可把多个 skill **融合**成"九合一"。
- 生成时 skill 自动注入，相关技法按需加载（语义搜索），不浪费上下文。

### 5. 管理设定
在**资产页**维护 9 类设定（角色/世界设定/伏笔/势力/怪物/副本/红线/梗/导入）；**百科页**五类实体卡片全局浏览；**图谱页**看关系网；**时间线页**回看事件流。正文提交时 AI 会自动把新事实写回设定库。

### 6. 看结果
**仪表盘**看进度、**统计页**看字数与一致性、**摘要页**看章节摘要、**导出页**导出全书正文。

---

## 五、页面导览

### 项目内页面

| 路径 | 页面 | 作用 |
|---|---|---|
| `/chat` | 对话（默认页） | 对话模式 + 创作模式，流式写正文、抽卡、人审 |
| `/dashboard` | 仪表盘 | 项目信息编辑 + 进度统计 + 继续写作 |
| `/planning` | 规划 | 卷级规划生成 |
| `/outlines` | 大纲 | 卷 / 细纲 / 章三级大纲 |
| `/write` | 写作台 | 章节精修（多标签、自动保存）、流水线生成、人审 |
| `/graph` | 图谱 | 五类内容图谱可视化（桌面三栏，手机全屏 + 底部工具栏） |
| `/roundtable` | 圆桌 | 多 AI 角色剧情讨论 |
| `/workflow` | 工作流 | 自定义生成流程可视化编排 |
| `/assets` | 资产 | 角色/世界设定/伏笔/势力/怪物/副本/红线/梗管理/导入文件夹 |
| `/import` · `/export` | 导入 / 导出 | 解析文本/文件/JSON/AI 扫描导入；导出全书 |
| `/summaries` | 摘要 | 章节摘要列表 |
| `/references` | 参考文件 | 上传写作参考，生成时自动注入 |
| `/stats` | 统计 | 一致性看板（章节/字数/伏笔/冲突） |
| `/timeline` | 时间线 | 按章节组织的多泳道事件时间线 |
| `/encyclopedia` | 百科 | 五类实体卡片浏览 + 出场场景索引 |

### 设置页（全局，左侧 12 项导航）

| 页面 | 作用 |
|---|---|
| 概览 | 全部管理模块卡片入口 |
| 模型 | 模型供应商管理（新增/编辑/删除 + 模型发现） |
| Agent 定义 | Agent 角色定义 CRUD + 可见性控制 |
| Prompt 编排 | 提示词 Sections / Agent 定义 / 工具列表 / 用户注入，全部可编辑 |
| Skills | 技能库管理（创建/编辑/启停/自动注入/搜索） |
| Rules | 行为规则管理（CRUD/启停/冲突检测） |
| 插件 | 插件安装 / 启停 / 源管理 |
| 定时任务 | 定时触发任务 |
| 压缩监控 | 记忆压缩统计 + 历史日志 |
| 工作区 | 文件树浏览（会话树/附件/文件） |
| 蒸馏技能 | 作品导入 → 7 维蒸馏 → Skill 管理 → 融合 → 盲评对比 |
| 用户注入 | 全局/按项目的自定义指令注入 |

> 手机竖屏（<768px）下：顶栏变为抽屉菜单收进全部入口；资产页导航变横向滑动条；图谱页画布全屏 + 底部工具栏、编辑面板为底部抽屉。整体有 **3 套主题**（精致浅色 / 温暖纸墨 / 深色 AI）。

---

## 六、项目结构

```
novel-compose/
├── novel_agent/              # 后端（FastAPI，29 个路由模块）
│   ├── api/                  # HTTP 路由（projects/chapters/generation/bible/skills/distillation…）
│   ├── audit/                # 质量体系：三视角审校/AI味检测/7Gate去AI味/去重/幻觉过滤/命名权威/确定性校验
│   ├── bible/                # 设定库 ORM（角色/伏笔/大纲/世界观/事件流）+ SQLite 仓储
│   ├── chat/                 # 交互 Agent（tool-calling ReAct 循环，真流式 + 压缩 + 子 Agent）
│   ├── orchestrator/         # 章节生成流水线（LangGraph 12 节点 + 断点续跑 + 取消令牌 + 跨卷编排）
│   ├── planning/             # 卷级规划（Plan→Design→Review→Apply + 人审）
│   ├── distillation/         # 写作风格蒸馏（7 维多轮蒸馏 → skill → 融合 → 盲评）
│   ├── skills/               # 拆书生成技能（book-to-skill，只存摘要不存原文）
│   ├── workflows/            # 7 条内置工作流（bishu-novel 移植，83 节点）+ nvl 脚本库
│   ├── roundtable/           # 圆桌会议引擎（主持人决策 + 共享记忆 + 用户干预 + SSE）
│   ├── memory/               # 记忆系统（core 常驻 / archival 向量 / recall 回溯 / summary_tree 分层）
│   ├── llm/                  # LLM 客户端（OpenAI 兼容，流式 + 重试 + token 账本）
│   ├── protocol/             # Delta 事件协议（agent 产出 → 校验 → 不可变应用 → 事件流）
│   ├── references/           # 写作语料（11 个规则 CSV + 禁用词表 + 章末钩子语料）
│   ├── geo/                  # 地图布局引擎
│   ├── defaults/             # 内置技能 / 题材模板 / 提示词 / 风格样本
│   ├── state_common.py       # 全局状态常量（各域状态机集中定义）
│   ├── config.py             # 配置加载（config.yaml + .env 占位符展开 + env 覆盖）
│   └── cli.py                # 命令行入口（init / generate / plan / resume / serve）
├── frontend/                 # 前端（React 19 + TypeScript + Vite + Tailwind）
│   ├── src/
│   │   ├── pages/            # 页面（项目内 + settings/ 设置页）
│   │   ├── views/            # 视图层组件（百科/资产/大纲/时间线/仪表盘…）
│   │   ├── components/       # 共享组件（ui 22 个基础件 / entity / chat / write…）
│   │   ├── df/               # 图谱/圆桌/工作流页面及组件
│   │   ├── store/            # Zustand 状态（pipeline/interactive/chapter/bible/ops/project）
│   │   ├── hooks/            # 自定义 Hooks（useGeneration/useChat/useConfirmDialog/useMediaQuery…）
│   │   ├── api.ts            # 后端 API 封装（含 SSE 流式）
│   │   └── routes.tsx        # 路由表
│   ├── android/              # Capacitor 8 安卓壳
│   ├── electron/             # Electron 桌面壳（自动拉起后端、标题栏控制）
│   └── e2e/                  # Playwright 端到端测试
├── config.yaml.example       # 配置模板
├── build_release.bat         # 一键打包桌面安装包
├── docs/                     # 设计文档 / 计划书 / 测试报告
└── tests/                    # 后端测试（pytest）
```

---

## 七、技术架构

### 章节生成流水线（12 节点）

```
world_engine(世界观) → assemble(组装上下文) → context_trimmer(裁剪)
→ analyze_style(风格分析) → write(正文) → audit(三视角审校)
→ [达标] human_review(人审检查点) → style_refine(润色) → save_text(提交设定库)
  → summarize(摘要) → post_hoc(事实后验)
→ [不达标 ≤3 次] rewrite → audit     [超过 3 次] 结束
```

- 写审分离：Writer 与 Auditor 使用**不同模型**
- 反馈循环 ≤3 次；人审后验 critical 级事实冲突 ≤3 次返工润色
- 非关键节点失败自动重试跳过，关键节点失败终止；全程可取消，断点可续跑

### 数据存储

| 数据 | 位置 | 说明 |
|---|---|---|
| 设定库 | `project_data/bible.db` | SQLite（WAL）：角色/势力/伏笔/大纲/世界观/事件流… |
| 章节生成断点 | `project_data/projects/{id}/checkpoints.db` | LangGraph checkpoint，崩溃可续跑 |
| 卷级规划断点 | `project_data/volume_checkpoints.db` | 规划人审断点 |
| 章节正文 | `project_data/projects/{id}/chapters/` | Markdown 文件 |
| Skills | `project_data/skills/*.json` | 技能库（含语义索引） |
| 蒸馏数据 | `project_data/distillation.db` | 作品/片段/轮次/Skill/融合方案 |
| 向量库 | `project_data/chroma/` | 记忆检索 + skill 语义搜索 + 题材语料 RAG |
| 参考语料 | `novel_agent/references/csv/` | 11 个写作规则 CSV（只读） |
| 配置与密钥 | `config.yaml` + `.env` | 模型与密钥 |

### 模型分配（在设置 → 模型 / Agent 定义中可调）

| 角色 | 默认模型 | 职责 |
|---|---|---|
| writer / polisher | glm-5.2（火山方舟） | 正文生成 / 润色改写 |
| auditor / debater | deepseek-v4-flash | 三视角审校 / 对抗讨论（写审分离） |
| planner / architect / outliner | deepseek-v4-flash | 规划与大纲 |
| summarizer | deepseek-v4-flash | 摘要 |
| embedding | doubao-embedding-vision | 向量检索（可降级） |

---

## 八、配置说明

`config.yaml` 主要段落：

- `llm`：主模型（base_url / api_key / model / max_tokens / timeout…）
- `auditor_llm`：审校独立模型（写审分离；留空回退主模型）
- `agent_llm`：各 Agent 的模型分配（api_key 留空自动回退主模型 key）
- `embedding`：向量模型配置（方舟 doubao-embedding-vision）
- `project_data_dir`：项目数据目录（可自定义；打包版默认 `%APPDATA%\NovelCompose\project_data`）
- `enable_genre_rag`：题材向量语料 RAG 开关（末日/克苏鲁/异能等从语料检索真实片段）
- `allow_auto_expand_chapter`：章纲内容不足时允许 AI 自动扩充剧情

> API Key 只放 `.env`，`config.yaml` 用 `${VAR}` 占位符引用，避免密钥进 git。还支持 `NOVEL_*` 环境变量覆盖。

---

## 九、测试与质量保障

```bash
# 后端单元/集成测试
python -m pytest tests/ -q

# 前端类型检查
cd frontend && npx tsc --noEmit

# 前端端到端测试（需前后端已启动）
cd frontend && npx playwright test
```

质量机制：写审分离（不同模型）→ 三视角审校 + 对抗讨论 → AI 味句级检测 → 7 Gate 去 AI 味后处理 → 跨章语义去重（向量）→ 幻觉过滤（防图谱污染）→ 命名权威（防角色写崩）→ 确定性校验（字数/限频词/句长/对话占比，能用代码查的不交给 LLM）→ 人审检查点 → 技能按需注入。

---

## 十、常见问题（FAQ）

**Q：页面打不开？**
A：确认后端 8000 与前端 5173 都已启动；页面一直转圈时看后端日志是否有报错。

**Q：生成很慢或失败？**
A：多为模型服务限流/超时。检查 `.env` 密钥是否有效、`config.yaml` 模型名是否正确；长文本生成可达数分钟，请耐心等流式输出（界面有停止按钮可中断）。

**Q：skill 语义搜索没效果？**
A：语义搜索需要 `ARK_EMBEDDING_API_KEY`（方舟 doubao-embedding）。未配置时自动降级为关键词搜索，不影响使用。

**Q：数据存在哪？**
A：由 `config.yaml` 的 `project_data_dir` 决定（打包版默认 `%APPDATA%\NovelCompose\project_data`）。整个目录拷贝即可备份/迁移。

**Q：手机上怎么用？**
A：方式一：手机与电脑同 Wi-Fi，浏览器访问 `http://电脑IP:8000`；方式二：`npm run app:build` + Android Studio 打包 APK 安装。

**Q：写了一半想换题材？**
A：新建项目即可；设定库、大纲、章节、断点都按项目隔离，互不影响。
