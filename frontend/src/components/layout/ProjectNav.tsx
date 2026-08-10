import { useCallback, useEffect, useRef, useState } from "react";
import { createPortal } from "react-dom";
import { useLocation, useNavigate, useParams } from "react-router-dom";
import { BookOpen, ChevronDown, Menu, Plus, Settings, Trash2, X } from "lucide-react";
import { useAppStore } from "@/store";
import { api } from "@/api";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Textarea } from "@/components/ui/textarea";
import { useMediaQuery } from "@/hooks/useMediaQuery";
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { HelpIcon } from "@/components/ui/help-icon";
import { helpTexts } from "@/help-texts";
import { useToast } from "@/hooks/useToast";
import { useConfirmDialog } from "@/hooks/useConfirmDialog";
import { cn } from "@/lib/utils";
import { ThemeSwitcher } from "@/components/theme-switcher";

/** 项目内主导航 */
const NAV_ITEMS = [
  { path: "chat", label: "对话" },
  { path: "write", label: "写作" },
  { path: "planning", label: "规划" },
  { path: "outlines", label: "大纲" },
  { path: "workflow", label: "工作流" },
  { path: "roundtable", label: "圆桌" },
  { path: "graph", label: "图谱" },
  { path: "timeline", label: "时间线" },
  { path: "assets", label: "资产" },
] as const;

/** 次级功能（收入"更多"下拉） */
const MORE_ITEMS = [
  { path: "dashboard", label: "工作台" },
  { path: "import", label: "导入" },
  { path: "export", label: "导出" },
  { path: "summaries", label: "摘要" },
  { path: "references", label: "参考" },
  { path: "stats", label: "统计" },
  { path: "encyclopedia", label: "百科卡" },
] as const;

export interface ProjectNavProps {
  leftSlot?: React.ReactNode;
  rightSlot?: React.ReactNode;
}

export function ProjectNav({ leftSlot, rightSlot }: ProjectNavProps = {}) {
  const navigate = useNavigate();
  const { projectId } = useParams<{ projectId: string }>();
  const location = useLocation();
  const project = useAppStore((s) => s.currentProject);
  const projects = useAppStore((s) => s.projects);
  const refreshProjects = useAppStore((s) => s.refreshProjects);
  const setCurrentProject = useAppStore((s) => s.setCurrentProject);
  const { showSuccess, showError } = useToast();
  const { confirm: confirmDelete, dialog: deleteDialog } = useConfirmDialog();

  const [projectDropdownOpen, setProjectDropdownOpen] = useState(false);
  const [moreOpen, setMoreOpen] = useState(false);
  const projectDropdownRef = useRef<HTMLDivElement>(null);
  const moreRef = useRef<HTMLDivElement>(null);
  const moreDropdownRef = useRef<HTMLDivElement>(null);

  // 移动壳：<768px 时使用抽屉导航
  const isMobile = useMediaQuery("(max-width: 767px)");
  const [mobileNavOpen, setMobileNavOpen] = useState(false);
  useEffect(() => {
    if (!mobileNavOpen) return;
    const onKey = (e: KeyboardEvent) => { if (e.key === "Escape") setMobileNavOpen(false); };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [mobileNavOpen]);

  // 新建项目弹窗
  const [createOpen, setCreateOpen] = useState(false);
  const [creating, setCreating] = useState(false);
  const [createForm, setCreateForm] = useState({ title: "", genre: "", summary: "" });

  // 首次加载项目列表
  useEffect(() => {
    if (projects.length === 0) {
      refreshProjects().catch(() => {});
    }
  }, [projects.length, refreshProjects]);

  // 点击外部关闭下拉
  useEffect(() => {
    function handleClick(e: MouseEvent) {
      if (projectDropdownRef.current && !projectDropdownRef.current.contains(e.target as Node)) {
        setProjectDropdownOpen(false);
      }
      // 「更多」下拉本体现在渲染在 body（portal）里，需一并排除，否则下拉内点击会被当成"点击外部"而关闭
      const inMore = moreRef.current?.contains(e.target as Node);
      const inMoreDropdown = moreDropdownRef.current?.contains(e.target as Node);
      if (inMore || inMoreDropdown) return;
      setMoreOpen(false);
    }
    document.addEventListener("mousedown", handleClick);
    return () => document.removeEventListener("mousedown", handleClick);
  }, []);

  const handleNavigate = (path: string) => {
    if (!projectId) return;
    navigate(`/projects/${projectId}/${path}`);
  };

  const isActive = (path: string) => location.pathname.includes(`/projects/${projectId}/${path}`);

  const handleSelectProject = (id: number) => {
    setProjectDropdownOpen(false);
    navigate(`/projects/${id}/chat`);
  };

  const handleCreateProject = useCallback(async () => {
    if (!createForm.title.trim()) {
      showError("请输入作品标题");
      return;
    }
    setCreating(true);
    try {
      const p = await api.createProject({
        title: createForm.title.trim(),
        genre: createForm.genre.trim() || "未分类",
        summary: createForm.summary.trim(),
      });
      await refreshProjects();
      setCurrentProject(p);
      showSuccess("项目创建成功");
      setCreateOpen(false);
      setCreateForm({ title: "", genre: "", summary: "" });
      navigate(`/projects/${p.id}/chat`);
    } catch (err: any) {
      showError("创建失败：" + (err?.message || "未知错误"));
    } finally {
      setCreating(false);
    }
  }, [createForm, navigate, refreshProjects, setCurrentProject, showSuccess, showError]);

  const handleDeleteCurrentProject = useCallback(async () => {
    if (!project) return;
    const ok = await confirmDelete({
      title: "删除项目",
      description: `项目「${project.title}」及其所有数据将被永久删除，此操作不可撤销。`,
      confirmText: "确认删除",
      cancelText: "取消",
      variant: "danger",
    });
    if (!ok) return;
    try {
      await api.deleteProject(project.id);
      await refreshProjects();
      showSuccess("项目已删除");
      // 删完后跳到剩余的第一个项目，或空状态
      const remaining = projects.filter((p) => p.id !== project.id);
      if (remaining.length > 0) {
        navigate(`/projects/${remaining[0].id}/chat`);
      } else {
        navigate("/");
      }
    } catch (e: any) {
      showError("删除失败：" + (e?.message || "未知错误"));
    }
  }, [project, projects, confirmDelete, navigate, refreshProjects, showSuccess, showError]);

  // 项目选择下拉（桌面 / 移动共用）
  const projectSelector = (
    <div className="relative min-w-0" ref={projectDropdownRef}>
      <button
        type="button"
        onClick={() => setProjectDropdownOpen((v) => !v)}
        className="flex min-w-0 items-center gap-1.5 rounded-lg px-2 py-1 text-sm font-semibold text-foreground transition-colors hover:bg-surface-hover"
        aria-label="切换项目"
      >
        <BookOpen className="h-4 w-4 shrink-0 text-primary" />
        <span className="max-w-[10rem] truncate">{project?.title || "选择作品"}</span>
        <ChevronDown className="h-3.5 w-3.5 shrink-0 text-muted" />
      </button>

      {projectDropdownOpen && (
        <div className="absolute left-0 top-full mt-2 w-72 max-w-[calc(100vw-16px)] rounded-lg border border-border bg-surface-elevated p-2 shadow-lg z-50">
          {/* 项目列表 */}
          <div className="mb-1 px-2 py-1 text-xs font-medium text-muted">切换项目</div>
          <div className="max-h-64 overflow-y-auto">
            {projects.map((p) => (
              <button
                key={p.id}
                type="button"
                onClick={() => handleSelectProject(p.id)}
                className={cn(
                  "flex w-full items-center gap-2 rounded-md px-2 py-1.5 text-left text-sm transition-colors",
                  p.id === project?.id
                    ? "bg-primary-muted text-primary"
                    : "text-foreground hover:bg-surface-hover"
                )}
              >
                <span className="truncate">{p.title}</span>
                {p.genre && (
                  <span className="ml-auto shrink-0 text-xs text-muted">{p.genre}</span>
                )}
              </button>
            ))}
          </div>

          {/* 底部操作 */}
          <div className="mt-1 border-t border-border pt-1 space-y-0.5">
            <button
              type="button"
              onClick={() => {
                setProjectDropdownOpen(false);
                setCreateOpen(true);
              }}
              className="flex w-full items-center gap-2 rounded-md px-2 py-1.5 text-left text-sm text-muted transition-colors hover:bg-surface-hover"
            >
              <Plus className="h-3.5 w-3.5" />
              新建项目
            </button>
            {project && (
              <button
                type="button"
                onClick={() => {
                  setProjectDropdownOpen(false);
                  void handleDeleteCurrentProject();
                }}
                className="flex w-full items-center gap-2 rounded-md px-2 py-1.5 text-left text-sm text-danger transition-colors hover:bg-danger/10"
              >
                <Trash2 className="h-3.5 w-3.5" />
                删除当前项目
              </button>
            )}
          </div>
        </div>
      )}
    </div>
  );

  return (
    <>
      <header className="flex h-14 shrink-0 items-center justify-between gap-2 border-b border-border bg-surface-elevated px-3 md:px-4">
        {isMobile ? (
          /* ===== 移动壳：☰ + 项目名 + 设置 ===== */
          <>
            <div className="flex min-w-0 flex-1 items-center gap-1">
              <button
                type="button"
                onClick={() => setMobileNavOpen(true)}
                className="inline-flex h-10 w-10 shrink-0 items-center justify-center rounded-lg text-foreground transition-colors hover:bg-surface-hover"
                aria-label="打开导航菜单"
              >
                <Menu className="h-5 w-5" />
              </button>
              {leftSlot}
              {projectSelector}
            </div>
            <div className="flex shrink-0 items-center gap-1">
              {rightSlot}
              <ThemeSwitcher />
              <Button
                variant="ghost"
                size="sm"
                className="h-10 w-10 px-0"
                onClick={() => navigate("/settings")}
                title="全局设置"
                aria-label="全局设置"
              >
                <Settings className="h-5 w-5" />
              </Button>
            </div>
          </>
        ) : (
          /* ===== 桌面版（保持原样） ===== */
          <>
            <div className="flex items-center gap-2">
              {leftSlot}

              {projectSelector}

              <HelpIcon title="顶部导航栏" content={helpTexts.common.projectNav} size="sm" />
            </div>

        {/* 中间：导航 tab */}
        <nav className="flex min-w-0 flex-1 items-center gap-0.5 overflow-x-auto">
          {NAV_ITEMS.map((item) => (
            <button
              key={item.path}
              type="button"
              onClick={() => handleNavigate(item.path)}
              className={cn(
                "inline-flex items-center justify-center rounded-lg px-2.5 py-1.5 text-sm font-medium transition-colors whitespace-nowrap",
                isActive(item.path)
                  ? "bg-primary text-primary-foreground"
                  : "text-muted hover:text-foreground hover:bg-surface-hover"
              )}
            >
              {item.label}
            </button>
          ))}
        </nav>

        {/* 右侧：更多 + 主题 + 设置 */}
        <div className="flex shrink-0 items-center gap-2">
          {/* 更多（固定在此处，避免被 nav 滚动容器裁剪） */}
          <div className="relative" ref={moreRef}>
            <button
              type="button"
              onClick={() => setMoreOpen((v) => !v)}
              className={cn(
                "inline-flex items-center gap-1 whitespace-nowrap rounded-lg px-3 py-1.5 text-sm font-medium transition-colors",
                MORE_ITEMS.some((item) => isActive(item.path))
                  ? "bg-primary-muted text-primary"
                  : "text-muted hover:text-foreground hover:bg-surface-hover"
              )}
            >
              更多
              <ChevronDown className="h-3.5 w-3.5" />
            </button>
            {moreOpen &&
              createPortal(
                <div
                  ref={moreDropdownRef}
                  className="absolute right-0 top-full mt-2 w-40 rounded-lg border border-border bg-surface-elevated p-1 shadow-lg z-50"
                  style={{
                    position: "fixed",
                    top: (moreRef.current?.getBoundingClientRect().bottom ?? 0) + 8,
                    right: window.innerWidth - (moreRef.current?.getBoundingClientRect().right ?? 0),
                  }}
                >
                  {MORE_ITEMS.map((item) => (
                    <button
                      key={item.path}
                      type="button"
                      onClick={() => {
                        handleNavigate(item.path);
                        setMoreOpen(false);
                      }}
                      className={cn(
                        "flex w-full items-center rounded-md px-2 py-1.5 text-left text-sm transition-colors",
                        isActive(item.path)
                          ? "bg-primary-muted text-primary"
                          : "text-foreground hover:bg-surface-hover"
                      )}
                    >
                      {item.label}
                    </button>
                  ))}
                </div>,
                document.body
              )}
          </div>
          {rightSlot}
          <ThemeSwitcher />
          <Button
            variant="ghost"
            size="sm"
            className="h-8 w-8 px-0"
            onClick={() => navigate("/settings")}
            title="全局设置"
          >
            <Settings className="h-4 w-4" />
          </Button>
        </div>
        </>
        )}
      </header>

      {/* 移动端抽屉导航（<768px） */}
      {isMobile && mobileNavOpen && (
        <div className="fixed inset-0 z-50 md:hidden" role="dialog" aria-modal="true" aria-label="导航菜单">
          <div className="absolute inset-0 bg-black/40" onClick={() => setMobileNavOpen(false)} aria-hidden="true" />
          <div className="absolute left-0 top-0 bottom-0 w-72 max-w-[85vw] overflow-y-auto border-r border-border bg-surface-elevated shadow-xl">
            <div className="flex h-14 items-center justify-between border-b border-border px-4">
              <span className="text-sm font-semibold text-foreground">NovelAgent</span>
              <button
                type="button"
                onClick={() => setMobileNavOpen(false)}
                className="inline-flex h-10 w-10 items-center justify-center rounded-lg text-foreground transition-colors hover:bg-surface-hover"
                aria-label="关闭菜单"
              >
                <X className="h-5 w-5" />
              </button>
            </div>
            <div className="p-2">
              <div className="px-3 py-1.5 text-xs font-medium text-muted">导航</div>
              {NAV_ITEMS.map((item) => (
                <button
                  key={item.path}
                  type="button"
                  onClick={() => {
                    handleNavigate(item.path);
                    setMobileNavOpen(false);
                  }}
                  className={cn(
                    "flex min-h-[44px] w-full items-center rounded-lg px-3 py-2.5 text-left text-sm transition-colors",
                    isActive(item.path)
                      ? "bg-primary text-primary-foreground"
                      : "text-foreground hover:bg-surface-hover"
                  )}
                >
                  {item.label}
                </button>
              ))}
              <div className="mt-2 px-3 py-1.5 text-xs font-medium text-muted">更多功能</div>
              {MORE_ITEMS.map((item) => (
                <button
                  key={item.path}
                  type="button"
                  onClick={() => {
                    handleNavigate(item.path);
                    setMobileNavOpen(false);
                  }}
                  className={cn(
                    "flex min-h-[44px] w-full items-center rounded-lg px-3 py-2.5 text-left text-sm transition-colors",
                    isActive(item.path)
                      ? "bg-primary-muted text-primary"
                      : "text-foreground hover:bg-surface-hover"
                  )}
                >
                  {item.label}
                </button>
              ))}
            </div>
          </div>
        </div>
      )}

      {/* 新建项目弹窗 */}
      <Dialog open={createOpen} onOpenChange={setCreateOpen}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>新建项目</DialogTitle>
          </DialogHeader>
          <form
            onSubmit={(e) => {
              e.preventDefault();
              void handleCreateProject();
            }}
            className="space-y-4"
          >
            <div className="space-y-1.5">
              <span className="text-sm font-medium">作品标题</span>
              <Input
                placeholder="请输入作品标题"
                value={createForm.title}
                onChange={(e) => setCreateForm((f) => ({ ...f, title: e.target.value }))}
                autoFocus
              />
            </div>
            <div className="space-y-1.5">
              <span className="text-sm font-medium">类型</span>
              <Input
                placeholder="如：玄幻 / 科幻 / 都市"
                value={createForm.genre}
                onChange={(e) => setCreateForm((f) => ({ ...f, genre: e.target.value }))}
              />
            </div>
            <div className="space-y-1.5">
              <span className="text-sm font-medium">一句话简介</span>
              <Textarea
                placeholder="简单描述一下作品..."
                value={createForm.summary}
                onChange={(e) => setCreateForm((f) => ({ ...f, summary: e.target.value }))}
                rows={3}
              />
            </div>
            <div className="flex justify-end gap-2 pt-2">
              <Button
                type="button"
                variant="outline"
                onClick={() => { setCreateOpen(false); setCreateForm({ title: "", genre: "", summary: "" }); }}
                disabled={creating}
              >
                取消
              </Button>
              <Button type="submit" variant="primary" disabled={creating || !createForm.title.trim()}>
                {creating ? "创建中..." : "创建"}
              </Button>
            </div>
          </form>
        </DialogContent>
      </Dialog>

      {deleteDialog}
    </>
  );
}
