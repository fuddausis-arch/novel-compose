import { useState, useEffect } from "react";
import { Dialog, DialogContent, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { Button } from "@/components/ui/button";
import { Trash2, CheckSquare, Square } from "lucide-react";

interface AiPreviewDialogProps<T> {
  open: boolean;
  title: string;
  items: T[];
  getKey: (item: T) => string;
  renderItem: (item: T) => React.ReactNode;
  onClose: () => void;
  onImport: (items: T[]) => void;
}

export function AiPreviewDialog<T>({
  open,
  title,
  items: initialItems,
  getKey,
  renderItem,
  onClose,
  onImport,
}: AiPreviewDialogProps<T>) {
  const [items, setItems] = useState<T[]>(initialItems);
  const [selectedKeys, setSelectedKeys] = useState<Set<string>>(new Set());

  useEffect(() => {
    if (open) {
      setItems(initialItems);
      setSelectedKeys(new Set(initialItems.map(getKey)));
    }
  }, [open, initialItems, getKey]);

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



  return (
    <Dialog open={open} onOpenChange={(v) => !v && onClose()}>
      <DialogContent className="max-w-2xl max-h-[80vh] flex flex-col">
        <DialogHeader>
          <DialogTitle>{title}（共 {items.length} 项）</DialogTitle>
        </DialogHeader>
        <div className="flex items-center justify-between py-2 border-b">
          <Button variant="ghost" size="sm" onClick={toggleAll}>
            {allSelected ? <CheckSquare className="h-4 w-4 mr-1" /> : <Square className="h-4 w-4 mr-1" />}
            {allSelected ? "取消全选" : "全选"}
          </Button>
          <span className="text-xs text-muted">已选 {selectedKeys.size} 项</span>
        </div>
        <div className="flex-1 overflow-y-auto space-y-2 pr-1">
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
                  <button onClick={() => toggleOne(key)} className="mt-0.5 shrink-0">
                    {selected ? <CheckSquare className="h-5 w-5 text-primary" /> : <Square className="h-5 w-5 text-muted" />}
                  </button>
                  <div className="flex-1 min-w-0">{renderItem(item)}</div>
                  <button
                    onClick={() => toggleOne(key)}
                    className="p-1 hover:bg-foreground/5 rounded shrink-0"
                    title={selected ? "不导入此项" : "导入此项"}
                  >
                    <Trash2 className={`h-3.5 w-3.5 ${selected ? "text-danger" : "text-muted"}`} />
                  </button>
                </div>
              </div>
            );
          })}
        </div>
        <div className="flex justify-end gap-2 pt-3 border-t">
          <Button variant="ghost" onClick={onClose}>
            放弃
          </Button>
          <Button
            onClick={() => {
              const selected = items.filter((item) => selectedKeys.has(getKey(item)));
              onImport(selected);
            }}
            disabled={selectedKeys.size === 0}
          >
            导入 {selectedKeys.size} 项到框架
          </Button>
        </div>
      </DialogContent>
    </Dialog>
  );
}
