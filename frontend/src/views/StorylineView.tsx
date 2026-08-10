// 叙事线系统：左栏线看板（筛选/搜索/增删改）+ 右栏选中线网络（节点链/交汇）+ 底部预警栏。
// 布局见计划书 3.1；组件模式与 views/AiStyleView.tsx 一致；标签/状态枚举来自 meta（不硬编码）。

import { useCallback, useEffect, useRef, useState } from "react";
import {
  GitMerge, Loader2, Plus, ScanSearch, Search, Sparkles, Square, Trash2, X,
} from "lucide-react";
import { api } from "@/api";
import type {
  ScanAlert, Storyline, StorylineDetail, StorylineMeta, StorylineNode, StorylineRelation,
} from "@/types";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Dialog, DialogContent, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { Progress } from "@/components/ui/progress";
import { Select } from "@/components/ui/select";
import { Textarea } from "@/components/ui/textarea";
import { useCurrentProject } from "@/hooks/useCurrentProject";
import { useToast } from "@/hooks/useToast";
import { cn } from "@/lib/utils";

const STATUS_LABEL: Record<string, string> = {
  active: "活跃", paused: "暂停", resolved: "已收线", abandoned: "废弃",
};
const REL_LABEL: Record<string, string> = {
  merge: "汇入", intersect: "相交", parallel: "并行", conflict: "对抗",
};
const NODE_LABEL: Record<string, string> = {
  foreshadow: "伏笔", event: "事件", milestone: "里程碑",
};
const ALERT_COLOR: Record<string, string> = {
  danger: "bg-danger", warning: "bg-warning", info: "bg-primary",
};

const emptyLine = {
  name: "", line_type: "", tags: [] as string[], status: "active", progress: 0,
  summary: "", notes: "", planned_resolve_chapter: 0, volume: "",
};

export default function StorylineView() {
  const { projectId } = useCurrentProject();
  const { showSuccess, showError } = useToast();

  const [meta, setMeta] = useState<StorylineMeta | null>(null);
  const [lines, setLines] = useState<Storyline[]>([]);
  const [activeTag, setActiveTag] = useState("");
  const [statusFilter, setStatusFilter] = useState("");
  const [search, setSearch] = useState("");
  const [selected, setSelected] = useState<number | null>(null);
  const [detail, setDetail] = useState<StorylineDetail | null>(null);

  // 新建/编辑线弹窗
  const [lineOpen, setLineOpen] = useState(false);
  const [editing, setEditing] = useState<Storyline | null>(null);
  const [lineForm, setLineForm] = useState({ ...emptyLine });
  const [savingLine, setSavingLine] = useState(false);

  // 节点/交汇弹窗
  const [nodeOpen, setNodeOpen] = useState(false);
  const [nodeForm, setNodeForm] = useState<Partial<StorylineNode>>({ node_type: "event", chapter: 0, title: "" });
  const [relOpen, setRelOpen] = useState(false);
  const [relForm, setRelForm] = useState<Partial<StorylineRelation>>({ relation_type: "merge", chapter: 0 });

  // 扫描
  const [alerts, setAlerts] = useState<ScanAlert[]>([]);
  const [scanning, setScanning] = useState(false);
  const [scanLog, setScanLog] = useState<string[]>([]);
  const abortRef = useRef<AbortController | null>(null);

  // LLM 识别创建
  const [creating, setCreating] = useState(false);
  const [createLog, setCreateLog] = useState<{ icon: string; text: string }[]>([]);
  const createAbortRef = useRef<AbortController | null>(null);

  const loadLines = useCallback(async () => {
    if (!projectId) return;
    try {
      const params: { tag?: string; status?: string; search?: string } = {};
      if (activeTag) params.tag = activeTag;
      if (statusFilter) params.status = statusFilter;
      if (search) params.search = search;
      const r = await api.listStorylines(projectId, params);
      setLines(r.items);
    } catch (e: any) {
      showError("加载线失败：" + (e?.message || "未知错误"));
    }
  }, [projectId, activeTag, statusFilter, search, showError]);

  const loadDetail = useCallback(async (id: number) => {
    if (!projectId) return;
    try {
      const d = await api.getStorylineDetail(projectId, id);
      setDetail(d);
    } catch (e: any) {
      showError("加载线详情失败：" + (e?.message || "未知错误"));
    }
  }, [projectId, showError]);

  useEffect(() => {
    api.storylineMeta().then(setMeta).catch(() => {});
  }, []);
  useEffect(() => { loadLines(); }, [loadLines]);
  useEffect(() => {
    if (selected) loadDetail(selected);
    else setDetail(null);
  }, [selected, loadDetail]);

  const openCreate = () => { setEditing(null); setLineForm({ ...emptyLine }); setLineOpen(true); };
  const openEdit = (l: Storyline) => {
    setEditing(l);
    setLineForm({ name: l.name, line_type: l.line_type, tags: [...(l.tags || [])],
      status: l.status, progress: l.progress, summary: l.summary, notes: l.notes,
      planned_resolve_chapter: l.planned_resolve_chapter, volume: l.volume });
    setLineOpen(true);
  };

  const toggleTag = (t: string) => {
    setLineForm((f) => {
      const tags = f.tags.includes(t) ? f.tags.filter((x) => x !== t) : [...f.tags, t];
      return { ...f, tags };
    });
  };

  const saveLine = async () => {
    if (!projectId) return;
    if (!lineForm.name.trim()) { showError("线名不能为空"); return; }
    setSavingLine(true);
    try {
      if (editing) await api.updateStoryline(projectId, editing.id, lineForm);
      else await api.createStoryline(projectId, lineForm);
      showSuccess(editing ? "已更新" : "已创建");
      setLineOpen(false);
      await loadLines();
    } catch (e: any) {
      showError("保存失败：" + (e?.message || "未知错误"));
    } finally { setSavingLine(false); }
  };

  const deleteLine = async (l: Storyline) => {
    if (!projectId) return;
    if (!window.confirm(`删除线「${l.name}」？其节点与交汇关系将一并删除。`)) return;
    try {
      await api.deleteStoryline(projectId, l.id);
      if (selected === l.id) setSelected(null);
      await loadLines();
      showSuccess("已删除");
    } catch (e: any) { showError("删除失败：" + (e?.message || "未知错误")); }
  };

  const addNode = async () => {
    if (!selected || !nodeForm.title?.trim()) { showError("请输入节点名"); return; }
    try {
      await api.createStorylineNode(projectId, selected, nodeForm);
      setNodeOpen(false);
      setNodeForm({ node_type: "event", chapter: 0, title: "" });
      await loadDetail(selected);
    } catch (e: any) { showError("加节点失败：" + (e?.message || "未知错误")); }
  };

  const deleteNode = async (n: StorylineNode) => {
    if (!selected) return;
    try {
      await api.deleteStorylineNode(n.id);
      await loadDetail(selected);
    } catch (e: any) { showError("删除节点失败：" + (e?.message || "未知错误")); }
  };

  const addRelation = async () => {
    if (!projectId || !relForm.target_storyline_id) { showError("请选择另一条线"); return; }
    try {
      await api.createStorylineRelation(projectId, {
        ...relForm, source_storyline_id: selected ?? 0, project_id: projectId,
      });
      setRelOpen(false);
      setRelForm({ relation_type: "merge", chapter: 0 });
      if (selected) await loadDetail(selected);
    } catch (e: any) { showError("建交汇失败：" + (e?.message || "未知错误")); }
  };

  const runScan = async (all: boolean) => {
    if (!projectId) return;
    setScanning(true);
    setAlerts([]);
    setScanLog([]);
    abortRef.current = api.scanStorylines(
      projectId, all ? null : (selected ? (detail?.line.last_active_chapter || 1) : 1),
      (d) => {
        const v = d.verdict === "adopt" ? "✓ 采用" : "⚠ 待确认";
        const name = d.llm?.name || `线${d.llm?.storyline_id ?? ""}`;
        setScanLog((prev) => [...prev.slice(-60), `${name}: ${v}`]);
      },
      (d) => setAlerts(d.items || []),
      () => { setScanning(false); showSuccess("扫描完成"); },
      (msg) => { setScanning(false); showError(msg); },
    );
  };

  const stopScan = () => {
    abortRef.current?.abort();
    abortRef.current = null;
    setScanning(false);
  };

  const runCreate = () => {
    if (!projectId) return;
    setCreating(true);
    setCreateLog([]);
    createAbortRef.current = api.llmCreateStorylines(
      projectId,
      (d) => setCreateLog((prev) => [...prev.slice(-60),
        { icon: "📖", text: `已收集大纲 ${d.chars} 字，识别中...` }]),
      (d) => {
        const items = d.storylines || [];
        const logs = items.map((l: any) => ({
          icon: l.line_type === "主线" ? "⭐" : "➤",
          text: `${l.name}（${(l.tags || []).join("/")}）· ${(l.nodes || []).length} 节点`,
        }));
        setCreateLog((prev) => [...prev.slice(-60),
          { icon: "✨", text: `识别到 ${items.length} 条线：` }, ...logs]);
      },
      (d) => {
        setCreateLog((prev) => [...prev.slice(-60), {
          icon: "✅",
          text: `已建 ${d.created_lines} 条线 · 跳过重复 ${d.skipped_lines} 条 · 新建节点 ${d.created_nodes} 个`,
        }]);
        setCreating(false);
        showSuccess(`AI 已建 ${d.created_lines} 条线`);
        loadLines();
      },
      (msg) => { setCreating(false); showError(msg); },
    );
  };

  const stopCreate = () => {
    createAbortRef.current?.abort();
    createAbortRef.current = null;
    setCreating(false);
  };

  const tags = meta?.tags || [];
  const relTypes = meta?.relation_types || [];

  return (
    <div className="flex h-full flex-col overflow-y-auto lg:overflow-hidden">
      <div className="mx-auto w-full max-w-7xl shrink-0 space-y-4 p-4 md:p-6 lg:pb-3">
      <div className="flex flex-col gap-3 md:flex-row md:items-center md:justify-between">
        <div>
          <h1 className="text-lg font-semibold text-foreground">叙事线</h1>
          <p className="text-sm text-muted">主线/支线 × 明线/暗线 + 自定义线，防断线防伏笔烂尾</p>
        </div>
        <div className="flex flex-wrap items-center gap-2">
          <div className="relative">
            <Search className="absolute left-2.5 top-2.5 h-3.5 w-3.5 text-muted" />
            <Input
              value={search} onChange={(e) => setSearch(e.target.value)}
              placeholder="搜索线/类型..." className="w-44 pl-8"
            />
          </div>
          <Select value={statusFilter} onChange={(e) => setStatusFilter(e.target.value)} className="w-28">
            <option value="">全部状态</option>
            {(meta?.statuses || []).map((s) => (
              <option key={s} value={s}>{STATUS_LABEL[s] || s}</option>
            ))}
          </Select>
          <Button variant="primary" onClick={openCreate}>
            <Plus className="h-4 w-4" /> 新建线
          </Button>
          {scanning ? (
            <Button variant="danger" onClick={stopScan}>
              <Square className="h-4 w-4" /> 中断
            </Button>
          ) : (
            <Button variant="outline" onClick={() => runScan(false)} disabled={!selected}>
              <ScanSearch className="h-4 w-4" /> 扫描
            </Button>
          )}
          <Button variant="ghost" onClick={() => runScan(true)} disabled={scanning}>
            全书扫描
          </Button>
          {creating ? (
            <Button variant="danger" onClick={stopCreate}>
              <Square className="h-4 w-4" /> 中断
            </Button>
          ) : (
            <Button variant="outline" onClick={runCreate} disabled={scanning}>
              <Sparkles className="h-4 w-4" /> AI 识别
            </Button>
          )}
        </div>
      </div>

      {/* 标签筛选 chips */}
      <div className="mb-4 flex flex-wrap items-center gap-1.5">
        <button
          onClick={() => setActiveTag("")}
          className={cn("rounded-lg px-3 py-1 text-xs font-medium transition-colors",
            !activeTag ? "bg-primary text-primary-foreground" : "bg-surface-hover text-muted hover:text-foreground")}
        >全部</button>
        {tags.map((t) => (
          <button
            key={t} onClick={() => setActiveTag(t === activeTag ? "" : t)}
            className={cn("rounded-lg px-3 py-1 text-xs font-medium transition-colors",
              activeTag === t ? "bg-primary text-primary-foreground" : "bg-surface-hover text-muted hover:text-foreground")}
          >{t}</button>
        ))}
        <span className="ml-auto text-xs text-muted">{lines.length} 条线</span>
      </div>

      {/* LLM 识别建线日志 */}
      {createLog.length > 0 && (
        <Card>
          <CardContent className="space-y-1 py-3">
            {creating && (
              <div className="mb-1 flex items-center gap-2 text-xs text-muted">
                <Loader2 className="h-3.5 w-3.5 animate-spin" /> LLM 正在从大纲识别叙事线并建线...
              </div>
            )}
            <div className="max-h-40 overflow-y-auto space-y-0.5 text-xs">
              {createLog.map((s, i) => (
                <div key={i} className="text-muted">{s.icon} {s.text}</div>
              ))}
            </div>
          </CardContent>
        </Card>
      )}
      </div>

      <div className="mx-auto w-full max-w-7xl min-h-0 flex-1 px-4 pb-6 md:px-6">
      <div className="grid h-full gap-4 lg:grid-cols-[300px_1fr]">
        {/* ── 左栏：线看板（桌面独立滚动） ── */}
        <div className="space-y-2 lg:h-full lg:overflow-y-auto lg:pr-1">
          {lines.length === 0 && (
            <Card className="border-dashed">
              <CardContent className="py-8 text-center text-sm text-muted">
                还没有线，点「新建线」开始，或扫描后由 AI 建议建线
              </CardContent>
            </Card>
          )}
          {lines.map((l) => {
            const hasAlert = alerts.some((a) => a.storyline_id === l.id);
            return (
              <Card
                key={l.id}
                className={cn("cursor-pointer transition-colors hover:bg-surface-elevated",
                  selected === l.id && "ring-1 ring-primary",
                  hasAlert && "border-danger/50")}
                onClick={() => setSelected(l.id)}
              >
                <CardContent className="space-y-2 p-3">
                  <div className="flex items-start justify-between gap-2">
                    <div className="min-w-0">
                      <div className="flex flex-wrap items-center gap-1">
                        <span className="truncate text-sm font-semibold text-foreground">{l.name}</span>
                        {l.line_type && (
                          <Badge variant="default">{l.line_type}</Badge>
                        )}
                      </div>
                      <div className="mt-1 flex flex-wrap gap-1">
                        {(l.tags || []).map((t) => (
                          <Badge key={t} variant={t === "主线" || t === "明线" ? "primary" : "default"}>{t}</Badge>
                        ))}
                      </div>
                    </div>
                    <div className="flex shrink-0 gap-0.5">
                      <Button variant="ghost" size="sm" className="h-6 w-6 px-0"
                        onClick={(e) => { e.stopPropagation(); openEdit(l); }} title="编辑">
                        ✏️
                      </Button>
                      <Button variant="ghost" size="sm" className="h-6 w-6 px-0 text-danger"
                        onClick={(e) => { e.stopPropagation(); deleteLine(l); }} title="删除">
                        <Trash2 className="h-3 w-3" />
                      </Button>
                    </div>
                  </div>
                  <div className="flex items-center gap-2">
                    <Progress value={l.progress} className="flex-1" />
                    <span className="text-xs text-muted">{l.progress}%</span>
                  </div>
                  <div className="flex flex-wrap gap-1 text-xs text-muted">
                    <Badge variant={hasAlert ? "danger" : "default"}>
                      {STATUS_LABEL[l.status] || l.status}
                    </Badge>
                    <span>节点 {l.node_count}</span>
                    <span>交汇 {l.relation_count}</span>
                    {l.planned_resolve_chapter > 0 && <span>计划收线 第{l.planned_resolve_chapter}章</span>}
                  </div>
                </CardContent>
              </Card>
            );
          })}
        </div>

        {/* ── 右栏：选中线网络（桌面独立滚动） ── */}
        <div className="space-y-4 lg:h-full lg:overflow-y-auto lg:pl-1">
          {!detail && (
            <Card className="flex min-h-[40vh] items-center justify-center border-dashed">
              <CardContent className="text-center text-muted">
                <GitMerge className="mx-auto mb-2 h-8 w-8" />
                <p className="text-sm">选中左侧一条线，查看它的伏笔链/事件/交汇</p>
              </CardContent>
            </Card>
          )}
          {detail && (
            <>
              <Card>
                <CardHeader className="flex-row items-center justify-between space-y-0">
                  <CardTitle>{detail.line.name}</CardTitle>
                  <div className="flex gap-2">
                    <Button variant="outline" size="sm" onClick={() => setNodeOpen(true)}>
                      <Plus className="h-3.5 w-3.5" /> 加节点
                    </Button>
                    <Button variant="outline" size="sm" onClick={() => setRelOpen(true)}>
                      <GitMerge className="h-3.5 w-3.5" /> 加交汇
                    </Button>
                  </div>
                </CardHeader>
                <CardContent className="space-y-3">
                  <div className="flex flex-wrap items-center gap-1.5">
                    {(detail.line.tags || []).map((t) => <Badge key={t} variant="primary">{t}</Badge>)}
                    {detail.line.line_type && <Badge variant="default">{detail.line.line_type}</Badge>}
                    <Badge variant="default">{STATUS_LABEL[detail.line.status] || detail.line.status}</Badge>
                    <Badge variant="default">进度 {detail.line.progress}%</Badge>
                    {detail.line.last_active_chapter > 0 && (
                      <Badge variant="default">最近推进 第{detail.line.last_active_chapter}章</Badge>
                    )}
                  </div>
                  {detail.line.summary && <p className="text-sm text-muted">{detail.line.summary}</p>}

                  {/* 节点链 */}
                  <div>
                    <div className="mb-2 text-xs font-medium text-muted">节点链（伏笔/事件/里程碑）</div>
                    {detail.nodes.length === 0 && (
                      <p className="text-xs text-muted">暂无节点</p>
                    )}
                    <div className="space-y-1.5">
                      {detail.nodes.map((n, i) => (
                        <div key={n.id} className="flex items-center gap-2">
                          <div className="flex items-center gap-1.5 rounded-lg border border-border bg-surface-elevated px-3 py-2 text-xs">
                            <Badge variant={n.node_type === "foreshadow" ? "warning" : "default"}>
                              {NODE_LABEL[n.node_type] || n.node_type}
                            </Badge>
                            {n.chapter > 0 && <span className="text-muted">第{n.chapter}章</span>}
                            <span className="font-medium text-foreground">{n.title}</span>
                            {n.foreshadow_id && <span className="text-muted">({n.foreshadow_id})</span>}
                            <Button variant="ghost" size="sm" className="h-5 w-5 px-0 text-danger"
                              onClick={() => deleteNode(n)} title="删除节点">
                              <X className="h-3 w-3" />
                            </Button>
                          </div>
                          {i < detail.nodes.length - 1 && <span className="text-muted">→</span>}
                        </div>
                      ))}
                    </div>
                  </div>

                  {/* 交汇 */}
                  <div>
                    <div className="mb-2 text-xs font-medium text-muted">交汇关系（与其它线）</div>
                    {detail.relations.length === 0 && <p className="text-xs text-muted">暂无交汇</p>}
                    <div className="flex flex-wrap gap-1.5">
                      {detail.relations.map((r) => {
                        const otherId = r.source_storyline_id === detail.line.id
                          ? r.target_storyline_id : r.source_storyline_id;
                        const other = lines.find((x) => x.id === otherId);
                        return (
                          <div key={r.id} className="flex items-center gap-1.5 rounded-lg border border-border bg-surface-elevated px-3 py-1.5 text-xs">
                            <Badge variant="warning">{REL_LABEL[r.relation_type] || r.relation_type}</Badge>
                            <span className="text-foreground">{other?.name || `线${otherId}`}</span>
                            {r.chapter > 0 && <span className="text-muted">第{r.chapter}章</span>}
                            <Button variant="ghost" size="sm" className="h-5 w-5 px-0 text-danger"
                              onClick={async () => {
                                try {
                                  await api.deleteStorylineRelation(r.id);
                                  await loadDetail(detail.line.id);
                                } catch (e: any) { showError(e?.message || "删除失败"); }
                              }} title="删除交汇">
                              <X className="h-3 w-3" />
                            </Button>
                          </div>
                        );
                      })}
                    </div>
                  </div>
                </CardContent>
              </Card>

              {/* 扫描日志 + 预警 */}
              <Card>
                <CardHeader>
                  <CardTitle>健康度扫描（双通道：规则+LLM 交叉验证）</CardTitle>
                </CardHeader>
                <CardContent className="space-y-3">
                  {scanning && (
                    <div className="rounded-lg border border-border bg-surface-elevated p-2">
                      <div className="mb-1 flex items-center gap-2 text-xs text-muted">
                        <Loader2 className="h-3.5 w-3.5 animate-spin" /> 扫描中...
                      </div>
                      <div className="max-h-32 overflow-y-auto space-y-0.5 text-xs">
                        {scanLog.map((s, i) => <div key={i} className="text-muted">{s}</div>)}
                      </div>
                    </div>
                  )}
                  {alerts.length === 0 && !scanning && (
                    <p className="text-xs text-muted">点「扫描」检测本线健康度，或「全书扫描」</p>
                  )}
                  <div className="space-y-1.5">
                    {alerts.map((a, i) => (
                      <div key={i} className="flex items-start gap-2 rounded-lg border border-border bg-surface-elevated px-3 py-2 text-xs">
                        <span className={cn("mt-1 h-2 w-2 shrink-0 rounded-full", ALERT_COLOR[a.severity] || "bg-muted")} />
                        <span className="text-foreground">{a.message}</span>
                      </div>
                    ))}
                  </div>
                </CardContent>
              </Card>
            </>
          )}
        </div>
      </div>
      </div>

      {/* 新建/编辑线 Dialog */}
      <Dialog open={lineOpen} onOpenChange={setLineOpen}>
        <DialogContent>
          <DialogHeader><DialogTitle>{editing ? "编辑线" : "新建线"}</DialogTitle></DialogHeader>
          <div className="space-y-3">
            <div className="space-y-1">
              <span className="text-sm font-medium">线名 *</span>
              <Input value={lineForm.name} placeholder="如：家族复仇线 / 时间线·主"
                onChange={(e) => setLineForm((f) => ({ ...f, name: e.target.value }))} />
            </div>
            <div className="space-y-1">
              <span className="text-sm font-medium">自定义类型</span>
              <Input value={lineForm.line_type} placeholder="如：复仇线 / 时间线（可空）"
                onChange={(e) => setLineForm((f) => ({ ...f, line_type: e.target.value }))} />
            </div>
            <div className="space-y-1">
              <span className="text-sm font-medium">标签（固定维度，可多选）</span>
              <div className="flex flex-wrap gap-1.5">
                {tags.map((t) => (
                  <button key={t} onClick={() => toggleTag(t)}
                    className={cn("rounded-lg px-3 py-1 text-xs font-medium transition-colors",
                      lineForm.tags.includes(t) ? "bg-primary text-primary-foreground" : "bg-surface-hover text-muted")}>
                    {t}
                  </button>
                ))}
              </div>
            </div>
            <div className="grid grid-cols-3 gap-2">
              <div className="space-y-1">
                <span className="text-sm font-medium">状态</span>
                <Select value={lineForm.status}
                  onChange={(e) => setLineForm((f) => ({ ...f, status: e.target.value }))}>
                  {(meta?.statuses || []).map((s) => (
                    <option key={s} value={s}>{STATUS_LABEL[s] || s}</option>
                  ))}
                </Select>
              </div>
              <div className="space-y-1">
                <span className="text-sm font-medium">进度%</span>
                <Input type="number" min={0} max={100} value={lineForm.progress}
                  onChange={(e) => setLineForm((f) => ({ ...f, progress: Number(e.target.value) }))} />
              </div>
              <div className="space-y-1">
                <span className="text-sm font-medium">计划收线章</span>
                <Input type="number" min={0} value={lineForm.planned_resolve_chapter}
                  onChange={(e) => setLineForm((f) => ({ ...f, planned_resolve_chapter: Number(e.target.value) }))} />
              </div>
            </div>
            <div className="space-y-1">
              <span className="text-sm font-medium">所属卷（分组用）</span>
              <Input value={lineForm.volume} placeholder="如：卷一（可空）"
                onChange={(e) => setLineForm((f) => ({ ...f, volume: e.target.value }))} />
            </div>
            <div className="space-y-1">
              <span className="text-sm font-medium">一句话说明</span>
              <Textarea rows={2} value={lineForm.summary}
                onChange={(e) => setLineForm((f) => ({ ...f, summary: e.target.value }))} />
            </div>
            <div className="flex justify-end gap-2 pt-1">
              <Button variant="outline" onClick={() => setLineOpen(false)} disabled={savingLine}>取消</Button>
              <Button variant="primary" onClick={saveLine} disabled={savingLine || !lineForm.name.trim()}>
                {savingLine ? "保存中..." : "保存"}
              </Button>
            </div>
          </div>
        </DialogContent>
      </Dialog>

      {/* 加节点 Dialog */}
      <Dialog open={nodeOpen} onOpenChange={setNodeOpen}>
        <DialogContent>
          <DialogHeader><DialogTitle>加节点</DialogTitle></DialogHeader>
          <div className="space-y-3">
            <div className="space-y-1">
              <span className="text-sm font-medium">类型</span>
              <Select value={nodeForm.node_type}
                onChange={(e) => setNodeForm((f) => ({ ...f, node_type: e.target.value }))}>
                {(meta?.node_types || []).map((t) => (
                  <option key={t} value={t}>{NODE_LABEL[t] || t}</option>
                ))}
              </Select>
            </div>
            <div className="grid grid-cols-2 gap-2">
              <div className="space-y-1">
                <span className="text-sm font-medium">章节</span>
                <Input type="number" min={0} value={nodeForm.chapter || 0}
                  onChange={(e) => setNodeForm((f) => ({ ...f, chapter: Number(e.target.value) }))} />
              </div>
              <div className="space-y-1">
                <span className="text-sm font-medium">伏笔ID（可选）</span>
                <Input value={nodeForm.foreshadow_id || ""} placeholder="F-001"
                  onChange={(e) => setNodeForm((f) => ({ ...f, foreshadow_id: e.target.value }))} />
              </div>
            </div>
            <div className="space-y-1">
              <span className="text-sm font-medium">节点名 *</span>
              <Input value={nodeForm.title || ""} placeholder="如：真凶现身"
                onChange={(e) => setNodeForm((f) => ({ ...f, title: e.target.value }))} />
            </div>
            <div className="flex justify-end gap-2">
              <Button variant="outline" onClick={() => setNodeOpen(false)}>取消</Button>
              <Button variant="primary" onClick={addNode}>添加</Button>
            </div>
          </div>
        </DialogContent>
      </Dialog>

      {/* 加交汇 Dialog */}
      <Dialog open={relOpen} onOpenChange={setRelOpen}>
        <DialogContent>
          <DialogHeader><DialogTitle>建交汇关系</DialogTitle></DialogHeader>
          <div className="space-y-3">
            <div className="space-y-1">
              <span className="text-sm font-medium">与哪条线交汇</span>
              <Select value={relForm.target_storyline_id ? String(relForm.target_storyline_id) : ""}
                onChange={(e) => setRelForm((f) => ({ ...f, target_storyline_id: Number(e.target.value) }))}>
                <option value="">选择线...</option>
                {lines.filter((l) => l.id !== selected).map((l) => (
                  <option key={l.id} value={l.id}>{l.name}</option>
                ))}
              </Select>
            </div>
            <div className="grid grid-cols-2 gap-2">
              <div className="space-y-1">
                <span className="text-sm font-medium">类型</span>
                <Select value={relForm.relation_type}
                  onChange={(e) => setRelForm((f) => ({ ...f, relation_type: e.target.value }))}>
                  {relTypes.map((t) => <option key={t} value={t}>{REL_LABEL[t] || t}</option>)}
                </Select>
              </div>
              <div className="space-y-1">
                <span className="text-sm font-medium">交汇章节</span>
                <Input type="number" min={0} value={relForm.chapter || 0}
                  onChange={(e) => setRelForm((f) => ({ ...f, chapter: Number(e.target.value) }))} />
              </div>
            </div>
            <div className="flex justify-end gap-2">
              <Button variant="outline" onClick={() => setRelOpen(false)}>取消</Button>
              <Button variant="primary" onClick={addRelation}>添加</Button>
            </div>
          </div>
        </DialogContent>
      </Dialog>
    </div>
  );
}
