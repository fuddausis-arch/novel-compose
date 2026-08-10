/** DeterminFlow 融合界面 · 管理页共享 UI 组件 */
import { useEffect, type ButtonHTMLAttributes, type HTMLAttributes, type InputHTMLAttributes, type ReactNode, type SelectHTMLAttributes, type TextareaHTMLAttributes } from "react";
import { AlertCircle, ChevronDown, Loader2, Search, X, type LucideIcon } from "lucide-react";
import { cn } from "@/lib/utils";
import { StatCard } from "@/components/ui/stat-card";
import { DF_BRAND_MARK_DARK } from "../../brand";

/** 页面强调色（静态类名映射，保证 Tailwind 可检测） */
export type DFAccent = "pink" | "red" | "teal" | "indigo" | "cyan" | "amber" | "green" | "purple";

const ACCENT_BADGE: Record<DFAccent, string> = {
  pink: "bg-pink-500/10 border-pink-500/20 text-pink-400",
  red: "bg-red-500/10 border-red-500/20 text-red-400",
  teal: "bg-teal-500/10 border-teal-500/20 text-teal-400",
  indigo: "bg-indigo-500/10 border-indigo-500/20 text-indigo-400",
  cyan: "bg-cyan-500/10 border-cyan-500/20 text-cyan-400",
  amber: "bg-amber-500/10 border-amber-500/20 text-amber-400",
  green: "bg-green-500/10 border-green-500/20 text-green-400",
  purple: "bg-purple-500/10 border-purple-500/20 text-purple-400",
};

const ACCENT_TEXT: Record<DFAccent, string> = {
  pink: "text-pink-400",
  red: "text-red-400",
  teal: "text-teal-400",
  indigo: "text-indigo-400",
  cyan: "text-cyan-400",
  amber: "text-amber-400",
  green: "text-green-400",
  purple: "text-purple-400",
};

/** 实心按钮配色（DFPrimaryButton/DFDangerButton 用） */
const ACCENT_SOLID: Record<DFAccent, string> = {
  pink: "bg-pink-500 hover:bg-pink-400",
  red: "bg-red-500 hover:bg-red-400",
  teal: "bg-teal-500 hover:bg-teal-400",
  indigo: "bg-indigo-500 hover:bg-indigo-400",
  cyan: "bg-cyan-500 hover:bg-cyan-400",
  amber: "bg-amber-500 hover:bg-amber-400",
  green: "bg-green-600 hover:bg-green-500",
  purple: "bg-purple-500 hover:bg-purple-400",
};

/** 浅色按钮配色（DFSecondaryButton/DFIconButton 用） */
const ACCENT_SOFT: Record<DFAccent, string> = {
  pink: "bg-pink-500/10 text-pink-400 hover:bg-pink-500/20 hover:text-pink-400",
  red: "bg-red-500/10 text-red-400 hover:bg-red-500/20 hover:text-red-400",
  teal: "bg-teal-500/10 text-teal-400 hover:bg-teal-500/20 hover:text-teal-400",
  indigo: "bg-indigo-500/10 text-indigo-400 hover:bg-indigo-500/20 hover:text-indigo-400",
  cyan: "bg-cyan-500/10 text-cyan-300 hover:bg-cyan-500/20 hover:text-cyan-300",
  amber: "bg-amber-500/20 text-amber-400 hover:bg-amber-500/30 hover:text-amber-400",
  green: "bg-green-500/20 text-green-400 hover:bg-green-500/30 hover:text-green-400",
  purple: "bg-purple-500/10 text-purple-300 hover:bg-purple-500/20 hover:text-purple-300",
};

/** df-ui 按钮通用 props：可选强调色（默认 indigo 与既有行为完全一致） */
type DFButtonProps = ButtonHTMLAttributes<HTMLButtonElement> & { accent?: DFAccent };

/** 页面容器：全高 + 居中限宽 */
export function DFPageShell({ children }: { children: ReactNode }) {
  return (
    <div className="min-h-[calc(100dvh-3.5rem)] p-6">
      <div className="mx-auto max-w-7xl space-y-6">{children}</div>
    </div>
  );
}

/** 页面标题栏：强调色图标 + 标题 + 描述 + 右侧操作区 */
export function DFPageHeader({
  icon: Icon,
  accent,
  title,
  description,
  actions,
}: {
  icon: LucideIcon;
  accent: DFAccent;
  title: string;
  description?: string;
  actions?: ReactNode;
}) {
  return (
    <div className="flex flex-col gap-4 sm:flex-row sm:items-center sm:justify-between">
      <div className="flex items-center gap-3">
        <div className={cn("rounded-lg border p-2", ACCENT_BADGE[accent])}>
          <Icon size={22} aria-hidden="true" />
        </div>
        <div>
          <h2 className="text-lg font-semibold text-foreground">{title}</h2>
          {description && <p className="mt-0.5 text-sm text-muted">{description}</p>}
        </div>
      </div>
      {actions && <div className="flex flex-wrap items-center gap-2">{actions}</div>}
    </div>
  );
}

/** 卡片容器 */
export function DFCard({ className, ...props }: HTMLAttributes<HTMLDivElement>) {
  return (
    <div
      className={cn("rounded-xl border border-border bg-surface", className)}
      {...props}
    />
  );
}

/** 统计卡片 */
export function DFStatCard({ label, value, accent }: { label: string; value: ReactNode; accent?: DFAccent }) {
  return <StatCard label={label} value={value} accent={accent ? ACCENT_TEXT[accent] : "text-foreground"} />;
}

/** 加载态 */
export function DFLoading({ text = "正在加载数据..." }: { text?: string }) {
  return (
    <div className="flex items-center justify-center py-20" role="status" aria-live="polite">
      <Loader2 className="mr-2 h-5 w-5 animate-spin text-muted motion-reduce:animate-none" aria-hidden="true" />
      <span className="text-sm text-muted">{text}</span>
    </div>
  );
}

/** 空态：品牌 logo + 浮动动画 */
export function DFEmpty({
  title,
  description,
  action,
}: {
  title: string;
  description?: string;
  action?: ReactNode;
}) {
  return (
    <div className="flex flex-col items-center justify-center rounded-xl border border-border bg-surface px-6 py-16 text-center">
      <img
        src={DF_BRAND_MARK_DARK}
        alt=""
        className="mb-4 h-16 w-16 animate-float motion-reduce:animate-none"
        aria-hidden="true"
      />
      <h3 className="text-base font-semibold text-foreground">{title}</h3>
      {description && <p className="mt-1 max-w-md text-sm text-muted">{description}</p>}
      {action && <div className="mt-4">{action}</div>}
    </div>
  );
}

/** 右下角错误提示条（6 秒自动消失） */
export function DFErrorToast({ message, onClose }: { message: string | null; onClose: () => void }) {
  useEffect(() => {
    if (!message) return;
    const timer = setTimeout(onClose, 6000);
    return () => clearTimeout(timer);
  }, [message, onClose]);

  if (!message) return null;
  return (
    <div
      className="fixed bottom-4 right-4 z-50 flex max-w-sm items-start gap-2 rounded-lg border border-red-500/30 bg-red-500/10 px-4 py-3 shadow-lg backdrop-blur-sm"
      role="alert"
      aria-live="assertive"
    >
      <AlertCircle size={16} className="mt-0.5 shrink-0 text-red-400" aria-hidden="true" />
      <span className="flex-1 text-sm text-red-300">{message}</span>
      <button
        type="button"
        onClick={onClose}
        aria-label="关闭错误提示"
        className="shrink-0 cursor-pointer rounded p-0.5 text-red-400/70 transition-colors hover:text-red-300"
      >
        <X size={14} aria-hidden="true" />
      </button>
    </div>
  );
}

/** 主按钮（accent 默认 indigo，配色与原行为一致） */
export function DFPrimaryButton({ className, type = "button", accent, ...props }: DFButtonProps) {
  return (
    <button
      type={type}
      className={cn(
        "inline-flex min-h-[32px] cursor-pointer items-center justify-center gap-1.5 rounded-lg px-4 py-1.5 text-xs font-medium text-white transition-colors",
        "disabled:cursor-not-allowed disabled:opacity-50",
        accent ? ACCENT_SOLID[accent] : "bg-indigo-500 hover:bg-indigo-400",
        className,
      )}
      {...props}
    />
  );
}

/** 次按钮（accent 默认次级中性色，配色与原行为一致） */
export function DFSecondaryButton({ className, type = "button", accent, ...props }: DFButtonProps) {
  return (
    <button
      type={type}
      className={cn(
        "inline-flex min-h-[32px] cursor-pointer items-center justify-center gap-1.5 rounded-lg px-4 py-1.5 text-xs font-medium transition-colors",
        "disabled:cursor-not-allowed disabled:opacity-50",
        accent ? ACCENT_SOFT[accent] : "bg-secondary text-muted hover:bg-surface-hover hover:text-foreground",
        className,
      )}
      {...props}
    />
  );
}

/** 危险按钮（accent 默认 red，配色与原行为一致） */
export function DFDangerButton({ className, type = "button", accent, ...props }: DFButtonProps) {
  return (
    <button
      type={type}
      className={cn(
        "inline-flex min-h-[32px] cursor-pointer items-center justify-center gap-1.5 rounded-lg px-4 py-1.5 text-xs font-medium text-white transition-colors",
        "disabled:cursor-not-allowed disabled:opacity-50",
        accent ? ACCENT_SOLID[accent] : "bg-red-500 hover:bg-red-400",
        className,
      )}
      {...props}
    />
  );
}

/** 图标按钮：满足 44px 最小触达尺寸（accent 默认中性，配色与原行为一致） */
export function DFIconButton({ className, type = "button", accent, ...props }: DFButtonProps) {
  return (
    <button
      type={type}
      className={cn(
        "inline-flex min-h-[44px] min-w-[44px] cursor-pointer items-center justify-center rounded-lg transition-colors",
        "disabled:cursor-not-allowed disabled:opacity-50",
        accent ? ACCENT_SOFT[accent] : "text-muted hover:bg-surface-hover hover:text-foreground",
        className,
      )}
      {...props}
    />
  );
}

/** 搜索输入框 */
export function DFSearchInput({ className, ...props }: InputHTMLAttributes<HTMLInputElement>) {
  return (
    <div className={cn("relative", className)}>
      <Search
        size={14}
        className="pointer-events-none absolute left-3 top-1/2 -translate-y-1/2 text-muted"
        aria-hidden="true"
      />
      <input
        className="h-9 w-full rounded-lg border border-border-strong/60 bg-surface pl-9 pr-3 text-sm text-foreground placeholder:text-muted focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-indigo-500/40"
        {...props}
      />
    </div>
  );
}

/** 深色下拉选择框 */
export function DFSelect({ className, children, ...props }: SelectHTMLAttributes<HTMLSelectElement>) {
  return (
    <div className={cn("relative", className)}>
      <select
        className="min-h-[44px] w-full cursor-pointer appearance-none rounded-lg border border-border-strong bg-surface-elevated py-2 pl-3 pr-9 text-sm text-foreground transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-indigo-500/40"
        {...props}
      >
        {children}
      </select>
      <ChevronDown
        size={14}
        className="pointer-events-none absolute right-3 top-1/2 -translate-y-1/2 text-muted"
        aria-hidden="true"
      />
    </div>
  );
}

/** 表单字段：标签 + 必填红星 + 错误/提示文本 */
export function DFFormField({
  label,
  required,
  error,
  hint,
  htmlFor,
  children,
}: {
  label: string;
  required?: boolean;
  error?: string;
  hint?: string;
  htmlFor?: string;
  children: ReactNode;
}) {
  return (
    <div className="space-y-1.5">
      <label htmlFor={htmlFor} className="block text-xs font-medium text-foreground">
        {label}
        {required && (
          <span className="ml-0.5 text-red-400" aria-hidden="true">
            *
          </span>
        )}
        {required && <span className="sr-only">（必填）</span>}
      </label>
      {children}
      {error ? (
        <p className="text-xs text-red-400" role="alert">
          {error}
        </p>
      ) : (
        hint && <p className="text-xs text-muted">{hint}</p>
      )}
    </div>
  );
}

/** 深色输入框 */
export function DFInput({ className, ...props }: InputHTMLAttributes<HTMLInputElement>) {
  return (
    <input
      className={cn(
        "h-9 w-full rounded-lg border border-border-strong bg-surface px-3 text-sm text-foreground",
        "placeholder:text-muted focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-indigo-500/40",
        className,
      )}
      {...props}
    />
  );
}

/** 深色多行输入框 */
export function DFTextarea({ className, ...props }: TextareaHTMLAttributes<HTMLTextAreaElement>) {
  return (
    <textarea
      className={cn(
        "min-h-[80px] w-full rounded-lg border border-border-strong bg-surface px-3 py-2 text-sm text-foreground",
        "placeholder:text-muted focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-indigo-500/40",
        className,
      )}
      {...props}
    />
  );
}

/** 小型标签 */
export function DFTag({ className, children }: { className?: string; children: ReactNode }) {
  return (
    <span
      className={cn(
        "inline-flex items-center rounded-md border border-border-strong/50 bg-secondary px-1.5 py-0.5 text-xs text-foreground",
        className,
      )}
    >
      {children}
    </span>
  );
}

/** 弹窗：遮罩 + 卡片，Escape / 点击遮罩关闭 */
export function DFModal({
  title,
  onClose,
  children,
  footer,
  wide,
}: {
  title: string;
  onClose: () => void;
  children: ReactNode;
  footer?: ReactNode;
  wide?: boolean;
}) {
  useEffect(() => {
    const handler = (e: KeyboardEvent) => {
      if (e.key === "Escape") onClose();
    };
    document.addEventListener("keydown", handler);
    return () => document.removeEventListener("keydown", handler);
  }, [onClose]);

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 p-4"
      onClick={onClose}
      role="presentation"
    >
      <div
        className={cn(
          "w-full rounded-xl border border-border/60 bg-surface-elevated p-5 shadow-2xl",
          wide ? "max-w-2xl" : "max-w-lg",
        )}
        onClick={(e) => e.stopPropagation()}
        role="dialog"
        aria-modal="true"
        aria-label={title}
      >
        <div className="mb-4 flex items-center justify-between">
          <h3 className="text-base font-semibold text-foreground">{title}</h3>
          <button
            type="button"
            onClick={onClose}
            aria-label="关闭弹窗"
            className="cursor-pointer rounded-md p-1 text-muted transition-colors hover:bg-surface-hover hover:text-foreground"
          >
            <X size={16} aria-hidden="true" />
          </button>
        </div>
        <div className="max-h-[70vh] overflow-y-auto pr-1">{children}</div>
        {footer && <div className="mt-5 flex justify-end gap-2">{footer}</div>}
      </div>
    </div>
  );
}

/** 删除二次确认弹窗 */
export function DFConfirmDialog({
  title,
  message,
  confirmText = "确认删除",
  loading,
  onCancel,
  onConfirm,
}: {
  title: string;
  message: string;
  confirmText?: string;
  loading?: boolean;
  onCancel: () => void;
  onConfirm: () => void;
}) {
  return (
    <DFModal
      title={title}
      onClose={onCancel}
      footer={
        <>
          <DFSecondaryButton onClick={onCancel} disabled={loading}>
            取消
          </DFSecondaryButton>
          <DFDangerButton onClick={onConfirm} disabled={loading}>
            {loading && <Loader2 size={12} className="animate-spin motion-reduce:animate-none" aria-hidden="true" />}
            {loading ? "处理中..." : confirmText}
          </DFDangerButton>
        </>
      }
    >
      <p className="text-sm text-muted">{message}</p>
    </DFModal>
  );
}
