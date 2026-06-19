import { OutlineLevelView } from "@/components/outline-level-view";
import type { Project } from "@/types";

interface Props {
  project: Project | null;
  refresh?: () => Promise<void>;
  setLoading?: (loading: boolean) => void;
}

export function OutlinesVolumeView({ project, refresh, setLoading }: Props) {
  if (!project) {
    return (
      <div className="flex-1 flex items-center justify-center text-muted text-sm">
        请先选择或创建一个项目
      </div>
    );
  }
  return (
    <OutlineLevelView
      project={project}
      level="volume"
      title="大纲（卷）"
      refresh={refresh}
      setLoading={setLoading}
    />
  );
}
