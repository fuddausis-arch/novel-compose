export function ProgressCard() {
  return (
    <div className="rounded-xl border border-border bg-surface-elevated p-4">
      <div className="text-sm font-semibold text-foreground">卷级进度</div>
      <div className="mt-1 text-xs text-muted">卷一：风起 · 0 / 30 章</div>
      <div className="mt-3 h-1.5 rounded-full bg-secondary">
        <div className="h-full w-0 rounded-full bg-primary" />
      </div>
    </div>
  );
}
