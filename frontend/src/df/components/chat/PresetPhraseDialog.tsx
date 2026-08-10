/**
 * 预设短语编辑弹窗
 *
 * 列表 + 新增/编辑表单 + 删除。数据字段对接本项目后端：
 * { id, category(分类), text(实际注入内容), shortcut(显示名) }
 */
import { useEffect, useRef, useState } from "react";
import { Edit3, Trash2, X } from "lucide-react";
import type { PresetPhrase } from "./api";

export interface PresetPhraseInput {
  category: string;
  text: string;
  shortcut: string;
}

interface Props {
  open: boolean;
  phrases: PresetPhrase[];
  onClose: () => void;
  onSave: (id: string | null, input: PresetPhraseInput) => Promise<void>;
  onDelete: (id: string) => Promise<void>;
}

export default function PresetPhraseDialog({ open, phrases, onClose, onSave, onDelete }: Props) {
  const dialogRef = useRef<HTMLDivElement>(null);
  const [editingId, setEditingId] = useState<string | null>(null);
  const [shortcut, setShortcut] = useState("");
  const [category, setCategory] = useState("通用指令");
  const [text, setText] = useState("");
  const [saving, setSaving] = useState(false);

  // 打开时重置表单并聚焦第一个输入框
  useEffect(() => {
    if (!open) return;
    setEditingId(null);
    setShortcut("");
    setCategory("通用指令");
    setText("");
    const firstInput = dialogRef.current?.querySelector<HTMLInputElement>("input");
    firstInput?.focus();
  }, [open]);

  if (!open) return null;

  const startEdit = (phrase: PresetPhrase) => {
    setEditingId(phrase.id);
    setShortcut(phrase.shortcut);
    setCategory(phrase.category || "通用指令");
    setText(phrase.text);
  };

  const resetForm = () => {
    setEditingId(null);
    setShortcut("");
    setCategory("通用指令");
    setText("");
  };

  const handleSave = async () => {
    if (!text.trim() || saving) return;
    setSaving(true);
    try {
      await onSave(editingId, {
        shortcut: shortcut.trim(),
        category: category.trim() || "通用指令",
        text: text.trim(),
      });
      resetForm();
    } finally {
      setSaving(false);
    }
  };

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/60"
      onClick={onClose}
      onKeyDown={(e) => { if (e.key === "Escape") onClose(); }}
      role="presentation"
    >
      <div
        ref={dialogRef}
        className="bg-surface-elevated border border-border/60 rounded-xl p-5 w-[460px] max-w-[calc(100vw-2rem)] max-h-[80vh] overflow-y-auto shadow-2xl"
        onClick={(e) => e.stopPropagation()}
        role="dialog"
        aria-modal="true"
        aria-label={editingId ? "编辑预设短语" : "新增预设短语"}
      >
        <div className="flex items-center justify-between mb-4">
          <h3 className="text-sm font-medium text-foreground">{editingId ? "编辑预设短语" : "预设短语管理"}</h3>
          <button
            type="button"
            onClick={onClose}
            aria-label="关闭对话框"
            className="p-1 rounded-md text-muted hover:text-foreground hover:bg-secondary cursor-pointer min-h-[44px] min-w-[44px] flex items-center justify-center"
          >
            <X size={16} aria-hidden="true" />
          </button>
        </div>

        {/* 已有短语列表 */}
        {phrases.length > 0 && (
          <div className="space-y-1.5 mb-4 max-h-48 overflow-y-auto">
            {phrases.map((phrase) => (
              <div
                key={phrase.id}
                className={`flex items-center justify-between px-3 py-2 rounded-lg text-xs ${
                  editingId === phrase.id
                    ? "bg-indigo-500/15 border border-indigo-500/30"
                    : "bg-secondary hover:bg-secondary border border-transparent"
                }`}
              >
                <div className="flex-1 min-w-0 mr-2">
                  <div className="text-foreground font-medium truncate">
                    {phrase.shortcut || phrase.text.slice(0, 16)}
                    <span className="ml-2 text-muted/60 font-normal">{phrase.category}</span>
                  </div>
                  <div className="text-muted truncate">{phrase.text}</div>
                </div>
                <div className="flex items-center gap-1 flex-shrink-0">
                  <button
                    type="button"
                    onClick={() => startEdit(phrase)}
                    className="p-1 rounded text-muted hover:text-cyan-400 hover:bg-surface-hover cursor-pointer min-h-[32px] min-w-[32px] flex items-center justify-center"
                    title="编辑"
                    aria-label={`编辑短语: ${phrase.shortcut || phrase.text.slice(0, 12)}`}
                  >
                    <Edit3 size={12} aria-hidden="true" />
                  </button>
                  <button
                    type="button"
                    onClick={() => void onDelete(phrase.id)}
                    className="p-1 rounded text-muted hover:text-red-400 hover:bg-surface-hover cursor-pointer min-h-[32px] min-w-[32px] flex items-center justify-center"
                    title="删除"
                    aria-label={`删除短语: ${phrase.shortcut || phrase.text.slice(0, 12)}`}
                  >
                    <Trash2 size={12} aria-hidden="true" />
                  </button>
                </div>
              </div>
            ))}
          </div>
        )}

        {/* 新增/编辑表单 */}
        <div className="space-y-3">
          <div className="flex gap-2">
            <div className="flex-1">
              <label htmlFor="df-preset-shortcut" className="text-xs text-muted block mb-1">显示名</label>
              <input
                id="df-preset-shortcut"
                value={shortcut}
                onChange={(e) => setShortcut(e.target.value)}
                placeholder="例如：润色这段"
                className="w-full px-3 py-2 text-sm bg-secondary border border-border/60 rounded-lg text-foreground placeholder:text-muted outline-none focus:border-indigo-500/60 transition-colors"
              />
            </div>
            <div className="w-32">
              <label htmlFor="df-preset-category" className="text-xs text-muted block mb-1">分类</label>
              <input
                id="df-preset-category"
                value={category}
                onChange={(e) => setCategory(e.target.value)}
                placeholder="通用指令"
                className="w-full px-3 py-2 text-sm bg-secondary border border-border/60 rounded-lg text-foreground placeholder:text-muted outline-none focus:border-indigo-500/60 transition-colors"
              />
            </div>
          </div>
          <div>
            <label htmlFor="df-preset-text" className="text-xs text-muted block mb-1">实际输入内容</label>
            <textarea
              id="df-preset-text"
              value={text}
              onChange={(e) => setText(e.target.value)}
              placeholder="点击短语时实际发送给 AI 的文本..."
              rows={3}
              className="w-full px-3 py-2 text-sm bg-secondary border border-border/60 rounded-lg text-foreground placeholder:text-muted outline-none focus:border-indigo-500/60 transition-colors resize-none"
            />
          </div>
          <div className="flex items-center justify-end gap-2 pt-1">
            {editingId && (
              <button
                type="button"
                onClick={resetForm}
                className="px-3 py-1.5 text-xs rounded-lg bg-secondary text-muted hover:text-foreground hover:bg-surface-hover transition-colors cursor-pointer min-h-[44px]"
              >
                取消编辑
              </button>
            )}
            <button
              type="button"
              onClick={onClose}
              className="px-3 py-1.5 text-xs rounded-lg bg-secondary text-muted hover:text-foreground hover:bg-surface-hover transition-colors cursor-pointer min-h-[44px]"
            >
              关闭
            </button>
            <button
              type="button"
              onClick={() => void handleSave()}
              disabled={!text.trim() || saving}
              className="px-4 py-1.5 text-xs rounded-lg bg-indigo-500 text-white hover:bg-indigo-400 transition-colors disabled:opacity-40 disabled:cursor-not-allowed cursor-pointer min-h-[44px]"
            >
              {editingId ? "保存" : "添加"}
            </button>
          </div>
        </div>
      </div>
    </div>
  );
}
