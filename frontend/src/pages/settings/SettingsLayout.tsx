/** 全局设置 · 布局组件：顶栏（返回 + 标题 + 主题切换）+ 左侧子导航 + 右侧内容区（Outlet） */
import { Outlet, useLocation, useNavigate } from "react-router-dom";
import {
  Archive,
  ArrowLeft,
  BookOpen,
  Bot,
  Boxes,
  Clock,
  Cpu,
  FileCode,
  FlaskConical,
  FolderOpen,
  LayoutDashboard,
  ScrollText,
  UserRound,
  type LucideIcon,
} from "lucide-react";
import { Button } from "@/components/ui/button";
import { ThemeSwitcher } from "@/components/theme-switcher";
import { useAppStore } from "@/store";
import { cn } from "@/lib/utils";

interface NavItem {
  label: string;
  icon: LucideIcon;
  path: string;
}

const NAV_ITEMS: NavItem[] = [
  { label: "概览", icon: LayoutDashboard, path: "/settings" },
  { label: "模型管理", icon: Cpu, path: "/settings/models" },
  { label: "Agent 定义", icon: Bot, path: "/settings/orchestration" },
  { label: "Prompt 编排", icon: FileCode, path: "/settings/orchestration" },
  { label: "Skills 管理", icon: BookOpen, path: "/settings/skills" },
  { label: "Rules 管理", icon: ScrollText, path: "/settings/rules" },
  { label: "插件管理", icon: Boxes, path: "/settings/plugins" },
  { label: "定时任务", icon: Clock, path: "/settings/cron" },
  { label: "压缩监控", icon: Archive, path: "/settings/compression" },
  { label: "工作区", icon: FolderOpen, path: "/settings/workspace" },
  { label: "蒸馏技能", icon: FlaskConical, path: "/settings/distillation" },
  { label: "用户注入", icon: UserRound, path: "/settings/injection" },
];

export default function SettingsLayout() {
  const location = useLocation();
  const navigate = useNavigate();
  const pathname = location.pathname;
  const projects = useAppStore((s) => s.projects);

  const isActive = (path: string) =>
    path === "/settings" ? pathname === "/settings" : pathname === path;

  // 返回：优先跳到最近项目的对话页，没有项目则跳项目列表（RootRedirect 会处理）
  const handleBack = () => {
    if (projects.length > 0) {
      const sorted = [...projects].sort(
        (a, b) => new Date(b.updated_at).getTime() - new Date(a.updated_at).getTime()
      );
      navigate(`/projects/${sorted[0].id}/chat`);
    } else {
      navigate("/");
    }
  };

  return (
    <div className="flex h-screen w-screen flex-col overflow-hidden bg-background">
      {/* 顶栏 */}
      <header className="flex h-14 shrink-0 items-center justify-between border-b border-border bg-surface px-4">
        <div className="flex items-center gap-3">
          <Button variant="ghost" size="sm" onClick={handleBack}>
            <ArrowLeft className="h-4 w-4" />
            返回
          </Button>
          <div className="h-5 w-px bg-border" />
          <h1 className="text-base font-semibold">全局设置</h1>
        </div>
        <ThemeSwitcher />
      </header>

      <div className="flex flex-1 overflow-hidden">
        {/* 左侧子导航 */}
        <aside className="w-56 shrink-0 overflow-y-auto border-r border-border bg-surface">
          <nav className="space-y-1 p-3" aria-label="设置子导航">
            {NAV_ITEMS.map((item) => {
              const active = isActive(item.path);
              const Icon = item.icon;
              return (
                <button
                  key={item.label}
                  type="button"
                  onClick={() => navigate(item.path)}
                  aria-current={active ? "page" : undefined}
                  className={cn(
                    "flex w-full items-center gap-2.5 rounded-lg px-3 py-2 text-sm transition-colors",
                    active
                      ? "bg-primary-muted font-medium text-primary"
                      : "text-muted hover:bg-surface-hover hover:text-foreground",
                  )}
                >
                  <Icon className="h-4 w-4 shrink-0" />
                  <span className="truncate">{item.label}</span>
                </button>
              );
            })}
          </nav>
        </aside>

        {/* 右侧内容区 */}
        <main className="min-w-0 flex-1 overflow-hidden">
          <Outlet />
        </main>
      </div>
    </div>
  );
}
