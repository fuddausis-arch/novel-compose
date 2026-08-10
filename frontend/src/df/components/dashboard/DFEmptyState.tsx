import type { ReactNode } from "react";
import { DF_BRAND_MARK_DARK } from "../../brand";

interface DFEmptyStateProps {
  title: string;
  description?: string;
  /** 可选操作区（按钮等） */
  action?: ReactNode;
}

/** DF 品牌空态：浮动 logo + 标题 + 描述 + 操作区 */
export function DFEmptyState({ title, description, action }: DFEmptyStateProps) {
  return (
    <div
      className="flex h-full min-h-[240px] flex-col items-center justify-center gap-3 px-6 text-center"
      role="status"
    >
      <img
        src={DF_BRAND_MARK_DARK}
        alt=""
        className="h-16 w-16 animate-float motion-reduce:animate-none"
        aria-hidden="true"
      />
      <h2 className="text-lg font-semibold text-foreground">{title}</h2>
      {description && (
        <p className="max-w-md text-sm text-muted">{description}</p>
      )}
      {action && <div className="mt-2">{action}</div>}
    </div>
  );
}
