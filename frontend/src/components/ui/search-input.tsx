import { Search } from "lucide-react";
import { Input } from "@/components/ui/input";
import { cn } from "@/lib/utils";

interface SearchInputProps {
  value: string;
  onChange: (value: string) => void;
  placeholder?: string;
  /** 外层容器 class（如 flex-1 min-w-[200px]） */
  className?: string;
  /** 输入框 class（如 pl-9） */
  inputClassName?: string;
  /** 图标 class（如 h-4 w-4） */
  iconClassName?: string;
  ariaLabel?: string;
}

/** 通用搜索框：Search 图标 + 输入框 */
export function SearchInput({
  value,
  onChange,
  placeholder,
  className,
  inputClassName,
  iconClassName,
  ariaLabel,
}: SearchInputProps) {
  return (
    <div className={cn("relative", className)}>
      <Search
        className={cn(
          "pointer-events-none absolute left-3 top-1/2 h-3.5 w-3.5 -translate-y-1/2 text-muted",
          iconClassName,
        )}
        aria-hidden="true"
      />
      <Input
        className={cn("pl-8", inputClassName)}
        placeholder={placeholder}
        aria-label={ariaLabel}
        value={value}
        onChange={(e) => onChange(e.target.value)}
      />
    </div>
  );
}
