import { cn } from "@/lib/utils";
import type { Project } from "@/types";

export interface ProjectCardProps {
  project: Project;
  active?: boolean;
  onClick: () => void;
}

export function ProjectCard({ project, active, onClick }: ProjectCardProps) {
  return (
    <div
      onClick={onClick}
      className={cn(
        "p-4 rounded-xl border bg-surface-elevated cursor-pointer transition-all",
        active && "border-primary ring-1 ring-primary",
        !active && "hover:border-border-strong hover:shadow"
      )}
    >
      <div className="flex items-start justify-between gap-2">
        <h3 className="font-semibold text-foreground truncate">{project.title}</h3>
        <span className="shrink-0 inline-flex items-center rounded-full bg-primary-muted px-2 py-0.5 text-xs font-medium text-primary">
          进行中
        </span>
      </div>

      <p className="mt-1 text-sm text-muted truncate">
        {project.genre || "未分类"}
      </p>

      <div className="mt-4 flex items-center gap-3 text-xs text-muted">
        <span>0 章</span>
        <span>0 字</span>
        <span>0 角色</span>
      </div>
    </div>
  );
}
