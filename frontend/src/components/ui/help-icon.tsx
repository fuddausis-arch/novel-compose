import { useState } from "react";
import { HelpCircle } from "lucide-react";
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
  DialogTrigger,
} from "@/components/ui/dialog";
import { cn } from "@/lib/utils";

export interface HelpIconProps {
  /** 弹窗标题 */
  title: string;
  /** 帮助说明正文，支持换行 */
  content: string;
  /** 额外样式 */
  className?: string;
  /** 问号大小：sm=小, md=默认 */
  size?: "sm" | "md";
}

/**
 * 通用帮助问号组件。
 * 点击后弹出 Dialog 解释当前功能。
 */
export function HelpIcon({ title, content, className, size = "md" }: HelpIconProps) {
  const [open, setOpen] = useState(false);
  return (
    <Dialog open={open} onOpenChange={setOpen}>
      <DialogTrigger asChild>
        <button
          type="button"
          className={cn(
            "inline-flex shrink-0 items-center justify-center rounded-full text-muted hover:text-foreground hover:bg-foreground/10 transition-colors focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-primary",
            size === "sm" ? "h-4 w-4" : "h-5 w-5",
            className
          )}
          aria-label={`帮助：${title}`}
          onClick={(e) => e.stopPropagation()}
        >
          <HelpCircle className={cn(size === "sm" ? "h-3 w-3" : "h-4 w-4")} />
        </button>
      </DialogTrigger>
      <DialogContent className="max-w-md">
        <DialogHeader>
          <DialogTitle className="text-base flex items-center gap-2">
            <HelpCircle className="h-4 w-4 text-primary" />
            {title}
          </DialogTitle>
        </DialogHeader>
        <div className="text-sm text-foreground/80 whitespace-pre-wrap leading-relaxed">
          {content}
        </div>
      </DialogContent>
    </Dialog>
  );
}
