import { cn } from "@/lib/utils";

export interface StatCardProps {
  label: string;
  value: string | number;
  tone?: "default" | "warning" | "danger";
}

export function StatCard({ label, value, tone = "default" }: StatCardProps) {
  return (
    <div className="rounded-xl border border-border bg-surface-elevated p-4">
      <div className="text-xs text-muted">{label}</div>
      <div
        className={cn(
          "mt-1 text-2xl font-bold",
          tone === "default" && "text-primary",
          tone === "warning" && "text-warning",
          tone === "danger" && "text-danger"
        )}
      >
        {value}
      </div>
    </div>
  );
}
