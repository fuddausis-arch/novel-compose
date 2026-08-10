import { memo } from "react";
import { Trash2 } from "lucide-react";
import { cn } from "@/lib/utils";
import type { Project } from "@/types";

export interface ProjectCardProps {
  project: Project;
  active?: boolean;
  onClick: () => void;
  onDelete?: (project: Project) => void;
}

export const ProjectCard = memo(function ProjectCard({
  project,
  active,
  onClick,
  onDelete,
}: ProjectCardProps) {
  return (
    <div
      data-testid="project-card"
      onClick={onClick}
      className={cn(
        "p-4 rounded-xl border bg-surface-elevated cursor-pointer transition-all",
        active && "border-primary ring-1 ring-primary",
        !active && "hover:border-border-strong hover:shadow"
      )}
    >
      <div className="flex items-start justify-between gap-2">
        <h3 className="font-semibold text-foreground truncate">{project.title}</h3>
        <div className="flex shrink-0 items-center gap-1">
          <span className="inline-flex items-center rounded-full bg-primary-muted px-2 py-0.5 text-xs font-medium text-primary">
            进行中
          </span>
          {onDelete && (
            <button
              type="button"
              aria-label="删除项目"
              onClick={(e) => {
                e.stopPropagation();
                onDelete(project);
              }}
              className="inline-flex h-6 w-6 items-center justify-center rounded-md text-muted transition-colors hover:bg-danger/10 hover:text-danger"
            >
              <Trash2 className="h-3.5 w-3.5" />
            </button>
          )}
        </div>
      </div>

      <p className="mt-1 text-sm text-muted truncate">
        {project.genre || "未分类"}
      </p>

      <div className="mt-4 flex items-center gap-3 text-xs text-muted">
        <span>{(project as any).chapter_count || 0} 章</span>
        <span>{(project as any).word_count || 0} 字</span>
        <span>{(project as any).character_count || 0} 角色</span>
      </div>
      <p className="mt-1 text-[10px] text-muted">统计数据需进入项目查看</p>
    </div>
  );
});
