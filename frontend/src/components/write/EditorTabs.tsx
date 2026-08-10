import { cn } from "@/lib/utils";
import type { TabItem } from "@/hooks/useOpenTabs";

export interface EditorTabsProps {
  tabs: TabItem[];
  activeTabId: string | null;
  onActivate: (id: string) => void;
  onClose: (id: string) => void;
  onAdd?: () => void;
}

export function EditorTabs({
  tabs,
  activeTabId,
  onActivate,
  onClose,
  onAdd,
}: EditorTabsProps) {
  return (
    <div className="flex items-center gap-1 border-b border-border bg-surface px-2 py-1.5">
      <div className="flex flex-1 items-center gap-1 overflow-x-auto scrollbar-hide">
        {tabs.map((tab) => {
          const isActive = tab.id === activeTabId;
          return (
            <div
              key={tab.id}
              onClick={() => onActivate(tab.id)}
              className={cn(
                "group flex shrink-0 cursor-pointer items-center gap-2 rounded-t-lg border px-3 py-1.5 text-sm transition-colors",
                isActive
                  ? "bg-surface-elevated border-border-strong text-foreground"
                  : "bg-surface border-border text-muted hover:text-foreground"
              )}
            >
              <span className="max-w-[140px] truncate">{tab.label}</span>
              <button
                type="button"
                onClick={(e) => {
                  e.stopPropagation();
                  onClose(tab.id);
                }}
                className="rounded-md p-0.5 text-muted opacity-0 transition-opacity hover:bg-foreground/10 hover:text-foreground group-hover:opacity-100"
                aria-label={`关闭 ${tab.label}`}
              >
                ✕
              </button>
            </div>
          );
        })}
      </div>

      {onAdd && (
        <button
          type="button"
          onClick={onAdd}
          className="flex h-7 w-7 shrink-0 items-center justify-center rounded-lg border border-border bg-surface text-muted transition-colors hover:border-border-strong hover:text-foreground"
          aria-label="新增标签"
        >
          +
        </button>
      )}
    </div>
  );
}
