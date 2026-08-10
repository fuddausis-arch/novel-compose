/** 左侧工作流列表栏：内置 + 自定义工作流卡片，自定义带「自定义」徽章
 *
 * 顶部可放工具栏子元素（如「新建工作流」按钮）。
 */
import type { ReactNode } from "react";
import { Loader2, Workflow } from "lucide-react";
import { ScrollArea } from "@/components/ui/scroll-area";
import { Badge } from "@/components/ui/badge";
import { cn } from "@/lib/utils";
import type { WorkflowSummary } from "./types";

interface WorkflowListPanelProps {
  workflows: WorkflowSummary[];
  loading: boolean;
  error: string | null;
  selectedId: string | null;
  onSelect: (id: string) => void;
  /** 顶部工具栏（如「新建」按钮、模式切换等），渲染在标题栏下方 */
  toolbar?: ReactNode;
}

export default function WorkflowListPanel({
  workflows,
  loading,
  error,
  selectedId,
  onSelect,
  toolbar,
}: WorkflowListPanelProps) {
  return (
    <aside
      className="flex w-64 shrink-0 flex-col border-r border-border bg-surface"
      aria-label="工作流列表"
    >
      {/* 栏目标题 */}
      <div className="flex h-12 shrink-0 items-center gap-2 border-b border-border px-4">
        <Workflow size={15} className="text-purple-400" aria-hidden="true" />
        <h2 className="text-sm font-semibold text-foreground">工作流</h2>
        {!loading && (
          <span className="ml-auto text-xs text-muted">{workflows.length} 条</span>
        )}
      </div>

      {/* 顶部工具栏 */}
      {toolbar && (
        <div className="shrink-0 border-b border-border p-2">{toolbar}</div>
      )}

      <ScrollArea className="flex-1">
        <div className="space-y-2 p-3">
          {loading && (
            <div
              className="flex items-center gap-2 px-1 py-2 text-xs text-muted"
              role="status"
            >
              <Loader2 size={13} className="animate-spin motion-reduce:animate-none" aria-hidden="true" />
              加载工作流列表...
            </div>
          )}
          {error && (
            <p className="px-1 py-2 text-xs text-red-400" role="alert">
              {error}
            </p>
          )}
          {!loading && !error && workflows.length === 0 && (
            <p className="px-1 py-2 text-xs text-muted">暂无可用工作流</p>
          )}
          {workflows.map((wf) => {
            const active = wf.workflow_id === selectedId;
            return (
              <button
                key={wf.workflow_id}
                type="button"
                onClick={() => onSelect(wf.workflow_id)}
                aria-pressed={active}
                className={cn(
                  "flex min-h-[44px] w-full cursor-pointer flex-col gap-1 rounded-lg border border-border bg-surface px-3 py-2.5 text-left transition-colors hover:border-purple-500/40",
                  active && "border-transparent bg-purple-500/10 ring-1 ring-purple-500/50",
                )}
              >
                <div className="flex w-full items-center gap-1.5">
                  <span className="min-w-0 flex-1 truncate text-sm font-medium text-foreground">
                    {wf.name}
                  </span>
                  {wf.is_custom ? (
                    <Badge variant="primary" className="shrink-0 text-[10px]">
                      自定义
                    </Badge>
                  ) : (
                    <Badge variant="default" className="shrink-0 text-[10px]">
                      内置
                    </Badge>
                  )}
                </div>
                <span className="flex w-full items-center gap-2 text-[11px] text-muted">
                  <span>{wf.node_count} 节点</span>
                  <span>v{wf.version}</span>
                  <span className="truncate font-mono">{wf.workflow_id}</span>
                </span>
              </button>
            );
          })}
        </div>
      </ScrollArea>
    </aside>
  );
}
