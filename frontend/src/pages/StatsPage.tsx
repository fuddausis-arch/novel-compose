import { useCallback, useState } from "react";
import { AppLayout } from "@/components/layout/AppLayout";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { useCurrentProject } from "@/hooks/useCurrentProject";
import { useAutoRefresh } from "@/hooks/useAutoRefresh";
import { useAppStore } from "@/store";
import { api } from "@/api";
import { useToast } from "@/hooks/useToast";

interface ConsistencyDashboard {
  stats: {
    total_chapters: number;
    total_words: number;
    total_characters: number;
    total_foreshadows: number;
    resolved_foreshadows: number;
    pending_foreshadows: number;
    overdue_foreshadows: number;
  };
  recent_state_changes: any[];
  unresolved_foreshadows: any[];
  overdue_foreshadows: any[];
  recent_events: any[];
  conflicts: any[];
}

export default function StatsPage() {
  const { project } = useCurrentProject();
  const store = useAppStore();
  const [dashboard, setDashboard] = useState<ConsistencyDashboard | null>(null);
  const [, setRefreshing] = useState(false);
  const { showError } = useToast();

  const load = useCallback(async () => {
    if (!project) return;
    setRefreshing(true);
    try {
      const d = await api.getConsistencyDashboard(project.id);
      setDashboard(d);
    } catch (e) {
      showError("一致性看板加载失败：" + (e instanceof Error ? e.message : String(e)));
    } finally {
      setRefreshing(false);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [project?.id]);

  // 页面挂载 / 窗口 focus / bible·chapters 数据版本变化时自动重新拉取
  useAutoRefresh(["bible", "chapters"], load, [load]);

  if (!project) return null;

  const stats = dashboard?.stats || {
    total_chapters: store.chapters.length,
    total_words: store.summaries.reduce((s, c) => s + (c.word_count || 0), 0),
    total_characters: store.characters.length,
    total_foreshadows: store.foreshadows.length,
    resolved_foreshadows: store.foreshadows.filter((f) => f.status === "resolved").length,
    pending_foreshadows: store.foreshadows.filter((f) => f.status === "pending" || f.status === "developing").length,
    overdue_foreshadows: store.foreshadows.filter((f) => f.status === "overdue").length,
  };

  const conflicts = dashboard?.conflicts || [];
  const overdue = dashboard?.overdue_foreshadows || [];

  return (
    <AppLayout>
      <div className="flex h-full flex-col overflow-hidden bg-background">
        <header className="flex items-center justify-between border-b border-border px-6 py-4">
          <h1 className="text-xl font-bold text-foreground">统计与一致性</h1>
          <Button
            variant="outline"
            onClick={() => void load()}
          >
            刷新
          </Button>
        </header>

        <div className="flex-1 overflow-y-auto p-6 space-y-6">
          {/* 核心指标 */}
          <div className="grid grid-cols-2 gap-4 sm:grid-cols-4">
            <div className="rounded-xl border border-border bg-surface-elevated p-4">
              <div className="text-xs text-muted">总字数</div>
              <div className="mt-1 text-2xl font-bold text-foreground">{stats.total_words}</div>
            </div>
            <div className="rounded-xl border border-border bg-surface-elevated p-4">
              <div className="text-xs text-muted">章节数</div>
              <div className="mt-1 text-2xl font-bold text-foreground">{stats.total_chapters}</div>
            </div>
            <div className="rounded-xl border border-border bg-surface-elevated p-4">
              <div className="text-xs text-muted">角色数</div>
              <div className="mt-1 text-2xl font-bold text-foreground">{stats.total_characters}</div>
            </div>
            <div className="rounded-xl border border-border bg-surface-elevated p-4">
              <div className="text-xs text-muted">伏笔总数</div>
              <div className="mt-1 text-2xl font-bold text-foreground">{stats.total_foreshadows}</div>
            </div>
          </div>

          {/* 伏笔状态 */}
          <div className="rounded-xl border border-border bg-surface-elevated p-4">
            <div className="text-sm font-semibold text-foreground">伏笔状态分布</div>
            <div className="mt-4 grid grid-cols-3 gap-4">
              <div>
                <div className="text-xs text-muted">已回收</div>
                <div className="mt-1 text-2xl font-bold text-success">{stats.resolved_foreshadows}</div>
              </div>
              <div>
                <div className="text-xs text-muted">待回收</div>
                <div className="mt-1 text-2xl font-bold text-warning">{stats.pending_foreshadows}</div>
              </div>
              <div>
                <div className="text-xs text-muted">疑似遗漏</div>
                <div className="mt-1 text-2xl font-bold text-danger">{stats.overdue_foreshadows}</div>
              </div>
            </div>
          </div>

          {/* 一致性冲突 */}
          <div className="rounded-xl border border-border bg-surface-elevated p-4">
            <div className="flex items-center justify-between">
              <div className="text-sm font-semibold text-foreground">一致性冲突报告</div>
              <Badge variant={conflicts.length > 0 ? "danger" : "success"}>
                {conflicts.length > 0 ? `${conflicts.length} 个冲突` : "无冲突"}
              </Badge>
            </div>
            <div className="mt-4 space-y-2">
              {conflicts.length === 0 ? (
                <div className="text-sm text-muted">暂无冲突，数据一致性良好</div>
              ) : (
                conflicts.map((c, i) => (
                  <div key={i} className="flex items-start gap-2 rounded-lg border border-border p-3">
                    <Badge variant={c.severity === "critical" ? "danger" : "warning"}>
                      {c.type || "冲突"}
                    </Badge>
                    <span className="text-sm text-foreground">{c.message}</span>
                  </div>
                ))
              )}
            </div>
          </div>

          {/* 超期伏笔 */}
          {overdue.length > 0 && (
            <div className="rounded-xl border border-border bg-surface-elevated p-4">
              <div className="text-sm font-semibold text-foreground">超期伏笔</div>
              <div className="mt-4 space-y-2">
                {overdue.map((f, i) => (
                  <div key={i} className="flex items-center justify-between rounded-lg border border-border p-3">
                    <div>
                      <div className="text-sm font-medium text-foreground">
                        {f.foreshadow_id || `#${i + 1}`}
                      </div>
                      <div className="text-xs text-muted">{f.description}</div>
                    </div>
                    <Badge variant="danger">超期</Badge>
                  </div>
                ))}
              </div>
            </div>
          )}

          {/* 最近事件 */}
          <div className="rounded-xl border border-border bg-surface-elevated p-4">
            <div className="text-sm font-semibold text-foreground">最近事件</div>
            <div className="mt-4 space-y-2">
              {(dashboard?.recent_events || []).length === 0 ? (
                <div className="text-sm text-muted">暂无事件</div>
              ) : (
                (dashboard?.recent_events || []).slice(0, 20).map((e, i) => (
                  <div key={i} className="flex items-center gap-2 text-sm text-foreground">
                    <Badge variant="default">{e.chapter ? `第${e.chapter}章` : "—"}</Badge>
                    <span>{e.description || e.event_type || JSON.stringify(e)}</span>
                  </div>
                ))
              )}
            </div>
          </div>
        </div>
      </div>
    </AppLayout>
  );
}
