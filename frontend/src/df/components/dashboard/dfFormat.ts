/** DF 融合界面通用格式化工具 */

/** Token 数量紧凑格式化：1234 -> 1.2K，1234567 -> 1.2M */
export function formatTokens(n: number): string {
  if (!Number.isFinite(n)) return "0";
  if (n >= 1_000_000) return `${(n / 1_000_000).toFixed(1)}M`;
  if (n >= 1_000) return `${(n / 1_000).toFixed(1)}K`;
  return String(Math.round(n));
}

/** 成本（美元）格式化：0 显示 $0.00，其余保留 4 位小数以体现小额成本 */
export function formatCost(n: number): string {
  if (!Number.isFinite(n) || n === 0) return "$0.00";
  if (n < 0.0001) return "<$0.0001";
  return `$${n.toFixed(4)}`;
}

/** 运行时长格式化：按天/时/分/秒逐级降级展示 */
export function formatUptime(seconds: number): string {
  if (!Number.isFinite(seconds) || seconds < 0) return "-";
  const d = Math.floor(seconds / 86400);
  const h = Math.floor((seconds % 86400) / 3600);
  const m = Math.floor((seconds % 3600) / 60);
  const s = Math.floor(seconds % 60);
  if (d > 0) return `${d}天${h}时`;
  if (h > 0) return `${h}时${m}分`;
  if (m > 0) return `${m}分${s}秒`;
  return `${s}秒`;
}

/** ISO 时间串 -> 本地 HH:MM（用于图表横轴与记录列表） */
export function formatClockTime(iso: string): string {
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return "-";
  return d.toLocaleTimeString("zh-CN", { hour: "2-digit", minute: "2-digit", hour12: false });
}

/** ISO 时间串 -> 本地 MM-DD HH:MM（用于项目列表） */
export function formatDateTime(iso: string | null | undefined): string {
  if (!iso) return "-";
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return "-";
  const mm = String(d.getMonth() + 1).padStart(2, "0");
  const dd = String(d.getDate()).padStart(2, "0");
  return `${mm}-${dd} ${d.toLocaleTimeString("zh-CN", { hour: "2-digit", minute: "2-digit", hour12: false })}`;
}
