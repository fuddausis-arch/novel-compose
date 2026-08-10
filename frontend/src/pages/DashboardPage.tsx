import { useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import { AppLayout } from "@/components/layout/AppLayout";
import { DashboardView } from "@/views/DashboardView";
import { Button } from "@/components/ui/button";
import { useCurrentProject } from "@/hooks/useCurrentProject";
import { useAppStore } from "@/store";
import { api } from "@/api";
import { useToast } from "@/hooks/useToast";
import type { Project } from "@/types";

export default function DashboardPage() {
  const navigate = useNavigate();
  const { project } = useCurrentProject();
  const store = useAppStore();
  const { showSuccess, showError } = useToast();
  const [projectForm, setProjectForm] = useState<Partial<Project>>({});
  const [refreshingGenre, setRefreshingGenre] = useState(false);

  useEffect(() => {
    if (project) {
      setProjectForm({
        title: project.title,
        genre: project.genre,
        summary: project.summary,
        style: project.style,
      });
    }
  }, [project?.id]);

  if (!project) return null;

  const totalWords = store.summaries.reduce((sum, s) => sum + (s.word_count || 0), 0);
  const chapterCount = store.chapters.length;
  const characterCount = store.characters.length;
  const foreshadowCount = store.foreshadows.filter((f) => f.status === "pending" || f.status === "developing").length;
  const outlineCount = store.outlines.length;

  const handleSave = async (form: Partial<Project>) => {
    try {
      await api.updateProject(project.id, form);
      await store.refreshProjects();
      store.setCurrentProject({ ...project, ...form });
      // 题材变更后刷新 genreContext，AI 生成使用新题材
      store.refreshGenreContext();
      showSuccess("项目信息已保存");
    } catch (e: any) {
      showError("保存失败：" + e.message);
    }
  };

  const handleRefreshGenreContext = async () => {
    setRefreshingGenre(true);
    try {
      await store.refreshGenreContext();
    } finally {
      setRefreshingGenre(false);
    }
  };

  return (
    <AppLayout>
      <div className="flex h-full flex-col overflow-hidden bg-background">
        <header className="flex items-center justify-between border-b border-border px-6 py-4">
          <h1 className="text-xl font-bold text-foreground">工作台</h1>
          <Button
            variant="primary"
            onClick={() => navigate(`/projects/${project.id}/write`)}
          >
            继续写作
          </Button>
        </header>

        <div className="flex-1 overflow-y-auto p-6">
          <DashboardView
            project={project}
            totalWords={totalWords}
            chapterCount={chapterCount}
            characterCount={characterCount}
            foreshadowCount={foreshadowCount}
            outlineCount={outlineCount}
            projectForm={projectForm}
            setProjectForm={setProjectForm}
            onSave={handleSave}
            genreContext={store.genreContext}
            onRefreshGenreContext={handleRefreshGenreContext}
            refreshingGenre={refreshingGenre}
          />
        </div>
      </div>
    </AppLayout>
  );
}
