# 前端功能补全计划：前后端功能映射与缺口治理

> **状态：** 已完成前后端功能梳理与缺口识别，待按优先级实施
> **目标：** 建立前后端 1:1 完整映射，消除后端已实现但前端未暴露的能力，提升用户可感知功能覆盖率

---

## 1. 前后端功能映射总览

### 1.1 后端 API 端点清单（41 个）

按模块分类整理如下：

| 模块 | 端点 | 功能说明 | 前端调用状态 |
|---|---|---|---|
| **Projects** | `POST /api/projects` | 创建项目 | ✅ 已接入 |
| | `GET /api/projects` | 列出项目 | ✅ 已接入 |
| | `GET /api/projects/{id}` | 获取单个项目详情 | ❌ 未使用 |
| | `PUT /api/projects/{id}` | 更新项目信息 | ✅ 已接入 |
| | `DELETE /api/projects/{id}` | 删除项目并级联清空数据 | ✅ 已接入 |
| **Bible - World** | `GET /api/bible/{id}/world-settings` | 列出世界观设定 | ✅ 已接入 |
| | `POST /api/bible/{id}/world-settings` | 新增世界观设定 | ✅ 已接入 |
| | `PUT /api/bible/{id}/world-settings/{sid}` | 更新世界观设定 | ✅ 已接入 |
| | `DELETE /api/bible/{id}/world-settings/{sid}` | 删除世界观设定 | ✅ 已接入 |
| **Bible - Characters** | `GET /api/bible/{id}/characters` | 列出角色 | ✅ 已接入 |
| | `POST /api/bible/{id}/characters` | 新增角色 | ✅ 已接入 |
| | `PUT /api/bible/{id}/characters/{name}` | 更新角色 | ✅ 已接入 |
| | `DELETE /api/bible/{id}/characters/{name}` | 删除角色 | ✅ 已接入 |
| **Bible - Foreshadows** | `GET /api/bible/{id}/foreshadows` | 列出伏笔 | ✅ 已接入 |
| | `POST /api/bible/{id}/foreshadows` | 新增伏笔 | ✅ 已接入（大纲页/资产生成） |
| | `PUT /api/bible/{id}/foreshadows/{fid}` | 更新伏笔 | ✅ 已接入 |
| | `DELETE /api/bible/{id}/foreshadows/{fid}` | 删除伏笔 | ✅ 已接入 |
| **Bible - Outlines** | `GET /api/bible/{id}/outlines` | 列出大纲 | ✅ 已接入 |
| | `POST /api/bible/{id}/outlines` | 新增大纲 | ✅ 已接入 |
| | `PUT /api/bible/{id}/outlines/{oid}` | 更新大纲 | ✅ 已接入 |
| | `DELETE /api/bible/{id}/outlines/{oid}` | 删除大纲 | ✅ 已接入 |
| **Bible - Summaries** | `GET /api/bible/{id}/summaries` | 列出章节摘要 | ❌ 未使用 |
| | `DELETE /api/bible/{id}/summaries/{chapter}` | 删除指定章节摘要 | ❌ 未使用 |
| **Bible - Import** | `POST /api/bible/{id}/import` | 结构化批量导入设定 | ❌ 未使用 |
| | `POST /api/bible/{id}/import-document` | 自然语言文档导入设定 | ✅ 已接入 |
| **Generation** | `POST /api/generation/world/generate` | AI 生成世界观 | ✅ 已接入 |
| | `POST /api/generation/characters/generate` | AI 生成角色 | ✅ 已接入 |
| | `POST /api/generation/outlines/generate` | AI 生成大纲与伏笔 | ✅ 已接入 |
| | `POST /api/generation/chapter/brief` | 生成章节写作任务书 | ✅ 已接入 |
| | `POST /api/generation/chapter/review` | 章节一致性审查 | ✅ 已接入 |
| | `POST /api/generation/chapter/commit` | 提交章节并沉淀事实 | ✅ 已接入 |
| | `POST /api/generation/genre-context` | 查询题材模板与参考资料 | ❌ 未使用 |
| **Chapters** | `POST /api/chapters/generate` | 同步生成章节 | ❌ 未使用 |
| | `GET /api/chapters/list` | 列出章节 | ✅ 已接入 |
| | `GET /api/chapters/generate/stream` | SSE 流式生成章节 | ✅ 已接入 |
| | `GET /api/chapters/{chapter}/text` | 读取章节正文 | ✅ 已接入 |
| | `PUT /api/chapters/{chapter}/text` | 保存章节正文 | ✅ 已接入 |
| | `DELETE /api/chapters/{chapter}` | 删除章节 | ✅ 已接入 |
| | `GET /api/chapters/export/txt` | 导出 TXT | ✅ 已接入 |
| **Planning** | `POST /api/planning/run` | 启动卷级规划 + 人审① | ❌ 未使用 |
| | `POST /api/planning/resume` | 人审① approve/reject | ❌ 未使用 |

### 1.2 前端功能组件清单

| 组件/页面 | 位置 | 核心能力 | 依赖后端模块 |
|---|---|---|---|
| `App.tsx` | 主入口 | 项目切换、侧边栏导航、工作台、资产树、删除项目 | Projects、Bible、Chapters |
| `DashboardView` | 内联 | 项目统计卡片、项目信息编辑 | Projects |
| `WorldView` | `components/world-view.tsx` | 世界观列表、CRUD、AI 生成 | Bible World、Generation |
| `CharactersView` | `components/characters-view.tsx` | 角色列表、CRUD、AI 生成 | Bible Characters、Generation |
| `OutlinesView` | `components/outlines-view.tsx` | 大纲列表、CRUD、AI 生成、伏笔板 | Bible Outlines/Foreshadows、Generation |
| `AssetEditorView` | 内联 | 角色/伏笔/大纲详情编辑 | Bible |
| `ChapterEditorView` | 内联 | 章节正文编辑、任务书、审查、提交、AI 流式生成 | Chapters、Generation |
| `ImportView` | 内联 | 自然语言文档导入 | Bible Import-Document |
| `ExportView` | 内联 | TXT 导出 | Chapters Export |
| `CreateProjectDialog` | `components/create-project-dialog.tsx` | 新建项目弹窗 | Projects |
| `store.ts` | 状态管理 | 统一拉取角色/伏笔/大纲/世界观/章节 | Bible、Chapters |

---

## 2. 功能缺口识别

### 2.1 缺口矩阵

| 编号 | 缺口名称 | 后端端点 | 前端现状 | 严重程度 | 影响说明 |
|---|---|---|---|---|---|
| GAP-01 | **卷级规划与人审①工作台缺失** | `/api/planning/run`、`/api/planning/resume` | 仅 `api.ts` 有封装，UI 无任何入口 | 🔴 P0 | 无法使用 VolumeRunner 进行卷级大纲规划，无法进入人审①循环 |
| GAP-02 | **章节摘要管理不可见** | `/api/bible/{id}/summaries`、`DELETE /api/bible/{id}/summaries/{chapter}` | 无入口 | 🟡 P1 | commit 后生成的摘要无法查看、检索、删除，长期记忆价值未释放 |
| GAP-03 | **题材上下文未展示** | `/api/generation/genre-context` | 无入口 | 🟡 P1 | brief/commit 已自动注入题材约束，但用户看不到模板与参考资料 |
| GAP-04 | **结构化批量导入缺失** | `/api/bible/{id}/import` | 仅支持自然语言文档导入 | 🟡 P1 | 已有 JSON/CSV 设定数据的用户无法批量导入 |
| GAP-05 | **单项目详情查询未使用** | `GET /api/projects/{id}` | 通过 `listProjects` + 本地查找替代 | 🟢 P2 | 不影响功能，但大型项目列表下存在数据不同步风险 |
| GAP-06 | **同步章节生成入口缺失** | `POST /api/chapters/generate` | 仅支持 SSE 流式生成 | 🟢 P2 | 流式生成是主路径，同步端点可作为 fallback 或脚本场景补充 |

### 2.2 严重程度定义

- **P0（阻断）**：后端核心能力无法被用户感知，严重限制产品主流程
- **P1（重要）**：影响数据管理、可解释性或批量效率，需尽快补齐
- **P2（优化）**：体验增强或替代路径已存在，可延后处理

---

## 3. 缺口根因分析

### 3.1 GAP-01：卷级规划与人审①工作台缺失

**根因：**
1. **开发节奏差异**：M4 计划以"最小可用单页控制台"为目标，但当前 React 前端重构后优先完成了资产编辑与单章生成，卷级规划的 UI 被后置
2. **人机审核流程复杂**：`VolumeRunner` 需要"启动 → 等待人审 → approve/reject → 继续/重写"的状态机，前端缺少对应的 interrupt/resume UI 模式
3. **需求优先级调整**：`frontend-redesign.md` 提到"四界面缩减为单页控制台"，驾驶舱、人审、圣经浏览、阅读合并，但重构过程中人审模块被裁剪
4. **接口封装与实际调用脱节**：`api.ts` 中保留了 `runPlanning`/`resumePlanning` 但没有任何组件消费

**后果：**
- 用户只能从大纲页零散生成章节，无法体验"卷一 30 章一键规划 → 人审确认 → 批量写入圣经"的完整工作流
- `/api/planning/run` 与 `/api/planning/resume` 成为事实上的死代码（从用户视角）

### 3.2 GAP-02：章节摘要管理不可见

**根因：**
1. **功能被视为内部机制**：`commitChapter` 生成的 `ChapterSummary` 主要用于 MemoryPack 与状态沉淀，产品设计时未将其作为用户可浏览的资产
2. **前端数据模型未暴露**：`store.ts` 中没有 `summaries` 状态，`types.ts` 中 `ChapterCommit` 接口存在但未在 UI 中使用
3. **缺少管理需求场景**：未设计"按摘要检索章节"、"删除错误摘要"等交互

**后果：**
- 用户看不到每章的核心事件、字数、出场人物等沉淀结果
- 摘要错误时无法删除重建，只能重新 commit 覆盖

### 3.3 GAP-03：题材上下文未展示

**根因：**
1. **自动注入优于显式展示**：`routes_generation.py` 的 `_genre_context` 在 brief/review/commit 中自动拼接题材模板和参考资料，产品设计假设用户无需查看
2. **参考数据库价值未释放**：15 个题材模板 + 9 张 CSV 参考表目前仅作为 prompt 上下文，没有独立浏览入口

**后果：**
- 用户不理解为什么 brief 会给出某些约束
- 无法手动选择/覆盖题材模板、无法浏览参考资料库

### 3.4 GAP-04：结构化批量导入缺失

**根因：**
1. **MVP 简化**：M4 计划只保留自然语言文档导入，结构化导入被视为进阶功能
2. **交互成本高**：需要用户按 JSON schema 组织数据，UI 需要上传/粘贴 JSON 并提供字段映射

**后果：**
- 从其他工具迁移设定数据的用户路径不通
- 批量导入的准确性依赖 LLM 提取，结构化数据反而更可靠

### 3.5 GAP-05：单项目详情查询未使用

**根因：**
1. **当前数据量小**：项目列表已包含全部字段，前端认为无需单独查询
2. **状态管理简化**：`store.ts` 用 `projects` 数组 + `currentProject` 本地查找替代

**后果：**
- 项目数据在多个会话/标签页间可能不同步
- 未来项目列表分页后，`style` 等字段可能不在列表中

### 3.6 GAP-06：同步章节生成入口缺失

**根因：**
1. **SSE 流式是首选体验**：同步端点 `/api/chapters/generate` 仅作为 API 备用存在
2. **前端无需同步阻塞**：当前场景下流式生成已覆盖所有需求

**后果：**
- 无显著影响，可保留为后端能力

---

## 4. 前端补全计划

### 4.1 总体原则

1. **补齐 P0 主流程**：优先实现卷级规划与人审①，恢复 M4 原计划核心闭环
2. **释放数据资产**：让 commit 生成的摘要、题材参考资料可被用户查看
3. **保持 UI 一致性**：新增页面沿用现有侧边栏 + 卡片 + Badge 设计语言
4. **不破坏现有路径**：新增功能以独立 tab/弹窗形式接入，不影响当前资产编辑和章节生成
5. **渐进式实现**：每个任务独立可测，逐步合并

### 4.2 任务拆分

#### 🔴 P0：卷级规划与人审①工作台

**目标：** 在侧边栏新增"卷级规划"入口，支持启动卷规划、查看规划结果、进行人审① approve/reject。

**涉及文件：**
- 新增：`frontend/src/components/planning-view.tsx`
- 修改：`frontend/src/App.tsx`、`frontend/src/api.ts`、`frontend/src/types.ts`、`frontend/src/store.ts`

**详细步骤：**

1. **扩展类型定义（types.ts）**
   - 新增 `VolumePlan`、`PlanResult`、`PlanningReviewPayload` 等接口
   - 明确 `runPlanning` 与 `resumePlanning` 的返回类型

2. **新增 PlanningView 组件**
   - 输入：卷名（默认"卷一"）、章节数（默认 30）、节奏描述
   - 操作："启动规划"按钮，调用 `/api/planning/run`
   - 结果展示：以卡片列表展示生成的角色、世界观、章纲
   - 人审区：显示"通过/打回"按钮，调用 `/api/planning/resume`
   - 状态管理：记录 `currentThreadId`，支持 approve/reject 后继续流程

3. **接入 App.tsx 侧边栏**
   - 在"工作台"下方新增"卷级规划"导航项
   - 点击后 `activeTab = "planning"`，渲染 `PlanningView`

4. **状态同步**
   - 规划完成后调用 `store.refreshAssets()`，将生成的角色/大纲/伏笔同步到侧边栏资产树

5. **异常处理**
   - 规划超时或 LLM 返回格式错误时显示可重试提示
   - 人审打回后允许用户填写修改意见再提交

**验收标准：**
- 能从 UI 启动卷级规划并看到生成的章纲
- 能点击"通过"将数据写入圣经
- 点击"打回"可填写意见并重新生成
- 规划完成后侧边栏资产树自动刷新

---

#### 🟡 P1：章节摘要浏览器

**目标：** 在导出 tab 或新增"摘要"tab 中展示所有章节摘要，支持删除错误摘要。

**涉及文件：**
- 新增：`frontend/src/components/summaries-view.tsx`
- 修改：`frontend/src/App.tsx`、`frontend/src/api.ts`、`frontend/src/types.ts`、`frontend/src/store.ts`

**详细步骤：**

1. **扩展类型与 API**
   - `types.ts`：确认 `ChapterCommit`、`ChapterSummary` 接口字段
   - `api.ts`：添加 `listSummaries(projectId)`、`deleteSummary(projectId, chapter)`

2. **新增 SummariesView 组件**
   - 表格/卡片展示：章节号、标题、核心事件、字数、提交时间
   - 支持按章节号/关键词搜索
   - 每行提供"删除摘要"按钮（不删除正文）

3. **接入 App.tsx**
   - 在侧边栏新增"摘要"或将其并入"导出"页作为子 tab

**验收标准：**
- commit 后可在摘要浏览器中看到该章摘要
- 可删除单条摘要，删除后重新 commit 可重建

---

#### 🟡 P1：题材上下文展示面板

**目标：** 在项目信息或大纲页展示当前题材识别结果、模板约束、参考资料。

**涉及文件：**
- 新增：`frontend/src/components/genre-context-panel.tsx`
- 修改：`frontend/src/App.tsx`、`frontend/src/api.ts`、`frontend/src/types.ts`

**详细步骤：**

1. **扩展 API 与类型**
   - `api.ts`：添加 `getGenreContext(projectId)`，调用 `/api/generation/genre-context`
   - `types.ts`：定义 `GenreContext` 接口（canonical_genre、template、references）

2. **新增 GenreContextPanel 组件**
   - 展示：识别的 canonical genre、题材模板 Markdown 渲染、参考资料列表
   - 位置：Dashboard 页底部或 WorldView 页顶部

3. **接入 App.tsx**
   - 在项目概览卡片下方新增"题材上下文"折叠面板

**验收标准：**
- 新建项目后能自动识别题材并展示模板
- brief/review/commit 注入的参考资料可被用户查看

---

#### 🟡 P1：结构化批量导入

**目标：** 在导入页新增 JSON 批量导入入口，与自然语言导入并列。

**涉及文件：**
- 修改：`frontend/src/App.tsx`、`frontend/src/api.ts`

**详细步骤：**

1. **扩展 API**
   - `api.ts`：添加 `importStructured(projectId, data)`，调用 `/api/bible/{id}/import`

2. **改造 ImportView 组件**
   - 增加 tab 切换："自然语言导入" / "JSON 批量导入"
   - JSON 模式：提供 textarea + 格式示例 + 校验提示
   - 成功后显示导入统计（角色/伏笔/大纲数量）

**验收标准：**
- 可粘贴符合 schema 的 JSON 并导入
- 导入后侧边栏资产树刷新

---

#### 🟢 P2：单项目详情查询兜底

**目标：** 在切换项目或刷新时，通过单独查询确保 `currentProject` 字段完整。

**涉及文件：**
- 修改：`frontend/src/store.ts`、`frontend/src/App.tsx`

**详细步骤：**

1. **扩展 API**
   - `api.ts`：添加 `getProject(id)`

2. **改造 store**
   - `setCurrentProject` 接收 id 时先调用 `getProject(id)` 拉取完整数据
   - 保留本地缓存作为 fallback

**验收标准：**
- 切换项目后 `style` 等字段始终存在
- 即使列表字段精简也不影响功能

---

#### 🟢 P2：同步章节生成（可选）

**目标：** 在章节编辑器提供"后台同步生成"选项，用于网络不稳定时替代 SSE。

**涉及文件：**
- 修改：`frontend/src/components/ChapterEditorView` 相关内联代码

**详细步骤：**

1. **扩展 API**
   - `api.ts`：添加 `generateChapterSync(projectId, chapter, title)`

2. **改造 ChapterEditorView**
   - AI 生成按钮旁增加下拉或选项："流式生成" / "同步生成"

**验收标准：**
- 同步生成完成后正确加载章节正文

---

## 5. 实施顺序建议

| 阶段 | 任务 | 预计影响范围 | 优先级 |
|---|---|---|---|
| **Phase 1** | GAP-01 卷级规划与人审①工作台 | 大（新增核心页面） | 🔴 P0 |
| **Phase 2** | GAP-02 章节摘要浏览器 | 中（新增数据展示页） | 🟡 P1 |
| **Phase 3** | GAP-03 题材上下文展示面板 | 小（新增信息面板） | 🟡 P1 |
| **Phase 4** | GAP-04 结构化批量导入 | 中（改造导入页） | 🟡 P1 |
| **Phase 5** | GAP-05 单项目详情查询兜底 | 小（状态管理优化） | 🟢 P2 |
| **Phase 6** | GAP-06 同步章节生成 | 小（增加备用路径） | 🟢 P2 |

---

## 6. 依赖与风险

### 6.1 依赖项

1. **后端接口稳定性**：`/api/planning/run` 与 `/api/planning/resume` 需要确认在长时间运行下不会断开（当前为同步 `asyncio.run`，可能阻塞并超时）
2. **LLM 输出格式**：卷级规划依赖 LLM 返回严格 JSON，需要配合 prompt 与解析容错
3. **状态持久化**：人审①的 checkpoint 依赖 LangGraph thread_id，前端需妥善保存当前 thread_id

### 6.2 风险与应对

| 风险 | 影响 | 应对措施 |
|---|---|---|
| 卷级规划 API 同步阻塞导致超时 | P0 功能不可用 | 将后端改为异步任务 + 轮询，或前端使用 SSE 推送进度 |
| 新增组件过多导致 App.tsx 臃肿 | 维护性下降 | 将内联视图拆分为独立组件，保持 App.tsx 只做路由/布局 |
| 前端状态与后端数据不同步 | 用户看到旧数据 | 在关键操作后统一调用 `store.refreshAssets()` |
| 题材模板 Markdown 渲染安全 | XSS 风险 | 使用可信的 Markdown 渲染库并对输入做净化 |

---

## 7. 验收清单

- [ ] 侧边栏新增"卷级规划"入口，可完成 run → review → resume 全流程
- [ ] 规划生成的角色/大纲/伏笔自动同步到资产树
- [ ] 新增"章节摘要"页面，可查看与删除摘要
- [ ] 项目 Dashboard 展示题材上下文（canonical genre + 模板 + 参考资料）
- [ ] 导入页支持 JSON 结构化批量导入
- [ ] 切换项目时拉取完整项目详情，避免字段缺失
- [ ] 所有新增功能通过 TypeScript 编译与现有测试回归
- [ ] 更新前端 API 文档与操作指南

---

## 8. 后续建议

1. **建立前后端契约文档**：将 API 接口、请求/响应 schema、状态码整理为独立文档，避免未来再次出现"接口已封装但无 UI"的脱节
2. **引入接口消费检查**：在 CI 中增加"api.ts 中定义的函数必须在组件中被引用"的静态检查（可配置白名单）
3. **前端目录结构优化**：将 DashboardView/AssetEditorView/ChapterEditorView/ImportView/ExportView 从 `App.tsx` 拆出，形成 `views/` 目录
4. **权限与错误处理统一化**：当前各组件各自处理错误提示，建议抽离 `useApiError` hook 统一错误反馈
