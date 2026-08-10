import { useEffect, useRef, useState } from "react";
import { Loader2, X, Square, CheckCircle, AlertCircle, ChevronDown, ChevronRight } from "lucide-react";
import { Dialog, DialogContent, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { Button } from "@/components/ui/button";

export interface GenStreamItem {
  id: number | string;
  title?: string;
  name?: string;
  summary?: string;
  content?: string;
  order?: number;
  category?: string;
  role?: string;
  [key: string]: any;
}

export type GenStreamType =
  | "volume" | "arc" | "chapter" | "chapter_by_volume"
  | "world" | "character";

interface GenerationStreamDialogProps {
  open: boolean;
  title: string;
  type: GenStreamType;
  /** 建立 EventSource 的工厂函数，返回 EventSource 实例 */
  createSource: () => EventSource;
  /** 关闭弹窗 */
  onClose: () => void;
  /** 全部导入/完成后回调（刷新列表） */
  onImport: (items: GenStreamItem[]) => void | Promise<void>;
  /** 单条导入回调 */
  onImportOne?: (item: GenStreamItem) => void | Promise<void>;
  /** 渲染单条卡片的自定义内容 */
  renderItem?: (item: GenStreamItem) => React.ReactNode;
}

export function GenerationStreamDialog({
  open, title, createSource, onClose, onImport, onImportOne, renderItem,
}: GenerationStreamDialogProps) {
  const [items, setItems] = useState<GenStreamItem[]>([]);
  const [status, setStatus] = useState<"generating" | "done" | "error" | "stopped">("generating");
  const [errorMsg, setErrorMsg] = useState("");
  const [progress, setProgress] = useState<{ generated: number; total: number; skipped?: number }>({ generated: 0, total: 0 });
  const [importedIds, setImportedIds] = useState<Set<string | number>>(new Set());
  const [importing, setImporting] = useState(false);
  const sourceRef = useRef<EventSource | null>(null);

  // 重置状态 + 建立 EventSource
  useEffect(() => {
    if (!open) return;
    setItems([]);
    setStatus("generating");
    setErrorMsg("");
    setProgress({ generated: 0, total: 0 });
    setImportedIds(new Set());

    const es = createSource();
    sourceRef.current = es;

    es.addEventListener("item", (e) => {
      try {
        const data = JSON.parse((e as MessageEvent).data) as GenStreamItem;
        setItems((prev) => [...prev, data]);
      } catch { /* ignore parse error */ }
    });

    es.addEventListener("progress", (e) => {
      try {
        const data = JSON.parse((e as MessageEvent).data);
        setProgress({ generated: data.generated || 0, total: data.total || 0, skipped: data.skipped });
      } catch { /* ignore */ }
    });

    es.addEventListener("done", (e) => {
      try {
        const data = JSON.parse((e as MessageEvent).data);
        if (data.interrupted) {
          setStatus("stopped");
        } else {
          setStatus("done");
        }
      } catch {
        setStatus("done");
      }
      es.close();
    });

    es.addEventListener("error", (e) => {
      // SSE error 事件：尝试解析错误信息
      let msg = "生成过程中出错";
      try {
        const data = JSON.parse((e as MessageEvent).data || "{}");
        if (data.error) msg = data.error;
        if (data.partial_count !== undefined && data.partial_count > 0) {
          msg += `（已生成 ${data.partial_count} 条）`;
        }
      } catch { /* EventSource 原生 error 没有 data */ }
      // EventSource 原生 onerror（连接断开）也会进入这里
      // 如果已经有 items 了，说明是中断；否则是真错误
      setStatus("error");
      setErrorMsg(msg);
      es.close();
    });

    // 防止 EventSource 自动重连
    es.onerror = () => {
      // 不在这里 setStatus，让 error event listener 处理
    };

    return () => {
      es.close();
      sourceRef.current = null;
    };
  }, [open]);

  const handleStop = () => {
    if (sourceRef.current) {
      sourceRef.current.close();
      sourceRef.current = null;
    }
    setStatus("stopped");
  };

  const handleImportAll = async () => {
    setImporting(true);
    try {
      await onImport(items);
      // 标记全部已导入
      setImportedIds(new Set(items.map((i) => i.id)));
    } finally {
      setImporting(false);
    }
  };

  const handleImportOne = async (item: GenStreamItem) => {
    if (importedIds.has(item.id)) return;
    if (onImportOne) {
      await onImportOne(item);
    } else {
      await onImport([item]);
    }
    setImportedIds((prev) => new Set([...prev, item.id]));
  };

  const handleClose = () => {
    if (sourceRef.current) {
      sourceRef.current.close();
      sourceRef.current = null;
    }
    onClose();
  };

  const pct = progress.total > 0 ? Math.round((progress.generated / progress.total) * 100) : 0;
  const statusText = {
    generating: "AI 生成中…",
    done: `生成完成（共 ${items.length} 条）`,
    error: `生成出错：${errorMsg}`,
    stopped: `已停止（已生成 ${items.length} 条）`,
  }[status];

  return (
    <Dialog open={open} onOpenChange={(v) => !v && handleClose()}>
      <DialogContent className="max-w-3xl max-h-[85vh] flex flex-col">
        <DialogHeader>
          <DialogTitle className="flex items-center gap-2">
            {status === "generating" && <Loader2 className="h-5 w-5 animate-spin text-primary" />}
            {status === "done" && <CheckCircle className="h-5 w-5 text-success" />}
            {(status === "error" || status === "stopped") && <AlertCircle className="h-5 w-5 text-warning" />}
            AI 生成{title}
          </DialogTitle>
        </DialogHeader>

        {/* 进度区 */}
        <div className="space-y-2 mb-3">
          <div className="flex items-center justify-between text-sm">
            <span className={status === "error" ? "text-destructive" : status === "done" ? "text-success" : "text-muted"}>
              {statusText}
            </span>
            <span className="text-xs text-muted">
              {progress.total > 0
                ? `${progress.generated} / ${progress.total}${progress.skipped ? `（跳过 ${progress.skipped}）` : ""}`
                : `已生成 ${items.length} 条`}
            </span>
          </div>
          {status === "generating" && progress.total > 0 && (
            <div className="h-1.5 bg-border rounded-full overflow-hidden">
              <div className="h-full bg-primary transition-all duration-300" style={{ width: `${pct}%` }} />
            </div>
          )}
        </div>

        {/* 条目列表 */}
        <div className="flex-1 overflow-y-auto space-y-2 min-h-[200px]">
          {items.length === 0 && status === "generating" && (
            <div className="flex flex-col items-center justify-center py-12 text-muted">
              <Loader2 className="h-8 w-8 animate-spin mb-3" />
              <p className="text-sm">AI 正在思考中，稍候片刻…</p>
            </div>
          )}
          {items.length === 0 && status === "error" && (
            <div className="flex flex-col items-center justify-center py-12 text-destructive">
              <AlertCircle className="h-8 w-8 mb-3" />
              <p className="text-sm">{errorMsg}</p>
            </div>
          )}
          {items.map((item, idx) => (
            <StreamItemCard
              key={`${item.id}-${idx}`}
              item={item}
              index={idx}
              imported={importedIds.has(item.id)}
              onImport={() => handleImportOne(item)}
              renderItem={renderItem}
            />
          ))}
        </div>

        {/* 底部按钮 */}
        <div className="flex items-center justify-between pt-3 border-t border-border">
          <div className="text-xs text-muted">
            {importedIds.size > 0 ? `已导入 ${importedIds.size} 条` : ""}
          </div>
          <div className="flex gap-2">
            {status === "generating" && (
              <Button variant="danger" onClick={handleStop}>
                <Square className="h-3.5 w-3.5 mr-1" /> 停止生成
              </Button>
            )}
            {(status === "done" || status === "stopped" || (status === "error" && items.length > 0)) && items.length > 0 && (
              <Button variant="primary" onClick={handleImportAll} disabled={importing || importedIds.size === items.length}>
                {importing ? <Loader2 className="h-3.5 w-3.5 mr-1 animate-spin" /> : <CheckCircle className="h-3.5 w-3.5 mr-1" />}
                {importedIds.size === items.length ? "全部已导入" : `全部导入（${items.length - importedIds.size} 条待导入）`}
              </Button>
            )}
            <Button variant="ghost" onClick={handleClose}>
              <X className="h-3.5 w-3.5 mr-1" /> 关闭
            </Button>
          </div>
        </div>
      </DialogContent>
    </Dialog>
  );
}

function StreamItemCard({
  item, index, imported, onImport, renderItem,
}: {
  item: GenStreamItem;
  index: number;
  imported: boolean;
  onImport: () => void;
  renderItem?: (item: GenStreamItem) => React.ReactNode;
}) {
  const [expanded, setExpanded] = useState(false);

  const title = item.title || item.name || `第 ${index + 1} 条`;
  const summary = item.summary || item.content || "";
  const showExpand = summary.length > 120;

  return (
    <div className="border border-border rounded-xl p-3 hover:border-primary/30 transition-colors animate-in fade-in slide-in-from-bottom-1 duration-300">
      <div className="flex items-start gap-3">
        <div className="flex-1 min-w-0">
          {renderItem ? (
            renderItem(item)
          ) : (
            <>
              <div className="font-medium text-sm flex items-center gap-2">
                {showExpand ? (
                  <button onClick={() => setExpanded(!expanded)} className="shrink-0">
                    {expanded ? <ChevronDown className="h-3.5 w-3.5" /> : <ChevronRight className="h-3.5 w-3.5" />}
                  </button>
                ) : null}
                {item.order != null && <span className="text-muted">#{item.order}</span>}
                <span>{title}</span>
                {item.category && <span className="text-xs text-muted">[{item.category}]</span>}
                {item.role && <span className="text-xs text-muted">[{item.role}]</span>}
              </div>
              <div className={`text-xs text-muted mt-1 ${!expanded && showExpand ? "line-clamp-2" : ""}`}>
                {summary}
              </div>
            </>
          )}
        </div>
        <Button
          size="sm"
          variant={imported ? "ghost" : "outline"}
          onClick={onImport}
          disabled={imported}
          className="shrink-0"
        >
          {imported ? <><CheckCircle className="h-3 w-3 mr-1" /> 已导入</> : "导入此条"}
        </Button>
      </div>
    </div>
  );
}
