import { useEffect } from "react";
import { useParams } from "react-router-dom";
import { useAppStore } from "@/store";
import { useToast } from "@/hooks/useToast";

export function useCurrentProject() {
  const { projectId } = useParams<{ projectId: string }>();
  const store = useAppStore();
  const { showError } = useToast();

  const id = projectId ? Number(projectId) : NaN;
  const isValidProjectId = !Number.isNaN(id) && id > 0;

  useEffect(() => {
    if (!isValidProjectId) return;

    store.loadProject(id).catch((e) => {
      showError("加载项目失败：" + e.message);
    });
  }, [id, isValidProjectId]);

  useEffect(() => {
    if (!store.currentProject) return;

    store.refreshAssets().catch((e) => {
      showError("加载资产失败：" + e.message);
    });

    store.refreshGenreContext().catch((e) => {
      showError("加载题材上下文失败：" + e.message);
    });
  }, [store.currentProject?.id]);

  return { projectId: id, project: store.currentProject };
}
