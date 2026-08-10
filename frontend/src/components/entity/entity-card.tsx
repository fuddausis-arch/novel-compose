/** 实体卡片外壳：统一「名称 + 徽章 + 描述 + 点击打开详情」的基础布局。
 *
 * 各页差异字段通过 children（描述上方）/ footer（描述下方）传入；
 * 各页原有样式通过 className 系列 prop 覆盖，保证视觉与替换前完全一致。
 * （百科卡 / 势力 / 怪物 / 副本页共用）
 */
import type { ReactNode } from "react";
import { cn } from "@/lib/utils";

export interface EntityCardProps {
  /** 点击卡片（各页各自打开详情抽屉/资产面板） */
  onClick: () => void;
  /** 名称 */
  title: ReactNode;
  /** 名称行右侧徽章（各页自定义：出场章数 / 类型 / 等级等） */
  badge?: ReactNode;
  /** 名称左侧图标（百科卡用） */
  leadingIcon?: ReactNode;
  /** 描述（位于 children 与 footer 之间） */
  description?: ReactNode;
  /** 描述上方的差异字段区 */
  children?: ReactNode;
  /** 描述下方的差异字段区 */
  footer?: ReactNode;
  /** 外壳容器 class（默认与资产视图 Card 外壳一致） */
  className?: string;
  /** 内容区 class（默认与资产视图 CardContent 一致） */
  contentClassName?: string;
  /** 名称行 class（默认与资产视图头部一致） */
  headerClassName?: string;
  /** 名称 class（默认与资产视图 h4 一致） */
  titleClassName?: string;
  /** 描述 class（默认与资产视图描述一致） */
  descriptionClassName?: string;
}

export function EntityCard({
  onClick,
  title,
  badge,
  leadingIcon,
  description,
  children,
  footer,
  className,
  contentClassName,
  headerClassName,
  titleClassName,
  descriptionClassName,
}: EntityCardProps) {
  return (
    <button
      type="button"
      onClick={onClick}
      className={cn(
        "flex cursor-pointer flex-col rounded-xl border border-border bg-surface text-left transition-colors hover:border-primary/50",
        className,
      )}
    >
      <div className={cn("flex flex-col gap-2 p-4", contentClassName)}>
        <div className={cn("flex items-start justify-between gap-2", headerClassName)}>
          {leadingIcon && <span className="shrink-0 text-primary">{leadingIcon}</span>}
          <h4 className={cn("text-sm font-medium text-foreground", titleClassName)}>{title}</h4>
          {badge}
        </div>
        {children}
        {description && (
          <p className={cn("text-sm text-muted whitespace-pre-wrap line-clamp-3", descriptionClassName)}>
            {description}
          </p>
        )}
        {footer}
      </div>
    </button>
  );
}
