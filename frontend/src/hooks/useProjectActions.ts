import { api } from "@/api";
import { useAppStore } from "@/store";
import { useToast } from "@/hooks/useToast";
import type { Project, Tab } from "@/types";

export function useProjectActions({
  setActiveTab,
  setSelectedAsset,
}: {
  setActiveTab: (tab: Tab) => void;
  setSelectedAsset: (asset: { type: "character" | "foreshadow" | "outline" | "chapter"; id: string } | null) => void;
}) {
  const store = useAppStore();
  const { showSuccess, showError } = useToast();

  const create = async (title: string, genre: string, summary: string, templateKey: string) => {
    try {
      const p = await api.createProject({ title, genre, summary, template_key: templateKey });
      await store.refreshProjects();
      store.setCurrentProject(p);
      showSuccess("项目创建成功");
    } catch (e: any) {
      showError("创建失败：" + e.message);
    }
  };

  const select = async (id: number) => {
    try {
      await store.loadProject(id);
    } catch (e: any) {
      showError("加载项目失败：" + e.message);
    }
  };

  const remove = async () => {
    if (!store.currentProject) return;
    const deletedId = store.currentProject.id;
    try {
      await api.deleteProject(deletedId);
      const remaining = store.projects.filter((p) => p.id !== deletedId);
      store.setProjects(remaining);
      const next = remaining[0] || null;
      store.setCurrentProject(next);
      setActiveTab("dashboard");
      setSelectedAsset(null);
      await store.refreshProjects();
      if (next) {
        showSuccess(`项目已删除，已自动切换到「${next.title}」`);
      } else {
        showSuccess("项目已删除");
      }
    } catch (e: any) {
      showError("删除失败：" + e.message);
      await store.refreshProjects();
    }
  };

  const save = async (form: Partial<Project>) => {
    if (!store.currentProject) return;
    try {
      await api.updateProject(store.currentProject.id, form);
      await store.refreshProjects();
      const updated = store.projects.find((x) => x.id === store.currentProject!.id);
      if (updated) store.setCurrentProject(updated);
      showSuccess("项目信息已保存");
    } catch (e: any) {
      showError("保存失败：" + e.message);
    }
  };

  return { create, select, remove, save };
}
