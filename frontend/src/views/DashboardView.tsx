import { useEffect, useState } from "react";
import { PenLine, BookOpen, Users, Route, AlertTriangle, AlertCircle, CheckCircle2, Loader2, XCircle } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Textarea } from "@/components/ui/textarea";
import { Badge } from "@/components/ui/badge";
import { api } from "@/api";
import { useToast } from "@/hooks/useToast";
import { useAppStore } from "@/store";
import { StatCard } from "@/components/ui/stat-card";
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
  refreshingGenre: boolean;
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
  refreshingGenre,
}: DashboardViewProps) {
  const [dashboard, setDashboard] = useState<any>(null);
  const [dashboardLoading, setDashboardLoading] = useState(false);
  const { showError } = useToast();

  const handleSave = () => {
    if (!projectForm.title?.trim()) {
      showError("标题不能为空");
      return;
    }
    onSave(projectForm);
  };

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
        <StatCard label="总字数" value={totalWords.toLocaleString()} icon={<PenLine className="h-4 w-4" />} tone="primary" />
        <StatCard label="章节数" value={chapterCount} icon={<BookOpen className="h-4 w-4" />} tone="primary" />
        <StatCard label="角色数" value={characterCount} icon={<Users className="h-4 w-4" />} tone="primary" />
        <StatCard label="伏笔 / 大纲" value={`${foreshadowCount}/${outlineCount}`} icon={<Route className="h-4 w-4" />} tone="warning" />
      </div>
      <Card>
        <CardHeader><CardTitle>项目概览</CardTitle></CardHeader>
        <CardContent className="space-y-3">
          <Input placeholder="标题" value={projectForm.title || ""} maxLength={500} onChange={(e) => setProjectForm({ ...projectForm, title: e.target.value })} />
          <Input placeholder="类型" value={projectForm.genre || ""} maxLength={200} onChange={(e) => setProjectForm({ ...projectForm, genre: e.target.value })} />
          <Textarea placeholder="简介" value={projectForm.summary || ""} maxLength={10000} onChange={(e) => setProjectForm({ ...projectForm, summary: e.target.value })} />
          <Textarea placeholder="文风" value={projectForm.style || ""} maxLength={2000} onChange={(e) => setProjectForm({ ...projectForm, style: e.target.value })} />
          <Button onClick={handleSave} disabled={!projectForm.title?.trim()}>保存项目信息</Button>
        </CardContent>
      </Card>
      <BatchGenerationCard projectId={project.id} />
      <Card>
        <CardHeader className="flex items-center justify-between">
          <CardTitle>题材上下文</CardTitle>
          <Button variant="outline" size="sm" onClick={onRefreshGenreContext} disabled={refreshingGenre}>
            {refreshingGenre ? "刷新中…" : "刷新"}
          </Button>
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

function BatchGenerationCard({ projectId }: { projectId: number }) {
  const store = useAppStore();
  const { showSuccess, showError } = useToast();
  const [startChapter, setStartChapter] = useState(1);
  const [endChapter, setEndChapter] = useState(10);

  const { batchGenerating, batchProgress, batchErrors } = store;
  const pct = batchProgress.total > 0
    ? Math.round(((batchProgress.completed + batchProgress.failed) / batchProgress.total) * 100)
    : 0;

  const handleStart = async () => {
    if (startChapter < 1 || endChapter < startChapter) {
      showError("请输入有效的章节范围（起始 ≥ 1，结束 ≥ 起始）");
      return;
    }
    showSuccess(`开始批量生成第 ${startChapter}-${endChapter} 章`);
    await store.batchGenerate(projectId, startChapter, endChapter);
  };

  const handleStop = () => {
    store.batchStop();
    showSuccess("已停止批量生成");
  };

  return (
    <Card>
      <CardHeader className="flex items-center justify-between">
        <CardTitle>批量生成</CardTitle>
        {batchGenerating && (
          <Badge variant="warning" className="flex items-center gap-1">
            <Loader2 className="h-3 w-3 animate-spin" />
            生成中
          </Badge>
        )}
      </CardHeader>
      <CardContent className="space-y-4">
        <div className="flex items-end gap-3">
          <div className="flex flex-col gap-1">
            <label className="text-xs text-muted">起始章节</label>
            <Input
              type="number"
              min={1}
              value={startChapter}
              onChange={(e) => setStartChapter(Number(e.target.value))}
              disabled={batchGenerating}
              className="w-28"
            />
          </div>
          <div className="flex flex-col gap-1">
            <label className="text-xs text-muted">结束章节</label>
            <Input
              type="number"
              min={1}
              value={endChapter}
              onChange={(e) => setEndChapter(Number(e.target.value))}
              disabled={batchGenerating}
              className="w-28"
            />
          </div>
          {batchGenerating ? (
            <Button variant="danger" onClick={handleStop}>
              停止
            </Button>
          ) : (
            <Button variant="primary" onClick={handleStart}>
              开始批量生成
            </Button>
          )}
        </div>

        {(batchGenerating || batchProgress.total > 0) && (
          <div className="space-y-2">
            <div className="flex items-center justify-between text-sm">
              <span className="text-muted">
                进度：{batchProgress.current}/{batchProgress.total}
              </span>
              <span className="text-muted">{pct}%</span>
            </div>
            <div className="h-2 rounded-full bg-surface overflow-hidden">
              <div
                className="h-full bg-primary transition-all duration-300"
                style={{ width: `${pct}%` }}
              />
            </div>
            <div className="flex gap-4 text-sm">
              <span className="flex items-center gap-1 text-success">
                <CheckCircle2 className="h-4 w-4" />
                成功 {batchProgress.completed}
              </span>
              <span className="flex items-center gap-1 text-danger">
                <XCircle className="h-4 w-4" />
                失败 {batchProgress.failed}
              </span>
            </div>
          </div>
        )}

        {batchErrors.length > 0 && (
          <div className="rounded-xl border border-danger/30 bg-danger/5 p-3 space-y-1 max-h-40 overflow-y-auto">
            <div className="text-sm font-semibold text-danger flex items-center gap-1.5">
              <AlertTriangle className="h-4 w-4" />
              失败章节（{batchErrors.length}）
            </div>
            {batchErrors.map((err, i) => (
              <div key={i} className="text-sm text-foreground/90">
                {err.chapter > 0 && <span className="text-muted">第{err.chapter}章：</span>}
                {err.error}
              </div>
            ))}
          </div>
        )}
      </CardContent>
    </Card>
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
