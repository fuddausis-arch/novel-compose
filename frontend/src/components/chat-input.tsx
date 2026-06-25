import { Send } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Textarea } from "@/components/ui/textarea";

interface ChatInputProps {
  value: string;
  onChange: (value: string) => void;
  onSend: () => void;
  loading?: boolean;
}

export function ChatInput({ value, onChange, onSend, loading }: ChatInputProps) {
  return (
    <div className="flex items-end gap-2 p-3 border-t border-border bg-surface/50">
      <Textarea
        value={value}
        onChange={(e) => onChange(e.target.value)}
        placeholder="输入消息，让 AI 帮你调整…"
        className="min-h-[44px] max-h-[120px] resize-none py-2.5"
        onKeyDown={(e) => {
          if (e.key === "Enter" && !e.shiftKey) {
            e.preventDefault();
            onSend();
          }
        }}
        disabled={loading}
      />
      <Button size="sm" variant="primary" onClick={onSend} disabled={loading || !value.trim()}>
        <Send className="w-4 h-4" />
      </Button>
    </div>
  );
}
