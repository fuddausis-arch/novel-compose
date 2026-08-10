import { X } from "lucide-react";
import { getSeatColor, type RoundtableSeat } from "./roundtablePresets";

interface DFSeatCardProps {
  /** 席位配置 */
  seat: RoundtableSeat;
  /** 席位下标（决定配色） */
  index: number;
  /** 是否允许移除（席位多于下限时可移除） */
  canRemove: boolean;
  /** 更新席位字段 */
  onChange: (index: number, field: keyof RoundtableSeat, value: string | number | boolean) => void;
  /** 移除席位 */
  onRemove: (index: number) => void;
}

/** 圆桌席位配置卡片：配色圆点 + 角色名 + 主持开关 + 温度 + System Prompt */
export function DFSeatCard({ seat, index, canRemove, onChange, onRemove }: DFSeatCardProps) {
  const color = getSeatColor(index);
  return (
    <div
      className={`space-y-2 rounded-xl border bg-surface p-3 ${color.border}`}
      role="group"
      aria-label={`席位 ${index + 1}：${seat.role_name || "未命名"}`}
    >
      <div className="flex items-center gap-2">
        <span className={`h-2 w-2 shrink-0 rounded-full ${color.dot}`} aria-hidden="true" />
        <label htmlFor={`df-seat-name-${index}`} className="sr-only">
          席位 {index + 1} 角色名称
        </label>
        <input
          id={`df-seat-name-${index}`}
          type="text"
          value={seat.role_name}
          onChange={(e) => onChange(index, "role_name", e.target.value)}
          placeholder={`角色名称 ${index + 1}`}
          aria-required="true"
          className="min-h-[36px] min-w-0 flex-1 rounded-lg border border-border-strong bg-surface px-2 text-sm text-foreground placeholder:text-muted focus:border-green-500/50 focus:outline-none"
        />
        <label className="flex min-h-[36px] shrink-0 cursor-pointer items-center gap-1 text-xs text-muted">
          <input
            type="checkbox"
            checked={seat.is_moderator}
            onChange={(e) => onChange(index, "is_moderator", e.target.checked)}
            className="h-3.5 w-3.5 cursor-pointer accent-green-500"
            aria-label={`席位 ${index + 1} 是否为主持人`}
          />
          主持
        </label>
        {canRemove && (
          <button
            type="button"
            onClick={() => onRemove(index)}
            aria-label={`移除席位：${seat.role_name || `席位 ${index + 1}`}`}
            className="-my-1 -mr-1 flex min-h-[44px] min-w-[44px] items-center justify-center rounded-lg text-muted transition-colors hover:text-red-400"
          >
            <X size={14} aria-hidden="true" />
          </button>
        )}
      </div>
      <div className="flex items-center gap-2">
        <label htmlFor={`df-seat-temp-${index}`} className="shrink-0 text-xs text-muted">
          温度
        </label>
        <input
          id={`df-seat-temp-${index}`}
          type="number"
          value={seat.temperature}
          onChange={(e) => onChange(index, "temperature", Number(e.target.value))}
          step={0.1}
          min={0}
          max={2}
          className="min-h-[36px] w-16 rounded-lg border border-border-strong bg-surface px-2 text-xs text-foreground focus:border-green-500/50 focus:outline-none"
        />
        {seat.is_moderator && (
          <span className="rounded bg-amber-500/20 px-1.5 py-0.5 text-xs font-medium text-amber-400">
            主持人
          </span>
        )}
      </div>
      <label htmlFor={`df-seat-prompt-${index}`} className="sr-only">
        席位 {index + 1} System Prompt
      </label>
      <textarea
        id={`df-seat-prompt-${index}`}
        value={seat.system_prompt}
        onChange={(e) => onChange(index, "system_prompt", e.target.value)}
        placeholder="角色的 System Prompt（留空将自动生成）"
        rows={2}
        className="min-h-[44px] w-full resize-none rounded-lg border border-border-strong bg-surface px-2 py-1.5 text-xs text-foreground placeholder:text-muted focus:border-green-500/50 focus:outline-none"
      />
    </div>
  );
}
