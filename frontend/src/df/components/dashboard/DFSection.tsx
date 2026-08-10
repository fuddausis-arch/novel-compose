import type { LucideIcon } from "lucide-react";
import type { ReactNode } from "react";
import { cn } from "@/lib/utils";

interface DFSectionProps {
  /** 分区标题 */
  title: string;
  icon?: LucideIcon;
  /** 标题右侧附加内容（图例、徽标、操作按钮等） */
  extra?: ReactNode;
  className?: string;
  children: ReactNode;
}

/** DF 风格卡片分区：统一标题栏 + 内容容器 */
export function DFSection({ title, icon: Icon, extra, className, children }: DFSectionProps) {
  return (
    <section
      className={cn("rounded-xl border border-border bg-surface p-4", className)}
      aria-label={title}
    >
      <div className="mb-3 flex items-center gap-2">
        {Icon && <Icon size={14} className="text-muted" aria-hidden="true" />}
        <h3 className="text-sm font-semibold text-foreground">{title}</h3>
        {extra && <div className="ml-auto flex items-center gap-2">{extra}</div>}
      </div>
      {children}
    </section>
  );
}
