/**
 * 通用确认对话框（红色危险确认按钮）
 */
import { useEffect, useRef } from "react";

interface Props {
  open: boolean;
  title: string;
  message: string;
  confirmText?: string;
  onConfirm: () => void;
  onCancel: () => void;
}

export default function ConfirmDialog({ open, title, message, confirmText = "确认", onConfirm, onCancel }: Props) {
  const confirmBtnRef = useRef<HTMLButtonElement>(null);

  // 打开时聚焦确认按钮，便于键盘操作
  useEffect(() => {
    if (open) {
      const timer = setTimeout(() => confirmBtnRef.current?.focus(), 50);
      return () => clearTimeout(timer);
    }
  }, [open]);

  if (!open) return null;

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/60"
      onClick={onCancel}
      onKeyDown={(e) => { if (e.key === "Escape") onCancel(); }}
      role="presentation"
    >
      <div
        className="bg-surface-elevated border border-border/60 rounded-xl p-5 w-[400px] max-w-[calc(100vw-2rem)] shadow-2xl"
        onClick={(e) => e.stopPropagation()}
        role="dialog"
        aria-modal="true"
        aria-label={title}
      >
        <h3 className="text-sm font-medium text-foreground mb-2">{title}</h3>
        <p className="text-xs text-muted mb-5">{message}</p>
        <div className="flex items-center justify-end gap-2">
          <button
            type="button"
            onClick={onCancel}
            className="px-3 py-1.5 text-xs rounded-lg bg-secondary text-muted hover:text-foreground hover:bg-surface-hover transition-colors duration-200 cursor-pointer min-h-[44px]"
          >
            取消
          </button>
          <button
            ref={confirmBtnRef}
            type="button"
            onClick={onConfirm}
            className="px-4 py-1.5 text-xs rounded-lg bg-red-500 text-white hover:bg-red-400 transition-colors duration-200 cursor-pointer min-h-[44px]"
          >
            {confirmText}
          </button>
        </div>
      </div>
    </div>
  );
}
