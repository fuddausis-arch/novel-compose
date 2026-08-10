import type { ReactNode } from "react";
import { cn } from "@/lib/utils";

export type StatTone = "default" | "primary" | "warning" | "danger" | "success";

export interface StatCardProps {
  /** 卡片标签（小字） */
  label: string;
  /** 主数值（大字） */
  value: string | number | ReactNode;
  /** 图标徽章内容（DashboardView 风格：彩色徽章 + 横向布局） */
  icon?: ReactNode;
  /** 数值/图标徽章配色 */
  tone?: StatTone;
  /** DF 风格图标徽章配色（如 "bg-purple-500/20 text-purple-400"） */
  iconClass?: string;
  /** DF 风格数值后缀（如 "次"、"个"） */
  suffix?: string;
  /** DF 风格底部辅助说明 */
  hint?: string;
  /** DF 风格运行脉冲点 */
  pulse?: boolean;
  /** df-ui 风格数值文本色 class（如 "text-pink-400"） */
  accent?: string;
}

/** 简单布局：label 小字在上 + 大字数值在下 */
const SIMPLE_TONE: Record<StatTone, string> = {
  default: "text-primary",
  primary: "text-primary",
  warning: "text-warning",
  danger: "text-danger",
  success: "text-success",
};

/** 图标横向布局：彩色图标徽章 + 大字数值 + label */
const ICON_TONE: Record<StatTone, string> = {
  primary: "bg-primary-muted text-primary",
  warning: "bg-warning/10 text-warning",
  danger: "bg-danger/10 text-danger",
  success: "bg-success/10 text-success",
  default: "bg-primary-muted text-primary",
};

/**
 * 统一统计卡片：覆盖 4 种既有视觉
 * - 简单/强调色：label 小字 + 大字数值（tone 或 accent 控制数值颜色）
 * - 图标横向：彩色图标徽章 + 大字数值 + label
 * - DF 风格：图标徽章 + 脉冲点 + 大字数值 + suffix + label + hint
 */
export function StatCard({ label, value, icon, tone = "default", iconClass, suffix, hint, pulse, accent }: StatCardProps) {
  // DF 风格：图标徽章 + 脉冲点 + 数字 + 标签（df/components/dashboard/DFStatCard）
  if (pulse !== undefined || iconClass !== undefined) {
    return (
      <div
        className="rounded-xl border border-border bg-surface p-4 transition-colors hover:border-border-strong/60"
        role="article"
        aria-label={`${label}: ${value}${suffix ?? ""}`}
      >
        <div className="mb-3 flex items-center justify-between">
          {icon && (
            <span className={cn("rounded-lg p-2", iconClass)} aria-hidden="true">
              {icon}
            </span>
          )}
          {pulse && <span className="h-2 w-2 rounded-full bg-green-500 status-running" aria-hidden="true" />}
        </div>
        <div className="text-2xl font-semibold tabular-nums text-foreground">
          {value}
          {suffix && <span className="ml-1 text-sm font-normal text-muted">{suffix}</span>}
        </div>
        <div className="mt-1 text-xs text-muted">{label}</div>
        {hint && <div className="mt-0.5 truncate text-[11px] text-muted/60">{hint}</div>}
      </div>
    );
  }

  // 图标横向风格（DashboardView 文件内 StatCard）
  if (icon !== undefined) {
    return (
      <div className="flex items-center gap-3 rounded-xl border border-border bg-surface p-4">
        <div className={cn("h-10 w-10 shrink-0 rounded-xl flex items-center justify-center", ICON_TONE[tone])}>
          {icon}
        </div>
        <div className="min-w-0">
          <div className="truncate text-xl font-bold text-foreground">{value}</div>
          <div className="text-xs font-medium text-muted">{label}</div>
        </div>
      </div>
    );
  }

  // 简单/强调色风格（dashboard/StatCard 与 df-ui DFStatCard）
  return (
    <div className={cn("rounded-xl border border-border p-4", accent ? "bg-surface" : "bg-surface-elevated")}>
      <div className="text-xs text-muted">{label}</div>
      <div className={cn("mt-1 text-2xl font-bold tabular-nums", accent ?? SIMPLE_TONE[tone])}>{value}</div>
    </div>
  );
}
