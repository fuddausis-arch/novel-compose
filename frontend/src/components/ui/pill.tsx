import { cn } from "@/lib/utils";

export interface PillProps {
  active?: boolean;
  children: React.ReactNode;
  onClick?: () => void;
}

export function Pill({ active, children, onClick }: PillProps) {
  return (
    <button
      type="button"
      onClick={onClick}
      className={cn(
        "inline-flex items-center justify-center rounded-full px-3 py-1.5 text-sm font-medium transition-all",
        active && "bg-primary text-primary-foreground shadow-sm",
        !active && "text-muted hover:text-foreground hover:bg-foreground/5"
      )}
    >
      {children}
    </button>
  );
}
