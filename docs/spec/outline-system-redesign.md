# 小说创作辅助系统改造设计文档

## 1. 目标

- 把「大纲」拆成三个独立入口：大纲（卷）、细纲、章纲，支持层级化规划。
- 在创建项目时支持选择内置小说模板。
- 暂停「节奏模板」功能，相关入口留空。
- 修复项目数据隔离、级联删除等关联性问题。
- 让 AI 生成结果支持人工二次编辑。

---

## 2. 现状与问题

| # | 问题 | 影响 | 优先级 |
|---|---|---|---|
| 1 | 章节文件未按 `project_id` 隔离，全部存在 `project_data/chapters/` | 多项目串数据、删除项目遗留文件 | 高 |
| 2 | `routes_chapters.py` 删除章节摘要时取最新项目而非当前项目 | 误删其他项目数据 | 高 |
| 3 | 删除项目时未清理章节正文文件 | 磁盘残留 | 高 |
| 4 | WorldSetting、Foreshadow、ChapterSummary 等表缺少 `ondelete=cascade` | 删除项目后留下孤儿数据 | 高 |
| 5 | `Outline.parent_id` 无外键约束 | 删除父级后子级变孤儿 | 中 |
| 6 | 节奏模板不符合需求 | 需要暂停并留空 | 高 |
| 7 | 30+ 内置小说模板未接入创建项目流程 | 用户无法选择模板 | 高 |
| 8 | 大纲只有单层 `level=chapter` | 无法做卷/细纲/章纲三层规划 | 高 |
| 9 | AI 生成角色/阵营/怪物/大纲后无法直接编辑 | 不灵活 | 中 |
| 10 | `/api/chapters/list` 接收 `project_id` 但未实际用于过滤章节文件 | 潜在隔离问题 | 中 |

---

## 3. 数据模型变更

### 3.1 项目目录结构

```
project_data/
├── projects/
│   └── {project_id}/
│       ├── chapters/          # 章节正文
│       ├── summaries/         # 章节摘要历史（如需要文件化）
│       └── ...
├── config.yaml
└── ...
```

- `RecallMemory` 初始化时根据 `project_id` 决定 `chapters_dir`。
- 创建项目时自动创建该项目目录。
- 删除项目时级联删除整个 `{project_id}` 目录。

### 3.2 `Outline` 模型

```python
class Outline(Base):
    __tablename__ = "outlines"

    id: Mapped[int] = mapped_column(primary_key=True)
    project_id: Mapped[int] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"))
    parent_id: Mapped[int | None] = mapped_column(ForeignKey("outlines.id", ondelete="CASCADE"))
    level: Mapped[str] = mapped_column(String)  # volume | arc | chapter
    order: Mapped[int]
    title: Mapped[str]
    summary: Mapped[str | None]
    act: Mapped[str | None]
    strand: Mapped[str | None]

    project: Mapped["Project"] = relationship("Project", back_populates="outlines")
    parent: Mapped["Outline | None"] = relationship("Outline", remote_side=[id], back_populates="children")
    children: Mapped[list["Outline"]] = relationship("Outline", back_populates="parent")
```

### 3.3 其他模型补外键

给以下表统一加上 `ondelete="CASCADE"`：
- `WorldSetting.project_id`
- `Foreshadow.project_id`
- `ForeshadowImplant.project_id`
- `ChapterSummary.project_id`
- `EmotionArc.project_id`
- `SubplotBoard.project_id`
- `CharacterMatrix.project_id`
- `TruthEvent.project_id`
- `StateChange.project_id`
- `ChapterCommit.project_id`

---

## 4. API 变更

### 4.1 大纲相关

保留 `/api/bible/{project_id}/outlines` 作为统一 CRUD 接口，通过 `level` 参数过滤：

- `GET /api/bible/{project_id}/outlines?level=volume`
- `GET /api/bible/{project_id}/outlines?level=arc&parent_id=1`
- `GET /api/bible/{project_id}/outlines?level=chapter&parent_id=2`
- `POST /api/bible/{project_id}/outlines` — 创建/更新（包含 `level`、`parent_id`）
- `DELETE /api/bible/{project_id}/outlines/{outline_id}` — 级联删除子级

生成接口拆成三个：

- `POST /api/generation/volumes/generate` — 生成卷（大纲）
- `POST /api/generation/arcs/generate` — 针对选中的卷生成细纲
- `POST /api/generation/chapters/generate` — 针对选中的细纲生成章纲

请求体统一包含：

```json
{
  "project_id": 1,
  "parent_id": 1,           // 生成细纲/章纲时必填
  "count": 5,
  "custom_prompt": "...",   // 用户自定义要求
  "template_key": "xianxia" // 后续扩展：按内置模板风格生成
}
```

### 4.2 章节相关

- `GET /api/chapters/list?project_id={project_id}` 必须按项目过滤。
- `RecallMemory` 初始化时绑定项目目录。

### 4.3 项目创建

- `POST /api/projects` 增加可选字段 `template_key`。
- 如果传入 `template_key`，读取 `novel_agent/templates/genres/{template_key}.md` 内容，作为项目 `style` 或单独保存为 `Project.template_content`。

### 4.4 节奏模板

- 前端「节奏模板」下拉框留空，后端接口保留但不使用。

---

## 5. 前端结构变更

### 5.1 侧边栏

把「大纲」入口改为可展开菜单：

```
大纲
├── 大纲（卷）
├── 细纲
└── 章纲
```

### 5.2 三个独立页面

| 页面 | 功能 | 数据来源 |
|---|---|---|
| `OutlinesVolumeView` | 展示/生成/编辑卷级大纲 | `level=volume` 的 outlines |
| `OutlinesArcView` | 先选卷，再展示/生成/编辑该卷下的细纲 | `level=arc` & `parent_id=volume_id` |
| `OutlinesChapterView` | 先选细纲，再展示/生成/编辑该细纲下的章纲 | `level=chapter` & `parent_id=arc_id` |

每个页面都支持：
- 列表展示
- 勾选/全选
- AI 生成（弹出预览，可取消/导入）
- 单行编辑（标题、摘要、act、strand、order）
- 删除（级联删除子级）

### 5.3 创建项目对话框

新增「模板选择」步骤：
- 展示内置模板列表（读取后端 `/api/templates/genres`）。
- 支持搜索/分类筛选。
- 不选则留空。

### 5.4 生成弹窗

所有 AI 生成结果统一走同一个预览弹窗组件：
- 列表展示生成内容
- 每行可编辑
- 可勾选导入/取消
- 显示本次使用的自定义提示词（可修改后重新生成）

---

## 6. 实施步骤

1. **修复数据隔离与级联删除**
   - 修改 `RecallMemory` 支持项目目录。
   - 修改项目创建/删除逻辑，创建/清理项目目录。
   - 修复 `routes_chapters.py` 删除摘要的 bug。
   - 给相关模型补 `ondelete="CASCADE"`。
   - 给 `Outline.parent_id` 加外键约束。

2. **暂停节奏模板**
   - 前端模板选择器置空。
   - 后端接口保留，参数忽略。

3. **接入内置小说模板**
   - 后端扫描 `novel_agent/templates/genres/` 提供列表接口。
   - 创建项目时支持选择模板并写入项目配置。

4. **大纲三层级改造**
   - 修改 `Outline` 模型 `level` 枚举。
   - 拆分外 API：`/generation/volumes`、`/generation/arcs`、`/generation/chapters`。
   - 前端新增三个视图，支持父级选择、生成、编辑。

5. **统一生成预览编辑组件**
   - 把角色/阵营/怪物/大纲的生成结果统一用这个组件处理。

6. **回归测试**
   - 创建多个项目验证数据隔离。
   - 测试大纲三层级生成与级联删除。
   - 测试模板选择流程。

---

## 7. 风险与注意事项

- **数据库迁移**：修改外键约束需要重新生成数据库或写 Alembic 迁移脚本。当前使用 SQLite，建议直接删库重建（数据已清空）。
- **已有章节文件**：目前项目数据已清空，改造时无需迁移旧文件。
- **性能**：卷下面细纲、细纲下面章纲的级联查询注意 N+1，必要时一次性拉取整棵树。
