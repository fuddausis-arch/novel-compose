import { cn } from "@/lib/utils";

export interface TreeItemProps {
  label: React.ReactNode;
  expanded?: boolean;
  onToggle?: () => void;
  active?: boolean;
  onClick?: () => void;
  depth?: number;
}

export function TreeItem({
  label,
  expanded,
  onToggle,
  active,
  onClick,
  depth = 0,
}: TreeItemProps) {
  return (
    <div
      role="button"
      tabIndex={0}
      onClick={onClick}
      onKeyDown={(e) => {
        if (e.key === "Enter" || e.key === " ") {
          e.preventDefault();
          onClick?.();
        }
      }}
      className={cn(
        "flex items-center gap-1 rounded-lg text-sm cursor-pointer select-none",
        active && "bg-primary text-primary-foreground",
        !active && "hover:bg-foreground/5"
      )}
      style={{
        padding: "0.35rem 0.5rem",
        paddingLeft: `${0.5 + depth * 0.9}rem`,
      }}
    >
      {onToggle ? (
        <span
          className="inline-flex w-4 items-center justify-center"
          onClick={(e) => {
            e.stopPropagation();
            onToggle();
          }}
          role="button"
          tabIndex={-1}
          aria-label={expanded ? "收起" : "展开"}
        >
          {expanded ? "▼" : "▶"}
        </span>
      ) : (
        <span className="inline-block w-4" />
      )}
      <span className="truncate">{label}</span>
    </div>
  );
}
