/** 全局设置 · 压缩监控页：统计卡片 + 压缩历史日志表格 */
import { useCallback, useEffect, useState, type ReactNode } from "react";
import { Archive, Loader2 } from "lucide-react";
import { Card } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { EmptyState } from "@/components/ui/empty-state";

interface CompressionStats {
  total_compressions: number;
  avg_ratio: number;
  total_tokens_saved: number;
  strategies?: { key: string; name: string; description: string }[];
}

interface CompressionLog {
  id: string;
  time: string;
  before_tokens: number;
  after_tokens: number;
  ratio: number;
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

export default function CompressionPage() {
  const [stats, setStats] = useState<CompressionStats | null>(null);
  const [logs, setLogs] = useState<CompressionLog[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const [statsData, logsData] = await Promise.all([
        fetchJson<CompressionStats>("/api/compression/stats").catch(() => null),
        fetchJson<{ logs: CompressionLog[] }>("/api/compression/logs").catch(() => ({ logs: [] })),
      ]);
      setStats(statsData);
      setLogs(logsData.logs || []);
    } catch (e) {
      setError(e instanceof Error ? e.message : "加载失败");
      setStats(null);
      setLogs([]);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  const header = (
    <div className="flex items-center gap-3">
      <div className="rounded-lg border border-border bg-primary-muted p-2 text-primary">
        <Archive className="h-5 w-5" />
      </div>
      <div>
        <h2 className="text-lg font-semibold">压缩监控</h2>
        <p className="text-sm text-muted">查看上下文压缩统计与历史日志</p>
      </div>
    </div>
  );

  const statCards = (
    <div className="grid grid-cols-3 gap-4">
      <Card className="p-4">
        <div className="text-xs text-muted">总压缩次数</div>
        <div className="mt-1 text-2xl font-bold tabular-nums">{stats?.total_compressions ?? 0}</div>
      </Card>
      <Card className="p-4">
        <div className="text-xs text-muted">平均压缩率</div>
        <div className="mt-1 text-2xl font-bold tabular-nums text-success">
          {stats ? `${Math.round(stats.avg_ratio * 100)}%` : "-"}
        </div>
      </Card>
      <Card className="p-4">
        <div className="text-xs text-muted">节省 Token 数</div>
        <div className="mt-1 text-2xl font-bold tabular-nums text-primary">{stats?.total_tokens_saved ?? 0}</div>
      </Card>
    </div>
  );

  let body: ReactNode;
  if (loading) {
    body = (
      <div className="flex items-center justify-center py-20">
        <Loader2 className="mr-2 h-5 w-5 animate-spin text-muted" />
        <span className="text-sm text-muted">正在加载压缩数据...</span>
      </div>
    );
  } else if (error || (!stats && logs.length === 0)) {
    body = (
      <EmptyState
        icon={<Archive className="h-10 w-10 text-muted" />}
        title={error ? "后端压缩监控尚未接入" : "暂无压缩记录"}
        description={error ?? "上下文压缩功能接入后将在此展示统计与日志"}
      />
    );
  } else {
    body = (
      <Card className="overflow-hidden p-0">
        <div className="border-b border-border bg-surface px-4 py-2.5 text-sm font-medium">压缩历史日志</div>
        {logs.length === 0 ? (
          <p className="py-10 text-center text-sm text-muted">暂无压缩日志</p>
        ) : (
          <table className="w-full text-sm">
            <thead className="border-b border-border bg-surface">
              <tr>
                <th className="px-4 py-2.5 text-left text-xs font-medium text-muted">时间</th>
                <th className="px-4 py-2.5 text-right text-xs font-medium text-muted">压缩前</th>
                <th className="px-4 py-2.5 text-right text-xs font-medium text-muted">压缩后</th>
                <th className="px-4 py-2.5 text-right text-xs font-medium text-muted">压缩率</th>
              </tr>
            </thead>
            <tbody>
              {logs.map((l) => (
                <tr key={l.id} className="border-b border-border last:border-0">
                  <td className="px-4 py-2.5 text-muted">{l.time}</td>
                  <td className="px-4 py-2.5 text-right tabular-nums">{l.before_tokens}</td>
                  <td className="px-4 py-2.5 text-right tabular-nums">{l.after_tokens}</td>
                  <td className="px-4 py-2.5 text-right">
                    <Badge variant="success">{Math.round(l.ratio * 100)}%</Badge>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </Card>
    );
  }

  return (
    <div className="h-full overflow-y-auto">
      <div className="mx-auto max-w-6xl space-y-6 p-6">
        {header}
        {statCards}
        {body}
      </div>
    </div>
  );
}
