# 前端界面全面优化设计文档

## 1. 背景与目标

当前前端已实现小说生成器的主要功能界面（Dashboard、卷级规划、章节编辑、一致性看板、导入导出等），但存在两方面问题：

1. **视觉层面**：界面被用户反馈为"太素"，色彩层次弱、视觉焦点不清晰、缺少现代感和吸引力。
2. **逻辑层面**：`App.tsx` 职责过重（508 行），状态刷新粒度粗，交互反馈不一致，长期维护成本高。

本设计旨在：
- 提供 **三套可切换主题**，覆盖浅色玻璃、温暖纸墨、深色 AI 三种风格。
- **重构前端业务逻辑**，拆分大组件、优化状态管理、提升渲染性能与交互体验。
- 确保最终界面在不同设备上保持良好的响应式表现。

## 2. 范围

**包含：**
- 主题系统设计（CSS 变量、切换器、持久化）
- `index.css` 与所有 UI 组件的颜色/阴影/圆角 token 改造
- `App.tsx` 拆分与自定义 hooks 抽取
- Store 刷新逻辑优化
- 章节编辑器自动保存
- 响应式布局（侧边栏/右面板折叠）
- 基础过渡动效

**不包含：**
- 新增业务功能（如章节审查、批量生成等，这些功能已存在或另排期）
- 后端 API 改动
- 图标库更换（继续使用 lucide-react）

## 3. 主题系统设计

### 3.1 三套主题

| 主题 key | 名称 | 基调 | 适用场景 |
|---|---|---|---|
| `light-glass` | 精致浅色玻璃 | 浅灰背景 + 毛玻璃卡片 + 蓝青渐变 | 默认，白天使用 |
| `warm-paper` | 温暖写作工作室 | 米白/羊皮纸底色 + 琥珀强调 | 长时间码字，护眼 |
| `dark-ai` | 深色 AI 指挥中心 | 深 slate 背景 + 霓虹紫/青渐变 | 夜间，科技感 |

### 3.2 技术实现

- 在 `index.css` 中定义三套 CSS 变量，通过 `html[data-theme="..."]` 选择器作用。
- 所有颜色、背景、边框、阴影均使用 CSS 变量，禁止在组件中写死色值。
- 切换主题时给 `html` 设置 `data-theme`，并写 `localStorage`。
- 切换动画：`transition: background-color 0.2s, border-color 0.2s, color 0.2s`。

### 3.3 核心 Token 示例（以 light-glass 为基准）

```css
html[data-theme="light-glass"] {
  --background: #f5f5f7;
  --surface: rgba(255, 255, 255, 0.78);
  --surface-elevated: rgba(255, 255, 255, 0.92);
  --border: rgba(0, 0, 0, 0.08);
  --border-strong: rgba(0, 0, 0, 0.14);
  --foreground: #1d1d1f;
  --muted: #6e6e73;
  --primary: #0071e3;
  --primary-hover: #0077ed;
  --danger: #ff3b30;
  --success: #34c759;
  --warning: #ff9500;
  --radius: 0.875rem;
  --shadow-sm: 0 2px 8px rgba(0,0,0,0.04);
  --shadow: 0 8px 24px rgba(0,0,0,0.08);
  --shadow-lg: 0 16px 48px rgba(0,0,0,0.12);
}
```

warm-paper 与 dark-ai 按各自基调映射同名变量。

### 3.4 主题切换器

- 位置：标题栏右侧（与项目标题同处一行）。
- 交互：图标按钮点击后弹出小面板，展示三个主题缩略图 + 名称，当前主题高亮。
- 图标建议：使用 `Palette` 或循环展示 `Sun` / `Moon` / `BookOpen`。

## 4. 逻辑优化设计

### 4.1 拆分 App.tsx

当前 `App.tsx` 包含：状态管理、项目 CRUD、资产 CRUD、导入导出、章节生成、UI 布局。拆分为：

| 新组件/Hook | 职责 |
|---|---|
| `Layout` | 整体三栏布局（Sidebar / Workspace / PipelinePanel） |
| `Sidebar` | 项目选择、导航、资产列表、创建/删除项目 |
| `Workspace` | 根据 `activeTab` 渲染对应 View |
| `PipelinePanel` | AI 流水线事件展示 |
| `useProjectActions` | 项目 CRUD、项目切换 |
| `useAssetActions` | 角色/伏笔/大纲/章节的增删改查 |
| `useImportActions` | 文档/文件解析、结构化导入 |
| `useGeneration` | 章节生成 SSE、生成状态管理 |

### 4.2 Store 优化

当前问题：`refreshAssets()` 一次性刷新 5 类资产，导致只要一类数据变化就全部重渲染。

优化：
- 拆分为 `refreshCharacters()`、`refreshOutlines()`、`refreshForeshadows()`、`refreshWorldSettings()`、`refreshChapters()`。
- `refreshAssets()` 保留作为全量刷新入口（切换项目时调用）。
- 为每类资产增加独立 `loading` 状态，例如 `charactersLoading`，避免全局 `loading` 互相阻塞。

### 4.3 渲染性能

- 侧边栏项目列表、资产列表项使用 `React.memo`。
- 长章节列表（> 50 章）使用 `@tanstack/react-virtual` 虚拟滚动。
- `DashboardView` 的一致性看板增加缓存：同一次 session 内，除非用户手动刷新或数据变更，否则不重复请求。

### 4.4 交互体验

- **章节编辑器自动保存**：对 `content` / `title` 做 1s debounce，自动调用保存 API，并用 Toast 提示"已自动保存"。
- **统一错误处理**：所有 API 错误通过 `useToast` 提示，不再裸抛到控制台。
- **操作确认**：删除项目/资产/章节保留 `confirm`，但加更明确的文案。

## 5. 响应式与动效

### 5.1 响应式布局

- 桌面端：固定 224px 侧边栏 + 自适应工作区 + 288px 右面板。
- 平板/小屏（< 1024px）：右面板自动折叠为可展开抽屉；侧边栏保持可滚动。
- 移动端（< 768px）：侧边栏折叠为顶部汉堡菜单；工作区全宽显示。

### 5.2 动效

- 页面/标签切换：`fade-in` + `translateY(4px)`，时长 150ms，ease-out。
- 卡片 hover：轻微上浮 + 阴影加深，时长 200ms。
- 按钮 hover：背景色过渡 + scale(1.02)。
- 主题切换：颜色过渡 200ms。
- 加载条：保留现有顶部 loading bar，但加主题色适配。

## 6. 实施阶段

### Phase 1：主题系统（约 1-2 天）
1. 改造 `index.css`，定义三套完整 CSS 变量。
2. 创建 `ThemeProvider` + `useTheme` hook，处理初始化与切换。
3. 创建 `ThemeSwitcher` 组件，放入标题栏。
4. 扫一遍现有组件，把所有硬编码颜色替换为 CSS 变量。
5. 验证三套主题切换无闪烁、无残留色块。

### Phase 2：逻辑重构（约 2-3 天）
1. 拆分 `App.tsx` 为 `Layout`、`Sidebar`、`Workspace`、`PipelinePanel`。
2. 抽取 `useProjectActions`、`useAssetActions`、`useImportActions`、`useGeneration`。
3. 优化 store，拆分 refresh 方法，加独立 loading 状态。
4. 给列表项加 `React.memo`，章节列表加虚拟滚动（如需要）。
5. 实现章节编辑器自动保存与统一错误处理。

### Phase 3：响应式与动效（约 1-2 天）
1. 实现侧边栏/右面板折叠抽屉。
2. 加页面切换、卡片 hover、按钮、主题切换动效。
3. 多分辨率下人工测试布局。

## 7. 测试计划

- `npm run build` 必须成功。
- `npm run lint` 无新增警告。
- 手动验证三套主题下所有页面正常显示。
- 手动验证响应式断点（1920px、1440px、1024px、768px、375px）。
- 验证自动保存、主题持久化、项目切换等核心交互。

## 8. 风险与回退

- **风险**：CSS 变量遗漏导致某些组件在 dark-ai 主题下显示异常。
  - **缓解**：建立主题 token 检查清单，切换主题后逐项检查。
- **风险**：拆分时破坏现有交互。
  - **缓解**：每拆一个组件立即运行构建并手动验证对应功能。
- **风险**：自动保存高频触发导致后端压力。
  - **缓解**：debounce 1s，并在保存中加 loading 锁避免并发。

## 9. 验收标准

- [ ] 标题栏可一键切换三套主题，切换后全局颜色正确。
- [ ] 主题偏好刷新后保持不变。
- [ ] `App.tsx` 行数降至 200 行以内。
- [ ] 所有列表项使用 `React.memo` 或虚拟滚动。
- [ ] 章节编辑器支持自动保存。
- [ ] 1024px 以下右面板可折叠，768px 以下侧边栏可折叠。
- [ ] 构建、lint、测试全部通过。
