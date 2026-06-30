import { useEffect, useMemo, useState } from "react";
import { useNavigate } from "react-router-dom";
import { Plus, Search, ArrowUpDown } from "lucide-react";

import { AppLayout } from "@/components/layout/AppLayout";
import { ProjectCard } from "@/components/projects/ProjectCard";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { useToast } from "@/hooks/useToast";
import { useAppStore } from "@/store";

export default function ProjectsPage() {
  const navigate = useNavigate();
  const { showError } = useToast();
  const projects = useAppStore((state) => state.projects);
  const refreshProjects = useAppStore((state) => state.refreshProjects);
  const [query, setQuery] = useState("");

  useEffect(() => {
    refreshProjects().catch((err) => {
      showError(err instanceof Error ? err.message : "加载作品列表失败");
    });
  }, [refreshProjects, showError]);

  const filteredProjects = useMemo(() => {
    const q = query.trim().toLowerCase();
    if (!q) return projects;
    return projects.filter((p) => p.title.toLowerCase().includes(q));
  }, [projects, query]);

  return (
    <AppLayout hideNav>
      <div className="flex h-full flex-col overflow-hidden bg-background">
        <header className="flex items-center justify-between border-b border-border px-6 py-4">
          <div>
            <h1 className="text-xl font-bold text-foreground">我的作品</h1>
            <p className="text-sm text-muted">共 {projects.length} 个项目</p>
          </div>

          <Button variant="primary" onClick={() => {}}>
            <Plus className="mr-1 h-4 w-4" />
            新建项目
          </Button>
        </header>

        <div className="flex items-center gap-3 border-b border-border px-6 py-3">
          <div className="relative flex-1 max-w-md">
            <Search className="absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-muted" />
            <Input
              placeholder="搜索作品..."
              className="pl-9"
              value={query}
              onChange={(e) => setQuery(e.target.value)}
            />
          </div>

          <Button variant="outline" size="sm" onClick={() => {}}>
            <ArrowUpDown className="mr-1 h-4 w-4" />
            按时间排序
          </Button>
        </div>

        <div className="flex-1 overflow-y-auto p-6">
          <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-3">
            {filteredProjects.map((project) => (
              <ProjectCard
                key={project.id}
                project={project}
                onClick={() => navigate(`/projects/${project.id}/dashboard`)}
              />
            ))}

            <div className="flex flex-col items-center justify-center rounded-xl border border-dashed border-border-strong p-4 text-muted hover:bg-surface-elevated cursor-pointer">
              <Plus className="h-6 w-6" />
              <span className="mt-2 text-sm font-medium">创建新项目</span>
            </div>
          </div>
        </div>
      </div>
    </AppLayout>
  );
}
