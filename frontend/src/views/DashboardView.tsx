import { useEffect, useState } from "react";
import { PenLine, BookOpen, Users, Route, AlertTriangle, AlertCircle, CheckCircle2 } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Textarea } from "@/components/ui/textarea";
import { Badge } from "@/components/ui/badge";
import { api } from "@/api";
import { useToast } from "@/hooks/useToast";
import { cn } from "@/lib/utils";
import type { Project, GenreContext } from "@/types";

interface DashboardViewProps {
  project: Project | null;
  totalWords: number;
  chapterCount: number;
  characterCount: number;
  foreshadowCount: number;
  outlineCount: number;
  projectForm: Partial<Project>;
  setProjectForm: (form: Partial<Project>) => void;
  onSave: (form: Partial<Project>) => void | Promise<void>;
  genreContext: GenreContext | null;
  onRefreshGenreContext: () => void;
}

export function DashboardView({
  project,
  totalWords,
  chapterCount,
  characterCount,
  foreshadowCount,
  outlineCount,
  projectForm,
  setProjectForm,
  onSave,
  genreContext,
  onRefreshGenreContext,
}: DashboardViewProps) {
  const [dashboard, setDashboard] = useState<any>(null);
  const [dashboardLoading, setDashboardLoading] = useState(false);
  const { showError } = useToast();

  const loadDashboard = async () => {
    if (!project) return;
    setDashboardLoading(true);
    try {
      const r = await api.getConsistencyDashboard(project.id);
      setDashboard(r);
    } catch (e: any) {
      showError("一致性看板加载失败：" + e.message);
    } finally {
      setDashboardLoading(false);
    }
  };

  useEffect(() => {
    loadDashboard();
  }, [project?.id]);

  if (!project) return null;
  return (
    <div className="flex-1 overflow-y-auto space-y-3">
      <div className="grid grid-cols-2 sm:grid-cols-4 gap-3">
        <StatCard label="总字数" value={totalWords.toLocaleString()} icon={<PenLine className="h-4 w-4" />} color="primary" />
        <StatCard label="章节数" value={chapterCount} icon={<BookOpen className="h-4 w-4" />} color="primary" />
        <StatCard label="角色数" value={characterCount} icon={<Users className="h-4 w-4" />} color="primary" />
        <StatCard label="伏笔 / 大纲" value={`${foreshadowCount}/${outlineCount}`} icon={<Route className="h-4 w-4" />} color="warning" />
      </div>
      <Card>
        <CardHeader><CardTitle>项目概览</CardTitle></CardHeader>
        <CardContent className="space-y-3">
          <Input placeholder="标题" value={projectForm.title || ""} onChange={(e) => setProjectForm({ ...projectForm, title: e.target.value })} />
          <Input placeholder="类型" value={projectForm.genre || ""} onChange={(e) => setProjectForm({ ...projectForm, genre: e.target.value })} />
          <Textarea placeholder="简介" value={projectForm.summary || ""} onChange={(e) => setProjectForm({ ...projectForm, summary: e.target.value })} />
          <Textarea placeholder="文风" value={projectForm.style || ""} onChange={(e) => setProjectForm({ ...projectForm, style: e.target.value })} />
          <Button onClick={() => onSave(projectForm)}>保存项目信息</Button>
        </CardContent>
      </Card>
      <Card>
        <CardHeader className="flex items-center justify-between">
          <CardTitle>题材上下文</CardTitle>
          <Button variant="outline" size="sm" onClick={onRefreshGenreContext}>刷新</Button>
        </CardHeader>
        <CardContent className="space-y-3">
          {!genreContext ? (
            <div className="text-sm text-muted">点击刷新查看当前项目识别的题材模板与参考资料。</div>
          ) : (
            <>
              <div className="flex items-center gap-2 text-sm">
                <span className="text-muted">识别类型：</span>
                <Badge>{genreContext.canonical_genre || "通用"}</Badge>
                <span className="text-xs text-muted">（原始：{genreContext.genre}）</span>
              </div>
              {genreContext.template_text && (
                <div>
                  <div className="text-xs font-medium text-muted mb-1">题材模板约束</div>
                  <pre className="whitespace-pre-wrap text-sm bg-surface rounded-lg p-3 overflow-auto max-h-96">{genreContext.template_text}</pre>
                </div>
              )}
              {genreContext.references.length > 0 && (
                <div>
                  <div className="text-xs font-medium text-muted mb-1">参考资料</div>
                  <ul className="space-y-2">
                    {genreContext.references.map((ref, i) => (
                      <li key={i} className="text-sm">
                        <span className="font-medium">{ref.关键词}</span>
                        <span className="text-muted">：{ref.核心摘要}</span>
                        {ref.详细展开 && <div className="text-xs text-muted mt-0.5">{ref.详细展开}</div>}
                      </li>
                    ))}
                  </ul>
                </div>
              )}
            </>
          )}
        </CardContent>
      </Card>

      <Card>
        <CardHeader className="flex items-center justify-between">
          <CardTitle>一致性看板</CardTitle>
          <Button variant="outline" size="sm" onClick={loadDashboard} disabled={dashboardLoading}>
            {dashboardLoading ? "刷新中…" : "刷新"}
          </Button>
        </CardHeader>
        <CardContent className="space-y-4">
          {!dashboard ? (
            <div className="text-sm text-muted">加载中…</div>
          ) : (
            <>
              <div className="grid grid-cols-5 gap-2 text-center">
                <MiniStat label="角色" value={dashboard.stats.characters} />
                <MiniStat label="世界设定" value={dashboard.stats.world_settings} />
                <MiniStat label="大纲" value={dashboard.stats.outlines} />
                <MiniStat label="未回收伏笔" value={dashboard.stats.unresolved_foreshadows} warning={dashboard.stats.unresolved_foreshadows > 0} />
                <MiniStat label="冲突" value={dashboard.stats.conflicts} danger={dashboard.stats.conflicts > 0} />
              </div>

              {dashboard.conflicts.length > 0 && (
                <div className="rounded-xl border border-danger/30 bg-danger/5 p-3 space-y-2">
                  <div className="text-sm font-semibold text-danger flex items-center gap-1.5">
                    <AlertTriangle className="h-4 w-4" />
                    检测到 {dashboard.conflicts.length} 条冲突
                  </div>
                  {dashboard.conflicts.map((c: any, i: number) => (
                    <div key={i} className="text-sm flex items-start gap-2">
                      <Badge
                        variant={
                          c.severity === "high" ? "danger" : c.severity === "medium" ? "warning" : "default"
                        }
                      >
                        {c.severity}
                      </Badge>
                      <span className="text-foreground/90 leading-relaxed">{c.message}</span>
                    </div>
                  ))}
                </div>
              )}

              {dashboard.overdue_foreshadows.length > 0 && (
                <div>
                  <div className="text-xs font-medium text-muted mb-1">超期未回收伏笔</div>
                  <div className="space-y-1">
                    {dashboard.overdue_foreshadows.map((f: any) => (
                      <div key={f.foreshadow_id} className="text-sm flex items-center justify-between">
                        <span>{f.foreshadow_id}：{f.description || "无描述"}</span>
                        <span className="text-xs text-muted">计划 {f.planned_resolve_chapter} 章回收</span>
                      </div>
                    ))}
                  </div>
                </div>
              )}

              {dashboard.recent_state_changes.length > 0 && (
                <div>
                  <div className="text-xs font-medium text-muted mb-1">近期状态变更</div>
                  <div className="space-y-1 max-h-40 overflow-y-auto">
                    {dashboard.recent_state_changes.slice(-10).reverse().map((s: any) => (
                      <div key={s.id} className="text-sm">
                        <span className="text-muted">第{s.chapter}章</span>
                        <span className="ml-2">{s.entity_type} {s.entity_id} 的 {s.field}</span>
                        <span className="ml-1 text-muted">{s.old_value || "-"} → {s.new_value || "-"}</span>
                      </div>
                    ))}
                  </div>
                </div>
              )}

              {dashboard.recent_events.length > 0 && (
                <div>
                  <div className="text-xs font-medium text-muted mb-1">近期事件</div>
                  <div className="space-y-1 max-h-40 overflow-y-auto">
                    {dashboard.recent_events.slice(-10).reverse().map((e: any) => (
                      <div key={e.id} className="text-sm">
                        <span className="text-muted">第{e.chapter}章</span>
                        <Badge className="ml-2 text-xs">{e.event_type}</Badge>
                        <span className="ml-2">{e.entity_id || e.payload?.description || "事件"}</span>
                      </div>
                    ))}
                  </div>
                </div>
              )}
            </>
          )}
        </CardContent>
      </Card>
    </div>
  );
}

function MiniStat({ label, value, warning, danger }: { label: string; value: number; warning?: boolean; danger?: boolean }) {
  const Icon = danger ? AlertTriangle : warning ? AlertCircle : CheckCircle2;
  return (
    <div className={cn(
      "rounded-xl border p-3 transition-all",
      danger ? "border-danger/30 bg-danger/5" : warning ? "border-warning/30 bg-warning/5" : "border-border bg-surface"
    )}>
      <div className={cn("text-2xl font-bold", danger ? "text-danger" : warning ? "text-warning" : "text-foreground")}>{value}</div>
      <div className="text-[10px] font-semibold text-muted uppercase tracking-wider flex items-center gap-1 mt-0.5">
        <Icon className="h-3 w-3" />
        {label}
      </div>
    </div>
  );
}

function StatCard({
  label,
  value,
  icon,
  color = "primary",
}: {
  label: string;
  value: string | number;
  icon?: React.ReactNode;
  color?: "primary" | "warning" | "danger" | "success";
}) {
  const colorClasses = {
    primary: "bg-primary-muted text-primary",
    warning: "bg-warning/10 text-warning",
    danger: "bg-danger/10 text-danger",
    success: "bg-success/10 text-success",
  };
  return (
    <Card className="flex items-center gap-3 p-4">
      <div className={cn("h-10 w-10 rounded-xl flex items-center justify-center shrink-0", colorClasses[color])}>
        {icon}
      </div>
      <div className="min-w-0">
        <div className="text-xl font-bold text-foreground truncate">{value}</div>
        <div className="text-xs font-medium text-muted">{label}</div>
      </div>
    </Card>
  );
}
