import { useEffect, useState } from "react";
import { Dialog, DialogContent, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Textarea } from "@/components/ui/textarea";
import { Select } from "@/components/ui/select";
import { CheckSquare, Square, Loader2, RefreshCw } from "lucide-react";
import type { Outline } from "@/types";

interface AiPreviewEditorProps {
  open: boolean;
  title: string;
  items: Outline[];
  level: "volume" | "arc" | "chapter";
  customPrompt: string;
  onClose: () => void;
  onImport: (items: Outline[]) => void;
  onRegenerate?: (customPrompt: string) => void;
  regenerating?: boolean;
}

const ACTS = ["开端", "发展", "小高潮", "转折", "大高潮", "结局"];
const STRANDS = [
  { value: "quest", label: "主线" },
  { value: "fire", label: "感情" },
  { value: "constellation", label: "世界观" },
];

export function AiPreviewEditor({
  open,
  title,
  items: initialItems,
  level,
  customPrompt: initialCustomPrompt,
  onClose,
  onImport,
  onRegenerate,
  regenerating = false,
}: AiPreviewEditorProps) {
  const [items, setItems] = useState<Outline[]>(initialItems);
  const [selectedKeys, setSelectedKeys] = useState<Set<string>>(new Set());
  const [customPrompt, setCustomPrompt] = useState(initialCustomPrompt);

  useEffect(() => {
    if (open) {
      setItems(initialItems);
      setSelectedKeys(new Set(initialItems.map((item) => String(item.id || `${item.order}-${item.title}`))));
      setCustomPrompt(initialCustomPrompt);
    }
  }, [open, initialItems, initialCustomPrompt]);

  const getKey = (item: Outline) => String(item.id || `${item.order}-${item.title}`);
  const allSelected = items.length > 0 && selectedKeys.size === items.length;

  const toggleAll = () => {
    if (allSelected) {
      setSelectedKeys(new Set());
    } else {
      setSelectedKeys(new Set(items.map(getKey)));
    }
  };

  const toggleOne = (key: string) => {
    const next = new Set(selectedKeys);
    if (next.has(key)) next.delete(key);
    else next.add(key);
    setSelectedKeys(next);
  };

  const updateItem = (key: string, patch: Partial<Outline>) => {
    setItems((prev) => prev.map((item) => (getKey(item) === key ? { ...item, ...patch } : item)));
  };

  const handleImport = () => {
    const selected = items.filter((item) => selectedKeys.has(getKey(item)));
    onImport(selected);
  };

  const handleRegenerate = () => {
    onRegenerate?.(customPrompt);
  };

  return (
    <Dialog open={open} onOpenChange={(v) => !v && onClose()}>
      <DialogContent className="max-w-3xl max-h-[85vh] flex flex-col">
        <DialogHeader>
          <DialogTitle>{title}（共 {items.length} 项）</DialogTitle>
        </DialogHeader>

        <div className="flex items-center gap-2 py-2">
          <Input
            className="flex-1"
            placeholder="修改要求后重新生成…"
            value={customPrompt}
            onChange={(e) => setCustomPrompt(e.target.value)}
          />
          {onRegenerate && (
            <Button variant="default" onClick={handleRegenerate} disabled={regenerating}>
              {regenerating ? <Loader2 className="h-4 w-4 mr-1 animate-spin" /> : <RefreshCw className="h-4 w-4 mr-1" />}
              重新生成
            </Button>
          )}
        </div>

        <div className="flex items-center justify-between py-2 border-b">
          <Button variant="ghost" size="sm" onClick={toggleAll}>
            {allSelected ? <CheckSquare className="h-4 w-4 mr-1" /> : <Square className="h-4 w-4 mr-1" />}
            {allSelected ? "取消全选" : "全选"}
          </Button>
          <span className="text-xs text-muted">已选 {selectedKeys.size} 项</span>
        </div>

        <div className="flex-1 overflow-y-auto space-y-3 pr-1">
          {items.length === 0 && (
            <div className="text-center text-sm text-muted py-8">暂无生成结果</div>
          )}
          {items.map((item) => {
            const key = getKey(item);
            const selected = selectedKeys.has(key);
            return (
              <div
                key={key}
                className={`rounded-xl border p-3 transition-colors ${selected ? "border-primary bg-primary/5" : "border-border bg-surface opacity-60"}`}
              >
                <div className="flex items-start gap-2">
                  <button onClick={() => toggleOne(key)} className="mt-1 shrink-0">
                    {selected ? <CheckSquare className="h-5 w-5 text-primary" /> : <Square className="h-5 w-5 text-muted" />}
                  </button>
                  <div className="flex-1 min-w-0 space-y-2">
                    <div className="flex gap-2">
                      <Input
                        className="w-16"
                        type="number"
                        value={item.order}
                        onChange={(e) => updateItem(key, { order: Number(e.target.value) })}
                      />
                      <Input
                        value={item.title}
                        onChange={(e) => updateItem(key, { title: e.target.value })}
                        placeholder="标题"
                      />
                      <Select value={item.act} onChange={(e) => updateItem(key, { act: e.target.value })}>
                        {ACTS.map((a) => (
                          <option key={a} value={a}>{a}</option>
                        ))}
                      </Select>
                      {level !== "volume" && (
                        <Select value={item.strand} onChange={(e) => updateItem(key, { strand: e.target.value as Outline["strand"] })}>
                          {STRANDS.map((s) => (
                            <option key={s.value} value={s.value}>{s.label}</option>
                          ))}
                        </Select>
                      )}
                    </div>
                    <Textarea
                      value={item.summary}
                      onChange={(e) => updateItem(key, { summary: e.target.value })}
                      placeholder="摘要"
                      rows={2}
                    />
                  </div>
                </div>
              </div>
            );
          })}
        </div>

        <div className="flex justify-end gap-2 pt-3 border-t">
          <Button variant="ghost" onClick={onClose}>
            放弃
          </Button>
          <Button onClick={handleImport} disabled={selectedKeys.size === 0}>
            导入 {selectedKeys.size} 项
          </Button>
        </div>
      </DialogContent>
    </Dialog>
  );
}
