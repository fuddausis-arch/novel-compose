import React, { useRef, useState } from "react";
import { ChevronDown, ChevronRight, Plus } from "lucide-react";
import { useVirtualizer } from "@tanstack/react-virtual";
import { cn } from "@/lib/utils";

export const SidebarSection = React.memo(function SidebarSection({
  title,
  icon,
  active,
  onClick,
}: {
  title: string;
  icon: React.ReactNode;
  active: boolean;
  onClick: () => void;
}) {
  return (
    <button
      onClick={onClick}
      className={cn(
        "w-full flex items-center gap-2.5 px-3 py-2 rounded-xl text-sm font-medium transition-all duration-200",
        active
          ? "bg-primary-muted text-primary shadow-sm"
          : "text-muted hover:bg-foreground/5 hover:text-foreground"
      )}
    >
      <span className={cn("transition-colors", active ? "text-primary" : "text-muted")}>{icon}</span>
      {title}
    </button>
  );
});

export function SidebarGroup({
  title,
  count,
  children,
  onAdd,
}: {
  title: string;
  count: number;
  children: React.ReactNode;
  onAdd: () => void;
}) {
  const [open, setOpen] = useState(false);
  return (
    <div className="mb-1">
      <div
        className="flex items-center justify-between px-2 py-1.5 text-xs font-semibold text-muted uppercase tracking-wider cursor-pointer hover:text-foreground transition-colors"
        onClick={() => setOpen(!open)}
      >
        <span>
          {title} <span className="text-[10px] opacity-70">({count})</span>
        </span>
        <div className="flex items-center gap-1" onClick={(e) => e.stopPropagation()}>
          <button
            onClick={onAdd}
            className="p-1 rounded-md hover:bg-primary-muted hover:text-primary text-muted transition-colors"
            aria-label={`添加${title}`}
          >
            <Plus className="h-3 w-3" />
          </button>
          {open ? <ChevronDown className="h-3 w-3" /> : <ChevronRight className="h-3 w-3" />}
        </div>
      </div>
      {open && <div className="ml-1 space-y-0.5">{children}</div>}
    </div>
  );
}

export const SidebarItem = React.memo(function SidebarItem({
  label,
  active,
  onClick,
}: {
  label: string;
  active: boolean;
  onClick: () => void;
}) {
  return (
    <button
      onClick={onClick}
      className={cn(
        "w-full text-left px-3 py-1.5 rounded-lg text-xs truncate transition-all duration-200",
        active
          ? "bg-primary-muted text-primary font-medium shadow-sm"
          : "text-muted hover:bg-foreground/5 hover:text-foreground"
      )}
    >
      {label}
    </button>
  );
});

interface VirtualListProps<T> {
  items: T[];
  getKey: (item: T) => string | number;
  renderItem: (item: T) => React.ReactNode;
  itemHeight: number;
  maxHeight?: number;
  overscan?: number;
}

export function VirtualList<T>({
  items,
  getKey,
  renderItem,
  itemHeight,
  maxHeight = 288,
  overscan = 5,
}: VirtualListProps<T>) {
  const parentRef = useRef<HTMLDivElement>(null);
  const virtualizer = useVirtualizer({
    count: items.length,
    getScrollElement: () => parentRef.current,
    estimateSize: () => itemHeight,
    overscan,
    getItemKey: (index) => getKey(items[index]),
  });

  return (
    <div ref={parentRef} className="overflow-y-auto" style={{ maxHeight }}>
      <div style={{ height: virtualizer.getTotalSize(), position: "relative", width: "100%" }}>
        {virtualizer.getVirtualItems().map((virtualItem) => (
          <div
            key={virtualItem.key}
            style={{
              position: "absolute",
              top: 0,
              left: 0,
              width: "100%",
              height: `${virtualItem.size}px`,
              transform: `translateY(${virtualItem.start}px)`,
            }}
          >
            {renderItem(items[virtualItem.index])}
          </div>
        ))}
      </div>
    </div>
  );
}
