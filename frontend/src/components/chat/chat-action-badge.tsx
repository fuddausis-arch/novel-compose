import { Loader2, CheckCircle2, XCircle, Play } from "lucide-react";
import { cn } from "@/lib/utils";
import type { ChatActionEvent } from "@/types/chat";

interface ChatActionBadgeProps {
  action: ChatActionEvent;
}

export function ChatActionBadge({ action }: ChatActionBadgeProps) {
  const { status, type } = action;
  const label = {
    rewrite_chapter: "重写章节",
    add_chapter_feedback: "记录反馈",
    generate_outlines: "生成大纲",
    query_status: "查询状态",
  }[type] || type;

  const icon =
    status === "dispatched" ? <Loader2 className="w-3 h-3 animate-spin" /> :
    status === "done" ? <CheckCircle2 className="w-3 h-3" /> :
    status === "failed" ? <XCircle className="w-3 h-3" /> :
    <Play className="w-3 h-3" />;

  return (
    <span className={cn(
      "inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-xs border",
      status === "done" ? "border-success text-success" :
      status === "failed" ? "border-danger text-danger" :
      "border-primary text-primary"
    )}>
      {icon}
      {label}
    </span>
  );
}
