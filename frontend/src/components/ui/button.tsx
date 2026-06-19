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
          "inline-flex items-center justify-center rounded-xl font-semibold transition-all active:scale-[0.98]",
          "focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary/50",
          "disabled:pointer-events-none disabled:opacity-50 disabled:shadow-none",
          variant === "default" && "bg-surface hover:bg-surface-hover text-foreground border border-border shadow-sm hover:shadow hover:border-border-strong",
          variant === "primary" && "bg-primary hover:bg-primary-hover text-primary-foreground shadow-md shadow-primary/20 hover:shadow-lg hover:shadow-primary/25 hover:-translate-y-px",
          variant === "ghost" && "hover:bg-foreground/5 text-foreground",
          variant === "outline" && "border border-border-strong bg-transparent hover:bg-foreground/5 hover:border-border",
          variant === "danger" && "bg-danger hover:bg-danger-hover text-primary-foreground shadow-md shadow-danger/20 hover:shadow-lg hover:shadow-danger/25 hover:-translate-y-px",
          size === "sm" && "h-8 px-3 text-xs",
          size === "md" && "h-10 px-4 text-sm",
          size === "lg" && "h-12 px-6 text-base",
          className
        )}
        {...props}
      />
    );
  }
);
Button.displayName = "Button";

export { Button };
