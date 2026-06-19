# AI 一键串联功能设计

## 1. 背景与目标

用户在创作过程中经常需要：
- 写完一卷/一小节/一章后，让 AI 推荐后续剧情；
- 在怪物/势力/关系模块中，基于现有世界观和剧情补充缺失的资产；
- 对 AI 推荐内容进行人工干预（采纳、部分采纳编辑、不采纳），并保留历史。

本功能命名为 **「AI 一键串联」**，核心目标是：基于当前上下文一键生成后续剧情或配套资产，并以弹窗形式让用户决定如何落库。

## 2. 设计原则

- **上下文感知**：按钮默认建议类型由当前界面决定。
- **复用优先**：复用现有 `generate_*` 体系与 `AiPreviewEditor` 可编辑弹窗模式。
- **人工可控**：任何 AI 输出都必须经过用户确认才能落库；支持内联编辑。
- **风格一致**：弹窗、按钮、加载状态与现有 UI 组件保持一致。
- **可追溯**：记录每次建议的触发来源、上下文、原始输出和采纳结果。

## 3. 触发入口

| 界面 | 默认建议类型 | 按钮文案 | 按钮位置 |
|------|-------------|---------|---------|
| 大纲（卷） | plot（后续剧情） | ✨ AI 建议后续 | 与「AI 生成卷」并列 |
| 细纲 | plot | ✨ AI 建议后续 | 与「AI 生成细纲」并列 |
| 章纲 | plot | ✨ AI 建议后续 | 与「AI 生成章纲」并列 |
| 章节编辑器 | plot | ✨ AI 建议后续 | 与「AI 生成」并列 |
| 怪物图鉴 | monster | ✨ AI 建议怪物 | 与「新建怪物」并列 |
| 势力组织 | faction | ✨ AI 建议势力 | 与「新建势力」并列 |
| 人物关系网 | relationship | ✨ AI 建议关系 | 与「新建关系」并列 |

弹窗内提供类型切换标签（后续剧情 / 怪物 / 势力 / 关系），允许用户偏离默认类型。

## 4. 用户交互流程

1. 用户点击「AI 建议」按钮，前端进入加载状态。
2. 后端根据 `context_type`、`context_id`、`suggest_type` 拼装 prompt 调用 LLM。
3. 生成完成后，弹出 `AiSuggestionDialog`：
   - 左侧/顶部显示类型切换；
   - 中间以卡片列表展示建议项，每项可勾选；
   - 底部按钮：不采纳、编辑后采纳、采纳选中项。
4. 用户选择「编辑后采纳」时，弹窗进入内联编辑模式，允许修改标题、摘要/描述等字段。
5. 点击「采纳选中项」后，前端调用 `/api/generation/suggest/adopt`，后端创建对应记录：
   - plot → 创建 outline 或追加章节正文；
   - monster → 创建 monster；
   - faction → 创建 faction；
   - relationship → 创建 character_relationship 或 faction_relationship。
6. 创建成功后，弹窗关闭，刷新列表，并自动打开对应资产的编辑面板（若适用）。
7. 点击「不采纳」则直接关闭弹窗，不落库，但仍记录到采纳历史中标记为 rejected。

## 5. 后端设计

### 5.1 新增接口

#### `POST /api/generation/suggest`

请求：
```json
{
  "project_id": 1,
  "context_type": "outline",
  "context_id": 12,
  "suggest_type": "plot",
  "count": 3,
  "custom_prompt": ""
}
```

响应：
```json
{
  "suggestions": [
    {
      "type": "plot",
      "title": "第 12 章 · 宗门试炼",
      "summary": "主角在试炼中遭遇赤焰魔狼...",
      "payload": { "level": "chapter", "order": 12, "act": "小高潮", "strand": "quest" }
    }
  ]
}
```

#### `POST /api/generation/suggest/adopt`

请求：
```json
{
  "project_id": 1,
  "suggestions": [
    {
      "type": "monster",
      "title": "赤焰魔狼",
      "summary": "火属性精英怪，掉落炎晶",
      "payload": { "species": "魔兽", "rank": "精英", "habitats": "火山秘境" },
      "edits": { "name": "赤焰魔狼·改" }
    }
  ]
}
```

响应：
```json
{
  "created": {
    "outlines": [],
    "monsters": [{ "id": 5, "name": "赤焰魔狼·改" }],
    "factions": [],
    "relationships": []
  }
}
```

### 5.2 建议生成策略

- `plot`：
  - 若 `context_type` 为 outline，读取该 outline 的 level/order/summary，判断是续写当前项还是生成下一项；
  - 若 `context_type` 为 chapter，基于当前章节正文/任务书/章纲续写；
  - 复用现有 `_outline_context` 获取世界观、角色、伏笔、已有大纲。
- `monster` / `faction` / `relationship`：
  - 读取项目已有世界观、角色、大纲、已有同类资产；
  - prompt 要求 LLM 输出与设定一致、不重复的新资产；
  - relationship 生成需基于已有角色名或势力 ID。

### 5.3 数据模型

新增 `ai_suggestions` 表：

| 字段 | 类型 | 说明 |
|------|------|------|
| id | Integer PK | |
| project_id | Integer FK → projects.id, CASCADE | |
| context_type | String | outline / chapter / monster / faction / relationship |
| context_id | Integer/String | 对应上下文的 ID 或标识 |
| suggest_type | String | plot / monster / faction / relationship |
| prompt | Text | 提交给 LLM 的完整 prompt |
| raw_response | Text | LLM 原始返回 |
| adopted_items | JSON | 用户最终采纳并保存的项 |
| status | String | adopted / partial / rejected |
| created_at | DateTime | |

## 6. 前端设计

### 6.1 新增组件

**`AiSuggestionDialog`**
- Props：`open`, `project`, `contextType`, `contextId`, `defaultSuggestType`, `onClose`, `onAdopted`
- 内部状态：`suggestType`, `loading`, `suggestions`, `selectedIds`, `editingItem`, `customPrompt`
- 支持类型切换标签、复选框全选/取消、内联编辑、重新生成。

### 6.2 集成点

- `OutlineLevelView`：在「AI 生成」旁新增「AI 建议后续」按钮。
- `ChapterEditorView`：在工具栏新增「AI 建议后续」按钮。
- `MonstersView` / `FactionsView` / `RelationshipsView`：在「新建」旁新增「AI 建议」按钮。
- 点击后打开 `AiSuggestionDialog`，采纳后调用 `refresh()` 并打开对应资产编辑器（通过 `onSelectAsset`）。

## 7. 性能与体验

- 生成响应控制在 5-15 秒；超时由 `LLMClient` 统一处理。
- 加载状态使用现有顶部进度条或按钮 loading 动画。
- LLM prompt 中加入质量控制要求：与现有设定不冲突、不重复、风格一致。
- 返回建议数量默认 3-5 条，用户可通过输入框调整。

## 8. 错误处理

- LLM 返回非 JSON 或空结果：友好提示「AI 未能理解上下文，请补充描述后重试」。
- 采纳时必填字段缺失：在弹窗内标红并阻止提交。
- 网络/后端异常：使用现有 `useToast` 提示。

## 9. 后续可扩展

- 在采纳历史中支持「查看原始建议」和「重新应用」。
- 支持批量采纳历史模板。
- 支持用户对每条建议打分，用于后续 prompt 调优。
