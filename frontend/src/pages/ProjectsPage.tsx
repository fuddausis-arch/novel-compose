import { useCallback, useEffect, useMemo, useState } from "react";
import { useNavigate } from "react-router-dom";
import { Plus, ArrowUpDown } from "lucide-react";

import { AppLayout } from "@/components/layout/AppLayout";
import { ProjectCard } from "@/components/projects/ProjectCard";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Textarea } from "@/components/ui/textarea";
import { SearchInput } from "@/components/ui/search-input";
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { useToast } from "@/hooks/useToast";
import { useConfirmDialog } from "@/hooks/useConfirmDialog";
import { useAppStore } from "@/store";
import { api } from "@/api";
import type { Project } from "@/types";

export default function ProjectsPage() {
  const navigate = useNavigate();
  const { showSuccess, showError } = useToast();
  const { confirm: confirmDelete, dialog: deleteDialog } = useConfirmDialog();
  const projects = useAppStore((state) => state.projects);
  const refreshProjects = useAppStore((state) => state.refreshProjects);
  const setCurrentProject = useAppStore((state) => state.setCurrentProject);
  const [query, setQuery] = useState("");
  const [open, setOpen] = useState(false);
  const [creating, setCreating] = useState(false);
  const [form, setForm] = useState({ title: "", genre: "", summary: "" });
  const [sortKey, setSortKey] = useState<"updated" | "title" | "created">("updated");

  const handleDeleteProject = useCallback(
    async (project: Project) => {
      const ok = await confirmDelete({
        title: "删除项目",
        description: `项目「${project.title}」及其所有圣经数据将被永久删除，此操作不可撤销。`,
        confirmText: "确认删除",
        cancelText: "取消",
        variant: "danger",
      });
      if (!ok) return;
      try {
        await api.deleteProject(project.id);
        await refreshProjects();
        showSuccess("项目已删除");
      } catch (e: any) {
        showError("删除失败：" + (e?.message || "未知错误"));
      }
    },
    [confirmDelete, refreshProjects, showSuccess, showError]
  );

  useEffect(() => {
    refreshProjects().catch((err) => {
      showError(err instanceof Error ? err.message : "加载作品列表失败");
    });
  }, [refreshProjects, showError]);

  const filteredProjects = useMemo(() => {
    const q = query.trim().toLowerCase();
    const filtered = !q ? projects : projects.filter((p) => p.title.toLowerCase().includes(q));
    const sorted = [...filtered].sort((a, b) => {
      if (sortKey === "title") return a.title.localeCompare(b.title, "zh");
      if (sortKey === "created") {
        return new Date(b.created_at).getTime() - new Date(a.created_at).getTime();
      }
      // updated
      return new Date(b.updated_at).getTime() - new Date(a.updated_at).getTime();
    });
    return sorted;
  }, [projects, query, sortKey]);

  const sortLabel = sortKey === "updated" ? "按更新时间排序" : sortKey === "title" ? "按标题排序" : "按创建时间排序";
  const cycleSortKey = () => {
    setSortKey((prev) => (prev === "updated" ? "title" : prev === "title" ? "created" : "updated"));
  };

  return (
    <AppLayout hideNav>
      <div className="flex h-full flex-col overflow-hidden bg-background">
        <header className="flex items-center justify-between border-b border-border px-6 py-4">
          <div className="flex items-center gap-2">
            <div>
              <h1 className="text-xl font-bold text-foreground">我的作品</h1>
              <p className="text-sm text-muted">共 {projects.length} 个项目</p>
            </div>
          </div>

          <div className="flex items-center gap-2">
            <Button variant="primary" onClick={() => setOpen(true)}>
              <Plus className="mr-1 h-4 w-4" />
              新建项目
            </Button>
          </div>
        </header>

        <div className="flex items-center gap-3 border-b border-border px-6 py-3">
          <SearchInput
            value={query}
            onChange={setQuery}
            placeholder="搜索作品..."
            className="flex-1 max-w-md"
            inputClassName="pl-9"
            iconClassName="h-4 w-4"
          />

          <Button variant="outline" size="sm" onClick={cycleSortKey}>
            <ArrowUpDown className="mr-1 h-4 w-4" />
            {sortLabel}
          </Button>
        </div>

        <div className="flex-1 overflow-y-auto p-6">
          <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-3">
            {filteredProjects.map((project) => (
              <ProjectCard
                key={project.id}
                project={project}
                onClick={() => navigate(`/projects/${project.id}/dashboard`)}
                onDelete={handleDeleteProject}
              />
            ))}

            <div
              onClick={() => setOpen(true)}
              className="flex flex-col items-center justify-center rounded-xl border border-dashed border-border-strong p-4 text-muted hover:bg-surface-elevated cursor-pointer"
            >
              <Plus className="h-6 w-6" />
              <span className="mt-2 text-sm font-medium">创建新项目</span>
            </div>
          </div>
        </div>
      </div>

      <Dialog open={open} onOpenChange={setOpen}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>新建项目</DialogTitle>
          </DialogHeader>
          <form
            onSubmit={async (e) => {
              e.preventDefault();
              if (!form.title.trim()) {
                showError("请输入作品标题");
                return;
              }
              setCreating(true);
              try {
                const p = await api.createProject({
                  title: form.title.trim(),
                  genre: form.genre.trim() || "未分类",
                  summary: form.summary.trim(),
                });
                await refreshProjects();
                setCurrentProject(p);
                showSuccess("项目创建成功");
                setOpen(false);
                setForm({ title: "", genre: "", summary: "" });
                navigate(`/projects/${p.id}/dashboard`);
              } catch (err: any) {
                showError("创建失败：" + (err.message || "未知错误"));
              } finally {
                setCreating(false);
              }
            }}
            className="space-y-4"
          >
            <div className="space-y-1.5">
              <span className="text-sm font-medium">作品标题</span>
              <Input
                placeholder="请输入作品标题"
                value={form.title}
                onChange={(e) => setForm((f) => ({ ...f, title: e.target.value }))}
                autoFocus
              />
            </div>
            <div className="space-y-1.5">
              <span className="text-sm font-medium">类型</span>
              <Input
                placeholder="如：玄幻 / 科幻 / 都市"
                value={form.genre}
                onChange={(e) => setForm((f) => ({ ...f, genre: e.target.value }))}
              />
            </div>
            <div className="space-y-1.5">
              <span className="text-sm font-medium">一句话简介</span>
              <Textarea
                placeholder="简单描述一下作品..."
                value={form.summary}
                onChange={(e) => setForm((f) => ({ ...f, summary: e.target.value }))}
                rows={3}
              />
            </div>
            <div className="flex justify-end gap-2 pt-2">
              <Button
                type="button"
                variant="outline"
                onClick={() => setOpen(false)}
                disabled={creating}
              >
                取消
              </Button>
              <Button type="submit" variant="primary" disabled={creating || !form.title.trim()}>
                {creating ? "创建中..." : "创建"}
              </Button>
            </div>
          </form>
        </DialogContent>
      </Dialog>

      {deleteDialog}
    </AppLayout>
  );
}
