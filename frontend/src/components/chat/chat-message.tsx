import { User, Bot } from "lucide-react";
import { cn } from "@/lib/utils";
import { ChatActionBadge } from "./chat-action-badge";
import type { ChatMessageItem } from "@/types/chat";

interface ChatMessageProps {
  message: ChatMessageItem;
}

export function ChatMessage({ message }: ChatMessageProps) {
  const isUser = message.role === "user";
  return (
    <div className={cn("flex gap-2", isUser ? "flex-row-reverse" : "flex-row")}>
      <div className={cn("w-7 h-7 rounded-full flex items-center justify-center shrink-0", isUser ? "bg-primary text-primary-foreground" : "bg-surface border border-border")}>
        {isUser ? <User className="w-4 h-4" /> : <Bot className="w-4 h-4" />}
      </div>
      <div className={cn("max-w-[80%] rounded-2xl px-3 py-2 text-sm", isUser ? "bg-primary text-primary-foreground" : "bg-surface border border-border")}>
        <div className="whitespace-pre-wrap">{message.content}</div>
        {message.actions && message.actions.length > 0 && (
          <div className="mt-2 flex flex-wrap gap-1">
            {message.actions.map((action, i) => (
              <ChatActionBadge key={i} action={action} />
            ))}
          </div>
        )}
      </div>
    </div>
  );
}
