import * as React from "react";
import { cn } from "@/lib/utils";

export interface BadgeProps extends React.HTMLAttributes<HTMLSpanElement> {
  variant?: "default" | "primary" | "danger" | "warning" | "success";
}

const Badge = React.forwardRef<HTMLSpanElement, BadgeProps>(
  ({ className, variant = "default", ...props }, ref) => (
    <span
      ref={ref}
      className={cn(
        "inline-flex items-center rounded-full px-2.5 py-0.5 text-xs font-semibold",
        variant === "default" && "bg-foreground/5 text-muted border border-border-strong",
        variant === "primary" && "bg-primary-muted text-primary border border-primary/20",
        variant === "danger" && "bg-danger/10 text-danger border border-danger/20",
        variant === "warning" && "bg-warning/10 text-warning border border-warning/20",
        variant === "success" && "bg-success/10 text-success border border-success/20",
        className
      )}
      {...props}
    />
  )
);
Badge.displayName = "Badge";

export { Badge };
