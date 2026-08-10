/**
 * 左侧 Token 监控竖栏（可折叠）
 *
 * 复刻 DeterminFlow MonitoringCard 的折叠/展开双态：
 * - 折叠：w-7 窄条，竖向占比条 + 调用次数
 * - 展开：w-64 完整卡片，上下文占用进度 + 分项统计 + 模型信息
 *
 * 注意：本项目后端无 token 统计端点，数据由前端按消息文本粗估（estimateTokens）。
 */
import { memo } from "react";
import {
  BarChart3, ChevronLeft, ChevronRight, Zap, Database, MessageSquare, Cpu,
  type LucideIcon,
} from "lucide-react";
import { formatTokens } from "./api";

export interface TokenStats {
  /** 系统提示词估算 token */
  systemTokens: number;
  /** 用户消息估算 token */
  userTokens: number;
  /** 助手消息估算 token */
  assistantTokens: number;
  /** LLM 调用次数（按助手消息数近似） */
  callCount: number;
  /** 当前模型 */
  model: string;
  /** 上下文上限 */
  maxContext: number;
}

interface Props {
  stats: TokenStats | null;
  collapsed: boolean;
  onToggle: () => void;
}

function fmtPct(numerator: number, denominator: number): string {
  if (!denominator) return "0.0%";
  return `${Math.min((numerator / denominator) * 100, 100).toFixed(1)}%`;
}

function StatRow({ icon: Icon, label, value, colorClass }: {
  icon: LucideIcon; label: string; value: string; colorClass: string;
}) {
  return (
    <div className="flex items-center gap-1.5 py-0.5" role="listitem">
      <Icon size={14} className={colorClass} aria-hidden="true" />
      <span className="text-xs text-muted">{label}</span>
      <span className="ml-auto text-xs font-mono text-foreground tabular-nums">{value}</span>
    </div>
  );
}

function TokenMonitor({ stats, collapsed, onToggle }: Props) {
  const used = stats ? stats.systemTokens + stats.userTokens + stats.assistantTokens : 0;
  const maxContext = stats?.maxContext || 0;
  const ctxPct = fmtPct(used, maxContext);
  const ctxBarPct = maxContext ? Math.min((used / maxContext) * 100, 100) : 0;
  // 占比 >80% 变红，>60% 变黄
  const ctxBgClass = ctxBarPct > 80 ? "bg-red-500" : ctxBarPct > 60 ? "bg-amber-500" : "bg-green-500";
  const ctxTextClass = ctxBarPct > 80 ? "text-red-500" : ctxBarPct > 60 ? "text-amber-500" : "text-green-500";

  // ---------- 折叠态：竖向窄条 ----------
  if (collapsed) {
    return (
      <div
        className="h-full flex flex-col items-center gap-1 py-2 cursor-pointer hover:bg-white/[0.03] transition-colors select-none rounded-r-lg border border-white/[0.04] bg-background/60"
        onClick={onToggle}
        role="button"
        tabIndex={0}
        aria-label={stats ? `展开 Token 监控面板，当前上下文占用 ${ctxPct}` : "展开 Token 监控面板"}
        onKeyDown={(e) => { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); onToggle(); } }}
      >
        <ChevronRight size={12} className="text-muted shrink-0" aria-hidden="true" />
        <span className="text-xs text-muted font-mono tabular-nums">{stats?.callCount ?? "-"}</span>
        <div className="flex-1 w-1.5 bg-white/[0.04] rounded-full overflow-hidden relative min-h-[20px]" aria-hidden="true">
          <div
            className={`absolute bottom-0 left-0 w-full rounded-full transition-all duration-500 ${ctxBgClass}`}
            style={{ height: `${ctxBarPct}%` }}
          />
        </div>
        <span className="text-xs text-muted font-mono tabular-nums">{stats ? ctxPct : "-"}</span>
      </div>
    );
  }

  // ---------- 展开态：完整卡片 ----------
  return (
    <div className="h-full flex flex-col rounded-xl border border-white/[0.06] bg-background select-none" role="region" aria-label="Token 监控面板">
      <div className="shrink-0 flex items-center gap-1.5 px-3 py-2.5 border-b border-white/[0.05]">
        <BarChart3 size={14} className="text-indigo-500" aria-hidden="true" />
        <span className="text-xs font-semibold text-foreground tracking-wide">Token 监控</span>
        <button
          type="button"
          onClick={onToggle}
          className="ml-auto p-0.5 rounded hover:bg-white/[0.06] transition-colors cursor-pointer min-h-[44px] min-w-[44px] flex items-center justify-center"
          aria-label="折叠 Token 监控面板"
        >
          <ChevronLeft size={12} className="text-muted" aria-hidden="true" />
        </button>
      </div>

      {!stats ? (
        <div className="flex-1 flex flex-col items-center justify-center px-4 text-center gap-2" role="status" aria-label="暂无 Token 监控数据">
          <BarChart3 size={24} className="text-muted" aria-hidden="true" />
          <span className="text-xs text-muted leading-relaxed">暂无数据<br />发送消息后开始统计</span>
        </div>
      ) : (
        <div className="flex-1 overflow-y-auto px-3 py-3 space-y-4 text-xs">
          {/* 上下文概览 */}
          <div className="space-y-1.5">
            <div className="flex items-center justify-between text-xs">
              <span className="text-muted">上下文占用</span>
              <span className={`font-mono tabular-nums ${ctxTextClass}`}>
                {formatTokens(used)} / {formatTokens(maxContext)}
              </span>
            </div>
            <div
              className="h-2.5 rounded-full bg-white/[0.05] overflow-hidden"
              role="progressbar" aria-valuenow={ctxBarPct} aria-valuemin={0} aria-valuemax={100}
              aria-label={`上下文占用 ${ctxPct}`}
            >
              <div className={`h-full rounded-full transition-all duration-500 ease-out ${ctxBgClass}`} style={{ width: `${ctxBarPct}%` }} />
            </div>
            <div className="flex items-center justify-between text-xs text-muted">
              <span>{ctxPct} 已用</span>
              <span>#{stats.callCount} 次调用</span>
            </div>
          </div>

          {/* 分项估算 */}
          <div className="space-y-1.5">
            <div className="flex items-center gap-1 text-xs text-muted font-medium">
              <Zap size={14} className="text-indigo-500/70" aria-hidden="true" />
              估算分布
            </div>
            <div className="space-y-1" role="list" aria-label="Token 估算统计">
              <StatRow icon={Database} label="系统提示词" value={formatTokens(stats.systemTokens)} colorClass="text-indigo-500" />
              <StatRow icon={MessageSquare} label="用户消息" value={formatTokens(stats.userTokens)} colorClass="text-cyan-500" />
              <StatRow icon={Cpu} label="助手回复" value={formatTokens(stats.assistantTokens)} colorClass="text-purple-500" />
            </div>
          </div>

          {/* 模型信息 */}
          <div className="pt-2 border-t border-white/[0.04] space-y-1">
            <div className="text-xs text-muted truncate" title={stats.model}>{stats.model || "未配置模型"}</div>
            <div className="text-xs text-muted tabular-nums">上限 {formatTokens(maxContext)}</div>
            <div className="text-[11px] text-muted">* 本地估算，仅供参考</div>
          </div>
        </div>
      )}
    </div>
  );
}

export default memo(TokenMonitor);
