import type { ReactNode } from "react";
import { cn } from "@/lib/utils";

interface EmptyStateProps {
  /** 空态图标（建议传 `<Xxx className="h-10 w-10 text-muted" />` 形式的 ReactNode） */
  icon?: ReactNode;
  title: string;
  description?: string;
  /** 可选的操作按钮区 */
  children?: ReactNode;
  /** 额外 class（如覆盖 padding） */
  className?: string;
}

/** 通用空态：圆角卡片 + 图标 + 标题 + 描述 + 可选操作区 */
export function EmptyState({ icon, title, description, children, className }: EmptyStateProps) {
  return (
    <div
      className={cn(
        "flex flex-col items-center justify-center rounded-xl border border-border bg-surface px-6 py-16 text-center",
        className,
      )}
    >
      {icon && <div className="mb-3">{icon}</div>}
      <h3 className="text-base font-semibold">{title}</h3>
      {description && <p className="mt-1 max-w-md text-sm text-muted">{description}</p>}
      {children && <div className="mt-4">{children}</div>}
    </div>
  );
}
