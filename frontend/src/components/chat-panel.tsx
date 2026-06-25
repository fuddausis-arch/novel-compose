import { useState, useEffect, useRef } from "react";
import { MessageSquare, PanelRightClose, PanelRightOpen, Trash2 } from "lucide-react";
import { Button } from "@/components/ui/button";
import { ChatMessage } from "@/components/chat-message";
import { ChatInput } from "@/components/chat-input";
import { useChat } from "@/hooks/useChat";
import { cn } from "@/lib/utils";
import type { ChatObjectType, ChatSessionType } from "@/types/chat";

interface ChatPanelProps {
  projectId: number;
  objectType: ChatObjectType | "";
  objectId: string | number;
  title?: string;
}

const STORAGE_KEY = "chat-panel-open";

export function ChatPanel({ projectId, objectType, objectId, title }: ChatPanelProps) {
  const [open, setOpen] = useState(() => {
    try {
      return localStorage.getItem(STORAGE_KEY) === "true";
    } catch {
      return false;
    }
  });
  const scrollRef = useRef<HTMLDivElement>(null);
  const { mode, setMode, messages, input, setInput, loading, send, clearSession } = useChat({
    projectId,
    objectType,
    objectId,
    title,
  });

  useEffect(() => {
    localStorage.setItem(STORAGE_KEY, String(open));
  }, [open]);

  useEffect(() => {
    if (scrollRef.current) {
      scrollRef.current.scrollTop = scrollRef.current.scrollHeight;
    }
  }, [messages, loading]);

  const tabButton = (label: string, value: ChatSessionType) => (
    <button
      key={value}
      onClick={() => setMode(value)}
      className={cn(
        "px-3 py-1.5 rounded-lg text-xs font-medium transition-colors",
        mode === value ? "bg-primary/10 text-primary" : "text-muted hover:bg-foreground/5"
      )}
    >
      {label}
    </button>
  );

  return (
    <div className={cn("flex h-full shrink-0 transition-all duration-200", open ? "w-[400px]" : "w-10")}>
      <div className="h-full flex flex-col border-l border-border bg-background">
        <button
          onClick={() => setOpen((v) => !v)}
          className="w-10 h-full flex flex-col items-center justify-center gap-2 py-3 text-muted hover:text-foreground hover:bg-foreground/5"
          title={open ? "收起聊天" : "展开聊天"}
        >
          {open ? <PanelRightClose className="w-4 h-4" /> : <PanelRightOpen className="w-4 h-4" />}
          {!open && <MessageSquare className="w-4 h-4" />}
          {!open && <span className="text-[10px] [writing-mode:vertical-lr]">AI 对话</span>}
        </button>
      </div>
      {open && (
        <div className="w-[360px] h-full flex flex-col border-l border-border bg-surface/30">
          <div className="flex items-center justify-between px-3 py-2 border-b border-border">
            <div className="flex items-center gap-1">
              {tabButton("对象对话", "object")}
              {tabButton("全局对话", "global")}
            </div>
            <Button size="sm" variant="ghost" onClick={clearSession} title="清空当前会话">
              <Trash2 className="w-3.5 h-3.5 text-muted" />
            </Button>
          </div>
          <div ref={scrollRef} className="flex-1 overflow-y-auto p-3 space-y-3">
            {messages.length === 0 && (
              <div className="text-xs text-muted text-center mt-10">
                {mode === "object"
                  ? `这是「${title || objectType || "当前对象"}」的专属对话，历史按对象隔离。`
                  : "这是项目级全局对话，可询问整体进度或下指令。"}
              </div>
            )}
            {messages.map((m) => (
              <ChatMessage key={m.id} message={m} />
            ))}
            {loading && (
              <div className="text-xs text-muted flex items-center gap-1">
                <span className="inline-block w-1.5 h-1.5 rounded-full bg-primary animate-pulse" />
                AI 思考中…
              </div>
            )}
          </div>
          <ChatInput value={input} onChange={setInput} onSend={send} loading={loading} />
        </div>
      )}
    </div>
  );
}
