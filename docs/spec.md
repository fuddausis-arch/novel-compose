# 小说生成器技术规格说明书

## 1. 项目概述

本项目是一个面向长篇网文创作的 AI 辅助生成器，核心目标是**维持长篇连载过程中的设定一致性**。系统借鉴 `webnovel-writer` 的 Story System 思想，通过圣经（Bible）、Memory Pack、多 Agent 协作、题材模板与参考资料库，为作者提供世界观/角色/大纲生成、章节写作任务书、事实审查、状态提交等一站式工作流。

## 2. 系统架构

```
┌─────────────────────────────────────────────────────────────┐
│                        Electron 客户端                        │
│                    (或浏览器访问 Vite 前端)                      │
├─────────────────────────────────────────────────────────────┤
│  frontend/                                                  │
│  ├── views/        页面级组件（Dashboard/World/Characters/…）  │
│  ├── components/   可复用组件 + UI 组件（含 pipeline-panel）    │
│  ├── api.ts        后端 API 封装                              │
│  ├── store.ts      全局状态管理（含 pipeline 进度状态）         │
│  └── types.ts      TypeScript 类型定义                        │
└───────────────────────┬─────────────────────────────────────┘
                        │ HTTP / SSE
┌───────────────────────▼─────────────────────────────────────┐
│  novel_agent/                                               │
│  ├── api/          FastAPI 路由层                            │
│  │   ├── routes_bible.py      圣经 CRUD + 导入               │
│  │   ├── routes_generation.py 世界观/角色/大纲/任务书/审查/commit │
│  │   ├── routes_planning.py   卷级规划与人审① + SSE 流式      │
│  │   └── routes_chapters.py   章节生成（SSE 流式）           │
│  ├── bible/        数据模型 + Repository + 数据库迁移          │
│  ├── memory/       MemoryPack / RecallMemory / ArchivalMemory │
│  ├── references/   CSV 参考资料库 + 检索                      │
│  ├── templates/    题材模板（genres/）+ 提示词模板（prompts/）  │
│  ├── planning/     卷级规划 StateGraph 工作流                 │
│  └── llm/          LLM 客户端封装                             │
└───────────────────────┬─────────────────────────────────────┘
                        │ SQLAlchemy + SQLite
┌───────────────────────▼─────────────────────────────────────┐
│  SQLite 数据库                                               │
│  ├── projects / characters / world_settings / outlines       │
│  ├── foreshadows / state_changes / events / relationships    │
│  └── chapters / chapter_commits / summaries / archival       │
└─────────────────────────────────────────────────────────────┘
```

## 3. 数据流

### 3.1 项目初始化流
1. 用户在 UI 创建项目（标题、类型、简介、文风）。
2. 后端保存 `Project` 记录。
3. 前端通过 `store.refreshAssets()` 加载该项目的圣经数据。

### 3.2 设定生成与采纳流
1. 用户在世界观/角色/大纲面板点击「AI 生成」。
2. 后端调用 LLM，返回结构化 JSON。
3. 后端**先写入**圣经，再返回 `items`（含 id）。
4. 前端弹出 `AiPreviewDialog`，用户勾选/删除。
5. 用户点击「导入」：前端删除未选中项；点击「放弃」：前端删除全部生成项。
6. 前端刷新 `store` 中的圣经数据。

### 3.3 章节写作流
1. 用户在大纲面板选择章节进入编辑器。
2. 用户点击「生成任务书」→ 后端组装 MemoryPack → LLM 生成五段任务书。
3. 用户撰写/粘贴正文。
4. 用户点击「审查」→ Reviewer Agent 输出五维问题清单。
5. 用户修改后点击「提交章节」→ Data Agent 提取状态增量/关系/事件/伏笔更新。
6. 后端将摘要写入 `summaries`，状态变更写入 `state_changes`，事件写入 `events`。

### 3.4 卷级规划流
1. 用户在 Planning 面板设定全书卷数、选择要规划的卷、本卷章数。
2. 前端校验项目标题/类型非空后，调用 `/api/planning/run/stream`（SSE）。
3. `VolumeRunner`（LangGraph）按 `plan → design → outline → review → apply` 多节点流程生成卷设定；每完成一个节点向后端推送进度事件。
4. 前端右侧面板 `PipelinePanel` 实时显示节点完成进度。
5. 规划结果返回前端，用户可先调用 `/api/planning/detect` 检测与现有资产的冲突（重复角色/世界设定/大纲/伏笔），再一键导入或人审①（通过/拒绝+修改意见）。
6. `resume` 后若通过则写入圣经。

### 3.5 章节生成流
1. 用户在大纲面板点击「生成正文」。
2. 前端调用 `/api/chapters/generate/stream`（SSE）。
3. `ChapterRunner`（LangGraph）按 `assemble → write → audit → human_review → polish → save_text → summarize` 节点生成。
4. 前端 `PipelinePanel` 实时显示各节点进度；若中途失败（如 `write` 后 draft 为空）则正确展示错误，不会伪装成「完成」。

## 4. 接口契约

### 4.1 项目与圣经（`/api/projects`, `/api/bible`）
| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/api/projects` | 项目列表 |
| POST | `/api/projects` | 创建项目 |
| GET | `/api/bible/{project_id}/characters` | 角色列表 |
| POST | `/api/bible/{project_id}/characters` | 创建角色 |
| DELETE | `/api/bible/{project_id}/characters/{name}` | 删除角色 |
| GET | `/api/bible/{project_id}/world-settings` | 世界观设定列表 |
| POST | `/api/bible/{project_id}/world-settings` | 创建世界观设定 |
| DELETE | `/api/bible/{project_id}/world-settings/{id}` | 删除世界观设定 |
| GET | `/api/bible/{project_id}/outlines` | 大纲列表 |
| POST | `/api/bible/{project_id}/outlines` | 创建大纲 |
| DELETE | `/api/bible/{project_id}/outlines/{id}` | 删除大纲 |
| GET | `/api/bible/{project_id}/foreshadows` | 伏笔列表 |
| GET | `/api/bible/{project_id}/states` | 实体状态列表 |
| GET | `/api/bible/{project_id}/events` | 事件列表 |

### 4.2 AI 生成（`/api/generation`）
| 方法 | 路径 | 说明 |
|------|------|------|
| POST | `/api/generation/world/generate` | 生成世界观设定 |
| POST | `/api/generation/characters/generate` | 生成角色 |
| POST | `/api/generation/outlines/generate` | 生成大纲 |
| POST | `/api/generation/chapter/brief` | 生成章节任务书 |
| POST | `/api/generation/chapter/review` | 审查章节 |
| POST | `/api/generation/chapter/commit` | 提交章节并提取事实 |
| POST | `/api/generation/genre-context` | 获取题材上下文 |

### 4.3 导入与导出（`/api/bible/{project_id}/...`）
| 方法 | 路径 | 说明 |
|------|------|------|
| POST | `/import` | 结构化批量导入 |
| POST | `/parse-document` | 文档解析（预览） |
| POST | `/import-document` | 文档导入 |
| POST | `/parse-file` | 文件解析（预览） |
| POST | `/import-file` | 文件导入 |
| GET | `/export` | 导出项目 JSON |

### 4.4 卷级规划（`/api/planning`）
| 方法 | 路径 | 说明 |
|------|------|------|
| POST | `/api/planning/run` | 启动卷级规划（同步返回结果） |
| GET | `/api/planning/run/stream` | SSE 流式卷级规划，推送节点完成事件 |
| POST | `/api/planning/resume` | 人审①反馈 |
| POST | `/api/planning/detect` | 检测规划结果与现有资产的导入冲突 |

### 4.5 章节生成（`/api/chapters`）
| 方法 | 路径 | 说明 |
|------|------|------|
| POST | `/api/chapters/generate` | 同步生成章节正文 |
| GET | `/api/chapters/generate/stream` | SSE 流式生成章节正文，推送节点完成事件 |

## 5. 状态管理

### 5.1 前端状态（store.ts）
- `projects`、`currentProject`：项目列表与当前项目。
- `characters`、`worldSettings`、`outlines`、`foreshadows`、`states`、`events`：当前项目圣经数据。
- `summaries`、`genreContext`：章节摘要与题材上下文。
- `pipelineEvents`、`pipelineStatus`、`pipelineProgress`：全局 AI 流水线事件、状态与进度，用于 `PipelinePanel` 实时反馈。
- `refreshAssets()`：统一刷新当前项目全部圣经数据，避免多处单独请求导致不一致。

### 5.2 后端状态模型
- `StateSnapshot`：实体在某一时刻的字段值快照。
- `StateChange`：字段级增量（entity_type/entity_key/field/old/new/reason/chapter）。
- `Event`：叙事事件（event_type/subject/payload/chapter）。
- `RelationshipChange`：人物关系变化。
- `ChapterCommit`：一次 commit 的事务边界，关联状态变更、事件、关系。

## 6. AI Agent 分工

| Agent | 职责 | 触发入口 |
|-------|------|---------|
| Context Agent | 加载 MemoryPack，输出五段写作任务书 | `/chapter/brief` |
| Reviewer Agent | 五维一致性审查 | `/chapter/review` |
| Data Agent | 提取状态增量、关系、事件、伏笔更新 | `/chapter/commit` |
| 世界观/角色/大纲生成 Agent | 生成对应圣经数据 | `/world/generate` 等 |
| VolumeRunner | 卷级规划与人审①；通过 SSE 推送节点进度 | `/planning/run`, `/planning/run/stream`, `/planning/resume` |
| ChapterRunner | 单章生成流水线；通过 SSE 推送节点进度 | `/chapters/generate`, `/chapters/generate/stream` |

## 7. 一致性机制

- **Memory Pack**：working（本章真源）/ episodic（近期事实）/ semantic（长期知识）三层，按字符预算截断。
- **State Delta**：记录每个字段的旧值→新值，支持追溯。
- **Event Audit**：每章 commit 产生事件日志。
- **Foreshadow Lifecycle**：planted/developing/resolved/abandoned。
- **Genre Template & Reference**：根据 `canonical_genre` 自动注入题材约束与裁决规则。

## 8. 目录结构速查

```
vibe coding/
├── novel_agent/
│   ├── api/              # FastAPI 路由
│   ├── bible/            # ORM 模型与 Repository
│   ├── memory/           # MemoryPack / Archival / Recall
│   ├── references/       # CSV 参考资料
│   ├── templates/        # 题材模板 + 提示词模板
│   ├── planning/         # 卷级规划工作流
│   ├── llm/              # LLM 客户端
│   └── utils/            # 文件提取等工具
├── frontend/
│   ├── src/
│   │   ├── views/        # 页面
│   │   ├── components/   # 组件（含 pipeline-panel）
│   │   ├── api.ts        # API 封装
│   │   ├── store.ts      # 全局状态
│   │   └── types.ts      # 类型
│   └── electron/         # Electron 主进程
├── tests/                # 后端测试
└── docs/                 # 文档
```

## 9. 超出规格的扩展实现

以下模块在原始规格之外已实现，属于正向扩展：

### 9.1 后端扩展

| 模块 | 路径 | 功能 |
|------|------|------|
| 聊天系统 | `novel_agent/chat/` | Agent + Context + Executor + Repository，支持对象级与项目级会话 |
| 元认知遥测 | `novel_agent/telemetry/` | 生成过程监控与指标收集 |
| 编排器 | `novel_agent/orchestrator/` | book_runner / nodes / text_utils，支持批量章节生成编排 |
| 审计系统 | `novel_agent/audit/` | dedup_scanner / text_post_processor，生成后去重与后处理 |
| 命令行入口 | `novel_agent/cli.py` | CLI 直接调用各功能 |
| 扩展数据模型 | `novel_agent/bible/models.py` | `PleasureBeat`（爽点）、`PlotDebt`（欠账）、`EmotionArc`（情感弧线）、`SubplotBoard`（支线）、`CharacterMatrix`（角色交互矩阵）、`AiSuggestion`（AI 建议历史）、`ChatSession`/`ChatMessage`（聊天） |

### 9.2 前端扩展

| 模块 | 路径 | 功能 |
|------|------|------|
| 势力/怪物/关系系统 | `frontend/src/views/`、`components/` | `Faction`、`Monster`、`FactionRelationship`、`CharacterRelationship`、`EntityAppearance` 的增删改查 |
| 聊天系统 | `frontend/src/components/chat/` | `ChatPanel`、`ChatSession`、`ChatMessage`，支持对象上下文聊天 |
| AI 建议 | `frontend/src/components/ai-suggestion-dialog.tsx` | `AiSuggestion`，一键串联建议与采纳 |
