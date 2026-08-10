/**
 * 对话输入区
 *
 * 布局（自上而下）：
 * a. 预设短语栏（group hover 显示编辑按钮）
 * b. 快捷按钮栏（压缩上下文——后端未支持，禁用态）
 * c. 输入框：多行 textarea（Enter 发送 / Shift+Enter 换行），
 *    左下回形针附件按钮，右下模型选择器胶囊 + 圆形发送/停止按钮
 */
import {
  useEffect, useRef, useState, type KeyboardEvent, type ReactNode,
} from "react";
import { Edit3, Loader2, Minimize2, Paperclip, Send, Square } from "lucide-react";
import type { PresetPhrase } from "./api";

export interface ComposerProps {
  onSend: (text: string) => void;
  onAbort: () => void;
  streaming: boolean;
  /** 会话就绪（已选项目且未在流式中） */
  sendEnabled: boolean;
  placeholder: string;
  presetPhrases: PresetPhrase[];
  onPresetClick: (phrase: PresetPhrase) => void;
  onOpenPresetEditor: () => void;
  onAttach: (file: File) => void;
  /** 附件上传中 */
  attaching?: boolean;
  /** 模型选择器等右侧控件 */
  trailingControls?: ReactNode;
  /** 会话标识：切换会话时清空草稿 */
  conversationKey: string;
  /** 请求向草稿中插入文本（如附件标记），nonce 变化时触发 */
  insertRequest?: { text: string; nonce: number } | null;
}

export default function Composer({
  onSend,
  onAbort,
  streaming,
  sendEnabled,
  placeholder,
  presetPhrases,
  onPresetClick,
  onOpenPresetEditor,
  onAttach,
  attaching = false,
  trailingControls,
  conversationKey,
  insertRequest,
}: ComposerProps) {
  const [value, setValue] = useState("");
  const textareaRef = useRef<HTMLTextAreaElement>(null);
  const fileInputRef = useRef<HTMLInputElement>(null);

  // 切换会话时清空输入草稿
  useEffect(() => {
    setValue("");
  }, [conversationKey]);

  // 外部请求插入文本（附件上传成功后插入 [附件：name] 标记）
  useEffect(() => {
    if (!insertRequest) return;
    setValue((prev) => (prev ? `${prev}\n${insertRequest.text}` : insertRequest.text));
    // 等 DOM 更新后重算高度
    requestAnimationFrame(() => {
      const el = textareaRef.current;
      if (!el) return;
      el.style.height = "auto";
      el.style.height = `${Math.min(el.scrollHeight, 160)}px`;
    });
  }, [insertRequest]);

  // textarea 高度自适应内容
  const autoResize = () => {
    const el = textareaRef.current;
    if (!el) return;
    el.style.height = "auto";
    el.style.height = `${Math.min(el.scrollHeight, 160)}px`;
  };

  const handleSend = () => {
    const text = value.trim();
    if (!text || !sendEnabled || streaming) return;
    onSend(text);
    setValue("");
    requestAnimationFrame(autoResize);
  };

  const handleKeyDown = (e: KeyboardEvent<HTMLTextAreaElement>) => {
    if (e.nativeEvent.isComposing) return; // 中文输入法合成中不触发发送
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      handleSend();
    }
  };

  const canSubmit = sendEnabled && value.trim().length > 0 && !streaming;

  return (
    <div className="space-y-2">
      {/* 预设短语栏 */}
      <div className="group flex items-center gap-1.5 flex-wrap min-h-[28px]" role="toolbar" aria-label="预设短语">
        <div className="flex-1 flex items-center gap-1.5 flex-wrap">
          {presetPhrases.length === 0 ? (
            <span className="text-xs text-muted/40 italic">暂无预设短语，点击右侧编辑按钮添加</span>
          ) : (
            presetPhrases.map((phrase) => (
              <button
                type="button"
                key={phrase.id}
                onClick={() => onPresetClick(phrase)}
                disabled={!sendEnabled || streaming}
                title={phrase.text}
                aria-label={`发送预设短语: ${phrase.shortcut || phrase.text}`}
                className="px-2.5 py-1 text-xs rounded-full bg-surface-hover text-foreground hover:bg-indigo-500/20 hover:text-indigo-400 border border-border/40 transition-colors duration-200 disabled:opacity-40 disabled:cursor-not-allowed cursor-pointer whitespace-nowrap"
              >
                {phrase.shortcut || phrase.text.slice(0, 12)}
              </button>
            ))
          )}
        </div>
        <button
          type="button"
          onClick={onOpenPresetEditor}
          title="编辑预设短语"
          aria-label="编辑预设短语"
          className="p-1.5 rounded-md text-muted hover:text-indigo-400 hover:bg-indigo-500/10 opacity-0 group-hover:opacity-100 transition-all cursor-pointer flex-shrink-0 min-h-[44px] min-w-[44px] flex items-center justify-center"
        >
          <Edit3 size={14} aria-hidden="true" />
        </button>
      </div>

      {/* 快捷按钮栏 */}
      <div className="flex items-center gap-2" role="toolbar" aria-label="快捷操作">
        <button
          type="button"
          disabled
          title="后端暂未支持上下文压缩"
          aria-label="压缩上下文（暂未支持）"
          className="flex items-center gap-1 px-2.5 py-1 text-xs rounded-md bg-surface-hover text-muted border border-border/40 transition-colors duration-200 hover:bg-purple-500/20 hover:text-purple-400 cursor-pointer disabled:opacity-40 disabled:cursor-not-allowed disabled:hover:bg-surface-hover disabled:hover:text-muted"
        >
          <Minimize2 size={12} aria-hidden="true" />
          压缩上下文
        </button>
      </div>

      {/* 输入框 */}
      <div className="rounded-2xl bg-surface-elevated border border-border/60 p-2.5 transition-[border-color,box-shadow] duration-200 focus-within:border-indigo-500/60 focus-within:ring-2 focus-within:ring-indigo-500/35">
        <textarea
          ref={textareaRef}
          value={value}
          onChange={(e) => { setValue(e.target.value); autoResize(); }}
          onKeyDown={handleKeyDown}
          placeholder={placeholder}
          disabled={!sendEnabled && !streaming}
          rows={2}
          aria-label="聊天消息输入"
          className="w-full resize-none overflow-y-auto rounded-lg border-none bg-transparent px-2 py-1 text-sm text-foreground placeholder:text-muted outline-none max-h-40 min-h-12 disabled:cursor-not-allowed disabled:opacity-50"
        />
        <div className="mt-2 flex min-h-10 items-center justify-between gap-2">
          {/* 左下：附件按钮 */}
          <div>
            <input
              ref={fileInputRef}
              type="file"
              tabIndex={-1}
              aria-hidden="true"
              className="hidden"
              onChange={(e) => {
                const file = e.target.files?.[0];
                if (file) onAttach(file);
                e.target.value = "";
              }}
            />
            <button
              type="button"
              onClick={() => fileInputRef.current?.click()}
              disabled={streaming || attaching}
              title="上传附件到工作空间"
              aria-label="添加附件"
              className="flex h-10 w-10 items-center justify-center rounded-full text-muted transition-colors hover:bg-indigo-500/10 hover:text-indigo-300 disabled:cursor-not-allowed disabled:opacity-40 cursor-pointer"
            >
              {attaching ? (
                <Loader2 size={17} className="animate-spin motion-reduce:animate-none" aria-hidden="true" />
              ) : (
                <Paperclip size={17} aria-hidden="true" />
              )}
            </button>
          </div>
          {/* 右下：模型选择器 + 发送/停止 */}
          <div className="flex items-center justify-end gap-2">
            {trailingControls}
            {streaming ? (
              <button
                type="button"
                onClick={onAbort}
                title="停止生成"
                aria-label="停止生成"
                className="flex h-10 w-10 items-center justify-center rounded-full bg-red-500/20 text-red-400 transition-colors duration-200 hover:bg-red-500/40 cursor-pointer"
              >
                <Square size={17} className="fill-current" aria-hidden="true" />
              </button>
            ) : (
              <button
                type="button"
                onClick={handleSend}
                disabled={!canSubmit}
                aria-label="发送消息"
                className={`flex h-10 w-10 items-center justify-center rounded-full transition-colors duration-200 ${
                  canSubmit
                    ? "bg-indigo-500 text-white hover:bg-indigo-400 cursor-pointer"
                    : "cursor-not-allowed bg-secondary text-muted"
                }`}
              >
                <Send size={17} aria-hidden="true" />
              </button>
            )}
          </div>
        </div>
      </div>
    </div>
  );
}
