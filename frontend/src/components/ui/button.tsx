import * as React from "react";
import { cn } from "@/lib/utils";

export interface ButtonProps extends React.ButtonHTMLAttributes<HTMLButtonElement> {
  variant?: "default" | "ghost" | "outline" | "danger" | "primary";
  size?: "sm" | "md" | "lg";
}

const Button = React.forwardRef<HTMLButtonElement, ButtonProps>(
  ({ className, variant = "default", size = "md", ...props }, ref) => {
    return (
      <button
        ref={ref}
        className={cn(
          "inline-flex items-center justify-center gap-1.5 rounded-lg font-medium transition-colors cursor-pointer",
          "focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary/40",
          "disabled:cursor-not-allowed disabled:opacity-50",
          variant === "default" && "bg-secondary text-secondary-foreground border border-border-strong hover:bg-secondary-hover",
          variant === "primary" && "bg-primary text-primary-foreground hover:bg-primary-hover",
          variant === "ghost" && "text-muted hover:bg-surface-hover hover:text-foreground",
          variant === "outline" && "border border-border-strong bg-transparent text-foreground hover:bg-surface-hover",
          variant === "danger" && "bg-danger text-primary-foreground hover:bg-danger-hover",
          size === "sm" && "min-h-[32px] px-3 text-xs",
          size === "md" && "min-h-[36px] px-4 text-sm",
          size === "lg" && "min-h-[44px] px-5 text-sm",
          className
        )}
        {...props}
      />
    );
  }
);
Button.displayName = "Button";

export { Button };
