import { cn } from "@/lib/utils";

interface FilterSelectProps {
  value: string;
  onChange: (value: string) => void;
  options: string[];
  /** 空值占位选项文案（如 "全部类型"） */
  placeholder?: string;
  className?: string;
  ariaLabel?: string;
}

/** 通用筛选下拉：圆角边框 + 选项列表 + 空值占位项 */
export function FilterSelect({ value, onChange, options, placeholder, className, ariaLabel }: FilterSelectProps) {
  return (
    <select
      value={value}
      onChange={(e) => onChange(e.target.value)}
      aria-label={ariaLabel}
      className={cn(
        "h-10 rounded-xl border border-border-strong bg-surface px-3 text-sm text-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary/50",
        className,
      )}
    >
      {placeholder && <option value="">{placeholder}</option>}
      {options.map((o) => (
        <option key={o} value={o}>
          {o}
        </option>
      ))}
    </select>
  );
}
