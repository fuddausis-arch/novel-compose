/** 全局设置 · 定时任务页：任务列表表格 + 创建任务 */
import { useCallback, useEffect, useState, type ReactNode } from "react";
import { Clock, Loader2, Plus } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Input } from "@/components/ui/input";
import { Select } from "@/components/ui/select";
import { EmptyState } from "@/components/ui/empty-state";
import { Dialog, DialogContent, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { useToast } from "@/hooks/useToast";

interface CronTask {
  id: string;
  name: string;
  cron: string;
  status: string;
}

/** 后端 GET /api/cron 返回的原始 job 结构 */
interface CronJobApi {
  id: string;
  name: string;
  schedule: string;
  enabled: boolean;
}

async function fetchJson<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(path, { headers: { "Content-Type": "application/json" }, ...init });
  if (!res.ok) {
    const text = await res.text().catch(() => "");
    let msg = `请求失败（HTTP ${res.status}）`;
    try {
      const j = JSON.parse(text);
      if (j.detail) msg = String(j.detail);
      else if (j.message) msg = String(j.message);
    } catch {
      /* 非 JSON，忽略 */
    }
    throw new Error(msg);
  }
  if (res.status === 204) return undefined as T;
  return (await res.json()) as T;
}

function statusVariant(status: string): "success" | "warning" | "default" {
  const s = status.toLowerCase();
  if (s === "running" || s === "active" || s === "enabled") return "success";
  if (s === "paused" || s === "pending") return "warning";
  return "default";
}

export default function CronPage() {
  const { showError, showSuccess } = useToast();
  const [tasks, setTasks] = useState<CronTask[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [creating, setCreating] = useState(false);
  const [form, setForm] = useState({ name: "", cron: "0 * * * *", status: "active" });
  const [saving, setSaving] = useState(false);

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const data = await fetchJson<{ jobs: CronJobApi[] }>("/api/cron");
      setTasks(
        (data.jobs || []).map((j) => ({
          id: j.id,
          name: j.name,
          cron: j.schedule,
          status: j.enabled ? "active" : "paused",
        })),
      );
    } catch (e) {
      setError(e instanceof Error ? e.message : "加载失败");
      setTasks([]);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  const handleCreate = async () => {
    if (!form.name.trim()) {
      showError("请输入任务名称");
      return;
    }
    if (!form.cron.trim()) {
      showError("请输入 cron 表达式");
      return;
    }
    setSaving(true);
    try {
      await fetchJson("/api/cron", {
        method: "POST",
        body: JSON.stringify({
          id: crypto.randomUUID(),
          name: form.name.trim(),
          schedule: form.cron.trim(),
          workflow_type: "batch_generate",
          enabled: form.status === "active",
        }),
      });
      showSuccess("任务已创建");
      setCreating(false);
      setForm({ name: "", cron: "0 * * * *", status: "active" });
      await load();
    } catch (e) {
      showError(e instanceof Error ? e.message : "创建失败");
    } finally {
      setSaving(false);
    }
  };

  const header = (
    <div className="flex flex-col gap-4 sm:flex-row sm:items-center sm:justify-between">
      <div className="flex items-center gap-3">
        <div className="rounded-lg border border-border bg-primary-muted p-2 text-primary">
          <Clock className="h-5 w-5" />
        </div>
        <div>
          <h2 className="text-lg font-semibold">定时任务</h2>
          <p className="text-sm text-muted">调度 Agent 在指定时间自动执行任务</p>
        </div>
      </div>
      <Button variant="primary" size="sm" onClick={() => setCreating(true)}>
        <Plus className="h-4 w-4" />
        创建任务
      </Button>
    </div>
  );

  let body: ReactNode;
  if (loading) {
    body = (
      <div className="flex items-center justify-center py-20">
        <Loader2 className="mr-2 h-5 w-5 animate-spin text-muted" />
        <span className="text-sm text-muted">正在加载任务...</span>
      </div>
    );
  } else if (error || tasks.length === 0) {
    body = (
      <EmptyState
        icon={<Clock className="h-10 w-10 text-muted" />}
        title={error ? "后端定时任务尚未接入" : "暂无定时任务"}
        description={error ?? "点击「创建任务」添加第一个调度任务"}
      />
    );
  } else {
    body = (
      <Card className="overflow-hidden p-0">
        <table className="w-full text-sm">
          <thead className="border-b border-border bg-surface">
            <tr>
              <th className="px-4 py-2.5 text-left text-xs font-medium text-muted">名称</th>
              <th className="px-4 py-2.5 text-left text-xs font-medium text-muted">Cron 表达式</th>
              <th className="px-4 py-2.5 text-left text-xs font-medium text-muted">状态</th>
              <th className="px-4 py-2.5 text-right text-xs font-medium text-muted">操作</th>
            </tr>
          </thead>
          <tbody>
            {tasks.map((t) => (
              <tr key={t.id} className="border-b border-border last:border-0">
                <td className="px-4 py-2.5 font-medium">{t.name}</td>
                <td className="px-4 py-2.5 font-mono text-xs text-muted">{t.cron}</td>
                <td className="px-4 py-2.5">
                  <Badge variant={statusVariant(t.status)}>{t.status}</Badge>
                </td>
                <td className="px-4 py-2.5 text-right">
                  <Button
                    variant="ghost"
                    size="sm"
                    onClick={async () => {
                      try {
                        await fetchJson(`/api/cron/${encodeURIComponent(t.id)}`, { method: "DELETE" });
                        showSuccess("任务已删除");
                        setTasks((prev) => prev.filter((x) => x.id !== t.id));
                      } catch (e) {
                        showError(e instanceof Error ? e.message : "删除失败");
                      }
                    }}
                    className="text-danger hover:text-danger"
                  >
                    删除
                  </Button>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </Card>
    );
  }

  return (
    <div className="h-full overflow-y-auto">
      <div className="mx-auto max-w-6xl space-y-6 p-6">
        {header}
        {body}
      </div>

      {/* 创建弹窗 */}
      <Dialog open={creating} onOpenChange={(o) => !o && setCreating(false)}>
        <DialogContent className="max-w-md">
          <DialogHeader>
            <DialogTitle>创建定时任务</DialogTitle>
          </DialogHeader>
          <div className="space-y-3">
            <label className="block">
              <span className="mb-1 block text-xs font-medium">任务名称</span>
              <Input
                value={form.name}
                onChange={(e) => setForm((f) => ({ ...f, name: e.target.value }))}
                placeholder="如 每日章节审校"
              />
            </label>
            <label className="block">
              <span className="mb-1 block text-xs font-medium">Cron 表达式</span>
              <Input
                value={form.cron}
                onChange={(e) => setForm((f) => ({ ...f, cron: e.target.value }))}
                placeholder="0 * * * *"
                className="font-mono text-xs"
              />
            </label>
            <label className="block">
              <span className="mb-1 block text-xs font-medium">状态</span>
              <Select
                value={form.status}
                onChange={(e) => setForm((f) => ({ ...f, status: e.target.value }))}
              >
                <option value="active">active</option>
                <option value="paused">paused</option>
              </Select>
            </label>
          </div>
          <div className="mt-5 flex justify-end gap-2">
            <Button variant="ghost" size="sm" onClick={() => setCreating(false)} disabled={saving}>
              取消
            </Button>
            <Button variant="primary" size="sm" onClick={() => void handleCreate()} disabled={saving}>
              {saving ? "创建中..." : "创建"}
            </Button>
          </div>
        </DialogContent>
      </Dialog>
    </div>
  );
}
