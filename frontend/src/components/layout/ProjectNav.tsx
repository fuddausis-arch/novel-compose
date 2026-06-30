import { useLocation, useNavigate, useParams } from "react-router-dom";
import { ArrowLeft } from "lucide-react";
import { useAppStore } from "@/store";
import { Pill } from "@/components/ui/pill";
import { Button } from "@/components/ui/button";

const NAV_ITEMS = [
  { path: "dashboard", label: "工作台" },
  { path: "write", label: "写作" },
  { path: "assets", label: "资产" },
  { path: "stats", label: "统计" },
  { path: "settings", label: "设置" },
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

  const canGoBack = location.key !== "default";

  const handleNavigate = (path: string) => {
    if (!projectId) return;
    navigate(`/projects/${projectId}/${path}`);
  };

  const isActive = (path: string) => location.pathname.includes(`/projects/${projectId}/${path}`);

  return (
    <header className="flex h-14 shrink-0 items-center justify-between border-b border-border bg-surface-elevated px-4">
      <div className="flex items-center gap-2 text-sm font-semibold text-foreground">
        {leftSlot}
        <Button
          variant="ghost"
          size="sm"
          className="h-8 w-8 px-0"
          onClick={() => navigate(-1)}
          disabled={!canGoBack}
          title="返回"
        >
          <ArrowLeft className="h-4 w-4" />
        </Button>
        <span className="text-base">📖</span>
        <span className="max-w-[12rem] truncate">{project?.title || "未选择作品"}</span>
      </div>

      <nav className="flex items-center gap-1">
        {NAV_ITEMS.map((item) => (
          <Pill
            key={item.path}
            active={isActive(item.path)}
            onClick={() => handleNavigate(item.path)}
          >
            {item.label}
          </Pill>
        ))}
      </nav>

      <div className="flex items-center gap-3 text-sm text-muted">
        {rightSlot}
        <div className="flex items-center gap-1.5">
          <span>🔍</span>
          <span>搜索</span>
        </div>
        <kbd className="hidden rounded-md bg-foreground/5 px-1.5 py-0.5 text-xs font-medium text-muted md:inline-block">
          ⌘K
        </kbd>
      </div>
    </header>
  );
}
