# Phase 1：主题系统实现计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 实现三套可切换主题（light-glass / warm-paper / dark-ai），包括 CSS 变量体系、主题切换器、localStorage 持久化，并让所有现有组件正确应用主题色。

**架构：** 使用 `html[data-theme="..."]` 驱动 CSS 变量，配合 `useTheme` hook 管理状态与持久化。所有颜色/阴影/圆角从 CSS 变量读取，组件中不再硬编码色值。

**Tech Stack:** React + TypeScript + Tailwind CSS v4 + lucide-react + Vite

---

## 文件结构

| 文件 | 职责 |
|---|---|
| `frontend/src/index.css` | 定义三套主题 CSS 变量、基础样式、工具类 |
| `frontend/src/hooks/useTheme.ts` | 主题状态管理、localStorage 读写、初始化 |
| `frontend/src/components/theme-switcher.tsx` | 主题切换按钮与选择面板 |
| `frontend/src/lib/theme.ts` | 主题类型定义与常量 |
| `frontend/src/App.tsx` | 接入 ThemeProvider 与 ThemeSwitcher |
| `frontend/src/components/ui/*.tsx` | 更新为使用 CSS 变量 |
| `frontend/src/views/*.tsx` | 移除硬编码颜色，改用 CSS 变量 |

---

### Task 1: 主题类型与常量定义

**Files:**
- Create: `frontend/src/lib/theme.ts`

- [ ] **Step 1: 编写主题类型与常量**

```typescript
export type ThemeKey = "light-glass" | "warm-paper" | "dark-ai";

export interface ThemeOption {
  key: ThemeKey;
  label: string;
  icon: "sun" | "book-open" | "moon";
  description: string;
}

export const THEMES: ThemeOption[] = [
  {
    key: "light-glass",
    label: "精致浅色",
    icon: "sun",
    description: "浅灰玻璃风，默认",
  },
  {
    key: "warm-paper",
    label: "温暖纸墨",
    icon: "book-open",
    description: "米白护眼写作风",
  },
  {
    key: "dark-ai",
    label: "深色 AI",
    icon: "moon",
    description: "深色科技指挥风",
  },
];

export const STORAGE_KEY = "novel-agent-theme";
export const DEFAULT_THEME: ThemeKey = "light-glass";

export function isValidTheme(value: string): value is ThemeKey {
  return THEMES.some((t) => t.key === value);
}
```

- [ ] **Step 2: Commit**

```bash
git add frontend/src/lib/theme.ts
git commit -m "feat(theme): add theme types and constants"
```

---

### Task 2: useTheme Hook

**Files:**
- Create: `frontend/src/hooks/useTheme.ts`
- Modify: `frontend/src/App.tsx`（后续 Task 中接入）

- [ ] **Step 1: 编写 useTheme hook**

```typescript
import { useEffect, useState, useCallback } from "react";
import { type ThemeKey, DEFAULT_THEME, STORAGE_KEY, isValidTheme } from "@/lib/theme";

export function useTheme() {
  const [theme, setThemeState] = useState<ThemeKey>(() => {
    if (typeof window === "undefined") return DEFAULT_THEME;
    const saved = localStorage.getItem(STORAGE_KEY);
    return saved && isValidTheme(saved) ? saved : DEFAULT_THEME;
  });

  const [mounted, setMounted] = useState(false);

  useEffect(() => {
    setMounted(true);
  }, []);

  const setTheme = useCallback((newTheme: ThemeKey) => {
    setThemeState(newTheme);
    localStorage.setItem(STORAGE_KEY, newTheme);
    document.documentElement.setAttribute("data-theme", newTheme);
  }, []);

  useEffect(() => {
    document.documentElement.setAttribute("data-theme", theme);
  }, [theme]);

  return { theme, setTheme, mounted };
}
```

- [ ] **Step 2: Commit**

```bash
git add frontend/src/hooks/useTheme.ts
git commit -m "feat(theme): add useTheme hook with localStorage persistence"
```

---

### Task 3: ThemeSwitcher 组件

**Files:**
- Create: `frontend/src/components/theme-switcher.tsx`
- Requires: `frontend/src/lib/theme.ts`, `frontend/src/hooks/useTheme.ts`

- [ ] **Step 1: 编写 ThemeSwitcher 组件**

```typescript
import { useState, useRef, useEffect } from "react";
import { Sun, Moon, BookOpen, Palette, Check } from "lucide-react";
import { Button } from "@/components/ui/button";
import { cn } from "@/lib/utils";
import { THEMES, type ThemeKey } from "@/lib/theme";
import { useTheme } from "@/hooks/useTheme";

const ICONS: Record<ThemeKey, typeof Sun> = {
  "light-glass": Sun,
  "warm-paper": BookOpen,
  "dark-ai": Moon,
};

export function ThemeSwitcher() {
  const { theme, setTheme, mounted } = useTheme();
  const [open, setOpen] = useState(false);
  const ref = useRef<HTMLDivElement>(null);

  useEffect(() => {
    function handleClickOutside(e: MouseEvent) {
      if (ref.current && !ref.current.contains(e.target as Node)) {
        setOpen(false);
      }
    }
    document.addEventListener("mousedown", handleClickOutside);
    return () => document.removeEventListener("mousedown", handleClickOutside);
  }, []);

  if (!mounted) return null;

  const ActiveIcon = ICONS[theme];

  return (
    <div className="relative" ref={ref}>
      <Button
        variant="ghost"
        size="sm"
        onClick={() => setOpen(!open)}
        className="gap-1.5"
        aria-label="切换主题"
      >
        <ActiveIcon className="h-4 w-4" />
        <span className="hidden sm:inline text-xs">主题</span>
      </Button>

      {open && (
        <div className="absolute right-0 top-full mt-2 w-56 rounded-xl border border-border bg-surface p-2 shadow-lg z-50 animate-in fade-in slide-in-from-top-1 duration-150">
          <div className="text-xs font-medium text-muted px-2 py-1.5">选择主题</div>
          {THEMES.map((t) => {
            const Icon = ICONS[t.key];
            const active = theme === t.key;
            return (
              <button
                key={t.key}
                onClick={() => {
                  setTheme(t.key);
                  setOpen(false);
                }}
                className={cn(
                  "w-full flex items-center gap-3 px-2 py-2 rounded-lg text-left transition-colors",
                  active ? "bg-primary/10 text-primary" : "hover:bg-black/5 text-foreground"
                )}
              >
                <div className={cn(
                  "w-8 h-8 rounded-lg flex items-center justify-center border",
                  active ? "border-primary bg-primary/10" : "border-border bg-surface-elevated"
                )}>
                  <Icon className="h-4 w-4" />
                </div>
                <div className="flex-1 min-w-0">
                  <div className="text-sm font-medium">{t.label}</div>
                  <div className="text-xs text-muted truncate">{t.description}</div>
                </div>
                {active && <Check className="h-4 w-4 text-primary" />}
              </button>
            );
          })}
        </div>
      )}
    </div>
  );
}
```

- [ ] **Step 2: Commit**

```bash
git add frontend/src/components/theme-switcher.tsx
git commit -m "feat(theme): add ThemeSwitcher component"
```

---

### Task 4: CSS 变量体系（light-glass）

**Files:**
- Modify: `frontend/src/index.css`

- [ ] **Step 1: 重构 index.css 为 light-glass 变量基础**

将现有 `@theme` 块迁移到 `html[data-theme="light-glass"]`，并补充过渡动画与工具类：

```css
@import "tailwindcss";

html[data-theme="light-glass"] {
  --background: #f5f5f7;
  --surface: rgba(255, 255, 255, 0.78);
  --surface-elevated: rgba(255, 255, 255, 0.92);
  --surface-hover: rgba(255, 255, 255, 0.9);
  --border: rgba(0, 0, 0, 0.08);
  --border-strong: rgba(0, 0, 0, 0.14);
  --foreground: #1d1d1f;
  --muted: #6e6e73;
  --primary: #0071e3;
  --primary-hover: #0077ed;
  --primary-foreground: #ffffff;
  --danger: #ff3b30;
  --success: #34c759;
  --warning: #ff9500;
  --radius: 0.875rem;
  --shadow-sm: 0 2px 8px rgba(0,0,0,0.04);
  --shadow: 0 8px 24px rgba(0,0,0,0.08);
  --shadow-lg: 0 16px 48px rgba(0,0,0,0.12);
}

@theme {
  --color-background: var(--background);
  --color-surface: var(--surface);
  --color-surface-elevated: var(--surface-elevated);
  --color-surface-hover: var(--surface-hover);
  --color-border: var(--border);
  --color-border-strong: var(--border-strong);
  --color-foreground: var(--foreground);
  --color-muted: var(--muted);
  --color-primary: var(--primary);
  --color-primary-hover: var(--primary-hover);
  --color-primary-foreground: var(--primary-foreground);
  --color-danger: var(--danger);
  --color-success: var(--success);
  --color-warning: var(--warning);
  --radius: var(--radius);
}

@layer base {
  * {
    @apply border-border;
  }
  html, body, #root {
    @apply h-full w-full overflow-hidden;
    background: var(--background);
    color: var(--foreground);
    font-family: -apple-system, BlinkMacSystemFont, "SF Pro Text", "Segoe UI", "PingFang SC", "Microsoft YaHei", sans-serif;
    transition: background-color 0.2s ease, color 0.2s ease;
  }
}
```

保留并适配现有的 `.glass`、`.editor-surface`、滚动条、loading 动画等工具类，但将其颜色改为使用 CSS 变量。

- [ ] **Step 2: 运行构建验证无报错**

Run: `cd frontend && npm run build`
Expected: 成功

- [ ] **Step 3: Commit**

```bash
git add frontend/src/index.css
git commit -m "feat(theme): refactor index.css to CSS variable tokens for light-glass"
```

---

### Task 5: warm-paper 主题变量

**Files:**
- Modify: `frontend/src/index.css`

- [ ] **Step 1: 添加 warm-paper 主题变量**

在 `index.css` 中 light-glass 之后追加：

```css
html[data-theme="warm-paper"] {
  --background: #faf8f5;
  --surface: rgba(255, 255, 255, 0.9);
  --surface-elevated: #ffffff;
  --surface-hover: rgba(255, 251, 245, 0.95);
  --border: rgba(120, 110, 95, 0.12);
  --border-strong: rgba(120, 110, 95, 0.2);
  --foreground: #2c241b;
  --muted: #7a6f63;
  --primary: #b45309;
  --primary-hover: #92400e;
  --primary-foreground: #ffffff;
  --danger: #dc2626;
  --success: #15803d;
  --warning: #d97706;
  --radius: 0.75rem;
  --shadow-sm: 0 2px 6px rgba(60, 45, 30, 0.04);
  --shadow: 0 6px 20px rgba(60, 45, 30, 0.08);
  --shadow-lg: 0 14px 40px rgba(60, 45, 30, 0.12);
}
```

- [ ] **Step 2: Commit**

```bash
git add frontend/src/index.css
git commit -m "feat(theme): add warm-paper theme tokens"
```

---

### Task 6: dark-ai 主题变量

**Files:**
- Modify: `frontend/src/index.css`

- [ ] **Step 1: 添加 dark-ai 主题变量**

```css
html[data-theme="dark-ai"] {
  --background: #0f1117;
  --surface: rgba(30, 33, 42, 0.72);
  --surface-elevated: rgba(38, 42, 54, 0.9);
  --surface-hover: rgba(46, 51, 66, 0.85);
  --border: rgba(255, 255, 255, 0.08);
  --border-strong: rgba(255, 255, 255, 0.14);
  --foreground: #f0f2f5;
  --muted: #9aa3b2;
  --primary: #8b5cf6;
  --primary-hover: #7c3aed;
  --primary-foreground: #ffffff;
  --danger: #f87171;
  --success: #4ade80;
  --warning: #fbbf24;
  --radius: 0.875rem;
  --shadow-sm: 0 2px 8px rgba(0,0,0,0.3);
  --shadow: 0 8px 24px rgba(0,0,0,0.4);
  --shadow-lg: 0 16px 48px rgba(0,0,0,0.5);
}
```

注意：dark-ai 下需要覆盖 `.glass`、`.editor-surface` 等工具类为深色模式适配版本。可以通过 `:is([data-theme="dark-ai"]) .glass { ... }` 追加覆盖。

- [ ] **Step 2: Commit**

```bash
git add frontend/src/index.css
git commit -m "feat(theme): add dark-ai theme tokens"
```

---

### Task 7: 玻璃/编辑器/滚动条工具类适配多主题

**Files:**
- Modify: `frontend/src/index.css`

- [ ] **Step 1: 重构工具类使用 CSS 变量**

```css
@layer utilities {
  .glass {
    background: var(--surface);
    backdrop-filter: blur(24px) saturate(180%);
    -webkit-backdrop-filter: blur(24px) saturate(180%);
    border: 1px solid var(--border-strong);
    box-shadow: var(--shadow);
  }
  .glass-elevated {
    background: var(--surface-elevated);
    backdrop-filter: blur(32px) saturate(200%);
    -webkit-backdrop-filter: blur(32px) saturate(200%);
    border: 1px solid var(--border-strong);
    box-shadow: var(--shadow-lg);
  }
  .editor-surface {
    background: var(--surface-elevated);
    color: var(--foreground);
  }
}
```

滚动条颜色也改用变量，确保 dark-ai 下不显灰：

```css
::-webkit-scrollbar-thumb {
  background: var(--border-strong);
  border-radius: 999px;
}
::-webkit-scrollbar-thumb:hover {
  background: var(--muted);
}
```

- [ ] **Step 2: 运行构建验证**

Run: `cd frontend && npm run build`
Expected: 成功

- [ ] **Step 3: Commit**

```bash
git add frontend/src/index.css
git commit -m "refactor(theme): adapt utility classes to CSS variables"
```

---

### Task 8: UI 组件颜色 Token 化

**Files:**
- Modify: `frontend/src/components/ui/button.tsx`
- Modify: `frontend/src/components/ui/card.tsx`
- Modify: `frontend/src/components/ui/input.tsx`
- Modify: `frontend/src/components/ui/textarea.tsx`
- Modify: `frontend/src/components/ui/select.tsx`
- Modify: `frontend/src/components/ui/badge.tsx`
- Modify: `frontend/src/components/ui/dialog.tsx`

- [ ] **Step 1: 逐个检查并替换硬编码色值**

以 `button.tsx` 为例，将所有 `bg-white` / `bg-black` / `text-white` 等替换为 CSS 变量对应 Tailwind 类，例如：

```tsx
// 之前
"bg-white text-black hover:bg-gray-100"
// 之后
"bg-surface text-foreground hover:bg-surface-hover"
```

确保 `variant="primary"` 使用 `bg-primary text-primary-foreground hover:bg-primary-hover`。
确保 `variant="danger"` / `variant="outline"` 等也使用对应变量。

- [ ] **Step 2: 对所有 UI 组件重复上述替换**

关键替换映射：
- `bg-white` → `bg-surface` 或 `bg-surface-elevated`
- `bg-black/5` → `bg-foreground/5`
- `bg-black/10` → `bg-foreground/10`
- `text-gray-*` / `text-muted-foreground` → `text-muted`
- `border-gray-*` → `border-border` / `border-border-strong`
- `shadow-sm` / `shadow` / `shadow-lg` → 保留 Tailwind 类，必要时改为 `shadow-[var(--shadow)]`

- [ ] **Step 3: 运行构建验证**

Run: `cd frontend && npm run build`
Expected: 成功

- [ ] **Step 4: Commit**

```bash
git add frontend/src/components/ui/*.tsx
git commit -m "refactor(theme): tokenize UI component colors"
```

---

### Task 9: 接入 ThemeProvider 与 ThemeSwitcher

**Files:**
- Modify: `frontend/src/App.tsx`

- [ ] **Step 1: 在 App.tsx 中引入并渲染 ThemeSwitcher**

```typescript
import { ThemeSwitcher } from "@/components/theme-switcher";
```

在标题栏右侧区域（当前显示 success/error/pipeline status 的位置）插入：

```tsx
<div className="flex items-center gap-2 no-drag">
  <ThemeSwitcher />
  {success && <span className="text-xs text-success">{success}</span>}
  {error && <span className="text-xs text-danger">{error}</span>}
  {pipelineStatus === "running" && <Loader2 className="h-3 w-3 animate-spin text-primary" />}
</div>
```

- [ ] **Step 2: 确保 useTheme 在 App 组件内生效**

由于 `useTheme` 通过 localStorage 和 `document.documentElement` 工作，不需要传统 Context Provider。只需确保 `ThemeSwitcher` 被渲染，首次加载时 `useEffect` 会设置 `data-theme`。

- [ ] **Step 3: 运行 dev 服务验证切换器可见**

Run: `cd frontend && npm run dev`（已运行则刷新）
Expected: 标题栏出现"主题"按钮，点击弹出三个选项

- [ ] **Step 4: Commit**

```bash
git add frontend/src/App.tsx
git commit -m "feat(theme): integrate ThemeSwitcher into title bar"
```

---

### Task 10: 视图组件颜色 Token 化

**Files:**
- Modify: `frontend/src/views/DashboardView.tsx`
- Modify: `frontend/src/views/ChapterEditorView.tsx`
- Modify: `frontend/src/views/PlanningView.tsx`
- Modify: `frontend/src/views/SummariesView.tsx`
- Modify: `frontend/src/views/ImportView.tsx`
- Modify: `frontend/src/views/ExportView.tsx`
- Modify: `frontend/src/views/AssetEditorView.tsx`
- Modify: `frontend/src/components/*.tsx`（world-view, characters-view, outlines-view 等）

- [ ] **Step 1: 扫描并替换所有硬编码颜色**

常见模式：
- `bg-white/40` → `bg-surface`
- `bg-blue-50` / `bg-amber-50` / `bg-red-50` → 使用语义化的 `bg-primary/10`、`bg-warning/10`、`bg-danger/10`
- `text-blue-700` / `text-amber-700` → `text-primary`、`text-warning`
- `hover:bg-black/5` → `hover:bg-foreground/5`
- `border-white/60` → `border-border`

- [ ] **Step 2: 处理 dark-ai 下的特殊元素**

检查所有使用 `rgba(...)` 或十六进制色值的 inline style，改为使用 CSS 变量或 Tailwind 类。例如：

```tsx
// 之前
<div className="rounded-lg border p-2 bg-white/40">
// 之后
<div className="rounded-lg border border-border bg-surface p-2">
```

- [ ] **Step 3: 运行构建验证**

Run: `cd frontend && npm run build`
Expected: 成功

- [ ] **Step 4: Commit**

```bash
git add frontend/src/views/*.tsx frontend/src/components/*.tsx
git commit -m "refactor(theme): tokenize views and components colors"
```

---

### Task 11: 主题切换过渡动画

**Files:**
- Modify: `frontend/src/index.css`

- [ ] **Step 1: 为常见属性添加过渡**

```css
@layer base {
  *, *::before, *::after {
    transition-property: background-color, border-color, color, fill, stroke, box-shadow;
    transition-duration: 150ms;
    transition-timing-function: ease-out;
  }
}
```

注意：这会全局加过渡，需排除 `textarea` / `input` 等需要即时反馈的元素：

```css
input, textarea, button {
  transition-property: background-color, border-color, color, box-shadow, transform;
}
```

- [ ] **Step 2: 验证切换时无闪烁**

手动点击三种主题，观察颜色是否平滑过渡。

- [ ] **Step 3: Commit**

```bash
git add frontend/src/index.css
git commit -m "feat(theme): add smooth theme transition animations"
```

---

### Task 12: 三套主题人工检查清单

**Files:**
- All `frontend/src/**/*.tsx`

- [ ] **Step 1: 按检查表逐项验证**

在浏览器中依次切换 light-glass / warm-paper / dark-ai，检查：
- [ ] 侧边栏背景、文字、选中态颜色正确
- [ ] 项目下拉框、搜索框颜色正确
- [ ] Dashboard 统计卡片、一致性看板、题材上下文卡片颜色正确
- [ ] 章节编辑器正文区、tab 按钮、工具栏颜色正确
- [ ] 卷级规划、摘要、导入导出页面颜色正确
- [ ] 所有 Button / Input / Textarea / Card / Badge / Dialog 在三主题下可读
- [ ] dark-ai 主题下无"死黑"或"死白"残留
- [ ] Toast 提示文字在三主题下可读

- [ ] **Step 2: 修复发现的残留硬编码颜色**

- [ ] **Step 3: 运行最终构建**

Run: `cd frontend && npm run build`
Expected: 成功

- [ ] **Step 4: Commit**

```bash
git add .
git commit -m "fix(theme): resolve remaining hardcoded colors across themes"
```

---

## Spec 覆盖自查

| Spec 要求 | 对应 Task |
|---|---|
| 三套主题定义 | Task 1, 4, 5, 6 |
| CSS 变量驱动 | Task 4 |
| localStorage 持久化 | Task 2 |
| 主题切换器 | Task 3, 9 |
| 所有组件颜色 token 化 | Task 8, 10, 12 |
| 切换动画 | Task 11 |

---

## 验收标准

- [ ] 标题栏出现主题切换按钮，点击可切换 light-glass / warm-paper / dark-ai
- [ ] 切换主题后刷新页面，主题保持不变
- [ ] 三套主题下所有页面无残留硬编码颜色导致的可读性问题
- [ ] `npm run build` 成功
- [ ] `npm run lint` 无新增警告
