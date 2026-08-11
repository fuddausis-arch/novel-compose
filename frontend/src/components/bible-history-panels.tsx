/**
 * 百科卡页新增面板：
 * - PlotDebtsView：剧情债查看/管理（列表 + 状态筛选 + 新建/编辑/删除/标记解决）
 * - RelationshipChangesView：关系变更流（只读）
 * - StatesEventsView：世界状态快照 + 事件流（只读）
 */
import { useCallback, useEffect, useMemo, useState } from "react";
import { CheckCircle2, Loader2, Pencil, Plus, Trash2 } from "lucide-react";
import { api } from "@/api";
import { bumpDataVersion } from "@/store/slices/dataVersion";
import { useToast } from "@/hooks/useToast";
import { useConfirmDialog } from "@/hooks/useConfirmDialog";
import { cn } from "@/lib/utils";
import type { PlotDebt, PlotDebtStatus, RelationshipChange, StateChange, TruthEvent } from "@/types";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Select } from "@/components/ui/select";
import { Textarea } from "@/components/ui/textarea";
import { Dialog, DialogContent, DialogHeader, DialogTitle } from "@/components/ui/dialog";

// ==================== 剧情债 ====================

const DEBT_STATUS_META: Record<PlotDebtStatus, { text: string; cls: string }> = {
  open: { text: "未解决", cls: "bg-warning/15 text-warning" },
  resolved: { text: "已解决", cls: "bg-success/15 text-success" },
  abandoned: { text: "已放弃", cls: "bg-secondary text-muted" },
};

const DEBT_TYPES = ["因果", "悬念", "承诺", "冲突", "成长", "复仇", "其他"];

interface DebtFormState {
  debt_type: string;
  description: string;
  pressure: number;
  term: string;
  status: PlotDebtStatus;
  created_chapter: number;
  resolved_chapter: number;
}

const EMPTY_DEBT_FORM: DebtFormState = {
  debt_type: "因果",
  description: "",
  pressure: 3,
  term: "short",
  status: "open",
  created_chapter: 0,
  resolved_chapter: 0,
};

export function PlotDebtsView({ projectId }: { projectId: number }) {
  const { showSuccess, showError } = useToast();
  const { confirm: confirmDelete, dialog: deleteDialog } = useConfirmDialog();

  const [debts, setDebts] = useState<PlotDebt[]>([]);
  const [loading, setLoading] = useState(false);
  const [statusFilter, setStatusFilter] = useState<string>("");
  const [editing, setEditing] = useState<PlotDebt | null>(null);
  const [dialogOpen, setDialogOpen] = useState(false);
  const [form, setForm] = useState<DebtFormState>(EMPTY_DEBT_FORM);
  const [saving, setSaving] = useState(false);

  const load = useCallback(async (silent = false) => {
    // silent=true：静默刷新（保存/删除/标记后用），不切 loading 保持容器常驻不跳顶
    if (!projectId) return;
    if (!silent) setLoading(true);
    try {
      const data = await api.listPlotDebts(projectId, statusFilter || undefined);
      setDebts(data);
    } catch (e: any) {
      showError("加载剧情债失败：" + e.message);
    } finally {
      if (!silent) setLoading(false);
    }
  }, [projectId, statusFilter, showError]);

  useEffect(() => {
    void load();
  }, [load]);

  const filtered = useMemo(
    () => (statusFilter ? debts.filter((d) => d.status === statusFilter) : debts),
    [debts, statusFilter],
  );

  const openCreate = () => {
    setEditing(null);
    setForm(EMPTY_DEBT_FORM);
    setDialogOpen(true);
  };

  const openEdit = (d: PlotDebt) => {
    setEditing(d);
    setForm({
      debt_type: d.debt_type || "因果",
      description: d.description || "",
      pressure: d.pressure ?? 3,
      term: d.term || "short",
      status: d.status || "open",
      created_chapter: d.created_chapter ?? 0,
      resolved_chapter: d.resolved_chapter ?? 0,
    });
    setDialogOpen(true);
  };

  const handleSave = async () => {
    if (!projectId) return;
    if (!form.description.trim()) {
      showError("请填写剧情债描述");
      return;
    }
    setSaving(true);
    try {
      if (editing) {
        await api.updatePlotDebt(projectId, editing.id, form);
      } else {
        await api.createPlotDebt(projectId, form);
      }
      showSuccess(editing ? "剧情债已更新" : "剧情债已创建");
      setDialogOpen(false);
      bumpDataVersion("bible");
      await load(true);
    } catch (e: any) {
      showError("保存失败：" + e.message);
    } finally {
      setSaving(false);
    }
  };

  const handleDelete = async (d: PlotDebt) => {
    const ok = await confirmDelete({
      title: "删除剧情债",
      description: `确定删除剧情债「${d.description.slice(0, 40)}」吗？此操作不可恢复。`,
      confirmText: "删除",
      cancelText: "取消",
      variant: "danger",
    });
    if (!ok || !projectId) return;
    try {
      await api.deletePlotDebt(projectId, d.id);
      showSuccess("剧情债已删除");
      bumpDataVersion("bible");
      await load();
    } catch (e: any) {
      showError("删除失败：" + e.message);
    }
  };

  const handleMarkResolved = async (d: PlotDebt) => {
    if (!projectId) return;
    try {
      await api.updatePlotDebt(projectId, d.id, {
        ...d,
        status: "resolved",
        resolved_chapter: d.resolved_chapter || d.created_chapter || 0,
      });
      showSuccess("剧情债已标记为解决");
      bumpDataVersion("bible");
      await load(true);
    } catch (e: any) {
      showError("操作失败：" + e.message);
    }
  };

  const counts = useMemo(() => {
    const c: Record<string, number> = { open: 0, resolved: 0, abandoned: 0 };
    debts.forEach((d) => { if (d.status in c) c[d.status] += 1; });
    return c;
  }, [debts]);

  return (
    <div className="space-y-3 p-4">
      {/* 工具栏：状态筛选 + 新建 */}
      <div className="flex flex-wrap items-center gap-2">
        <Select
          className="w-32"
          value={statusFilter}
          onChange={(e) => setStatusFilter(e.target.value)}
        >
          <option value="">全部状态</option>
          <option value="open">未解决（{counts.open}）</option>
          <option value="resolved">已解决（{counts.resolved}）</option>
          <option value="abandoned">已放弃（{counts.abandoned}）</option>
        </Select>
        <div className="ml-auto">
          <Button size="sm" variant="primary" onClick={openCreate}>
            <Plus className="h-3.5 w-3.5 mr-1" /> 新建剧情债
          </Button>
        </div>
      </div>

      {loading ? (
        <div className="flex items-center justify-center py-16 text-muted">
          <Loader2 className="h-4 w-4 animate-spin mr-2" /> 加载中…
        </div>
      ) : filtered.length === 0 ? (
        <div className="flex h-full items-center justify-center py-16 text-sm text-muted">
          暂无剧情债{statusFilter ? "（当前筛选）" : "，点击右上角新建"}
        </div>
      ) : (
        <div className="grid grid-cols-1 gap-3 lg:grid-cols-2">
          {filtered.map((d) => (
            <div key={d.id} className="flex flex-col gap-2 rounded-lg border border-border bg-surface-elevated p-3">
              <div className="flex flex-wrap items-center gap-2">
                <Badge variant="primary">{d.debt_type || "因果"}</Badge>
                <Badge className={DEBT_STATUS_META[d.status]?.cls ?? "bg-secondary text-muted"}>
                  {DEBT_STATUS_META[d.status]?.text ?? d.status}
                </Badge>
                <Badge variant="default">压力 {d.pressure}</Badge>
                <Badge variant="default">{d.term === "long" ? "长期" : d.term === "medium" ? "中期" : "短期"}</Badge>
                {d.created_chapter > 0 && <span className="text-[11px] text-muted">第{d.created_chapter}章埋设</span>}
                {d.status === "resolved" && d.resolved_chapter > 0 && (
                  <span className="text-[11px] text-success">第{d.resolved_chapter}章解决</span>
                )}
              </div>
              <p className="text-sm text-foreground whitespace-pre-wrap break-words">{d.description}</p>
              <div className="mt-auto flex items-center justify-end gap-1">
                {d.status === "open" && (
                  <Button size="sm" variant="ghost" className="text-success" onClick={() => handleMarkResolved(d)}>
                    <CheckCircle2 className="h-3.5 w-3.5 mr-1" /> 标记解决
                  </Button>
                )}
                <Button size="sm" variant="ghost" onClick={() => openEdit(d)}>
                  <Pencil className="h-3.5 w-3.5 mr-1" /> 编辑
                </Button>
                <Button size="sm" variant="ghost" className="text-danger hover:text-danger" onClick={() => handleDelete(d)}>
                  <Trash2 className="h-3.5 w-3.5 mr-1" /> 删除
                </Button>
              </div>
            </div>
          ))}
        </div>
      )}

      {/* 新建 / 编辑弹窗 */}
      <Dialog open={dialogOpen} onOpenChange={(o) => !o && setDialogOpen(false)}>
        <DialogContent className="max-w-md">
          <DialogHeader>
            <DialogTitle>{editing ? "编辑剧情债" : "新建剧情债"}</DialogTitle>
          </DialogHeader>
          <div className="space-y-3">
            <label className="block">
              <span className="mb-1 block text-xs font-medium">债务类型</span>
              <Select
                value={form.debt_type}
                onChange={(e) => setForm((f) => ({ ...f, debt_type: e.target.value }))}
              >
                {DEBT_TYPES.map((t) => (
                  <option key={t} value={t}>{t}</option>
                ))}
              </Select>
            </label>
            <label className="block">
              <span className="mb-1 block text-xs font-medium">描述</span>
              <Textarea
                rows={3}
                value={form.description}
                onChange={(e) => setForm((f) => ({ ...f, description: e.target.value }))}
                placeholder="例如：主角承诺帮老乞丐找女儿，须在第 40 章前兑现"
              />
            </label>
            <div className="grid grid-cols-2 gap-3">
              <label className="block">
                <span className="mb-1 block text-xs font-medium">压力值（1-5）</span>
                <Input
                  type="number"
                  min={1}
                  max={5}
                  value={form.pressure}
                  onChange={(e) => setForm((f) => ({ ...f, pressure: Number(e.target.value) || 3 }))}
                />
              </label>
              <label className="block">
                <span className="mb-1 block text-xs font-medium">期限</span>
                <Select
                  value={form.term}
                  onChange={(e) => setForm((f) => ({ ...f, term: e.target.value }))}
                >
                  <option value="short">短期</option>
                  <option value="medium">中期</option>
                  <option value="long">长期</option>
                </Select>
              </label>
            </div>
            <div className="grid grid-cols-2 gap-3">
              <label className="block">
                <span className="mb-1 block text-xs font-medium">埋设章节</span>
                <Input
                  type="number"
                  min={0}
                  value={form.created_chapter ?? ""}
                  onChange={(e) => setForm((f) => ({ ...f, created_chapter: Number(e.target.value) || 0 }))}
                />
              </label>
              <label className="block">
                <span className="mb-1 block text-xs font-medium">状态</span>
                <Select
                  value={form.status}
                  onChange={(e) => setForm((f) => ({ ...f, status: e.target.value as PlotDebtStatus }))}
                >
                  <option value="open">未解决</option>
                  <option value="resolved">已解决</option>
                  <option value="abandoned">已放弃</option>
                </Select>
              </label>
            </div>
          </div>
          <div className="mt-5 flex justify-end gap-2">
            <Button variant="ghost" size="sm" onClick={() => setDialogOpen(false)} disabled={saving}>
              取消
            </Button>
            <Button variant="primary" size="sm" onClick={handleSave} disabled={saving}>
              {saving ? "保存中…" : "保存"}
            </Button>
          </div>
        </DialogContent>
      </Dialog>

      {deleteDialog}
    </div>
  );
}

// ==================== 关系变更（只读） ====================

const RELATION_FIELD_LABELS: Record<string, string> = {
  relation_type: "关系类型",
  relation_subtype: "关系子类型",
  strength: "强度",
  status: "状态",
  since_chapter: "起始章节",
};

export function RelationshipChangesView({ projectId }: { projectId: number }) {
  const { showError } = useToast();
  const [changes, setChanges] = useState<RelationshipChange[]>([]);
  const [loading, setLoading] = useState(false);

  const load = useCallback(async () => {
    if (!projectId) return;
    setLoading(true);
    try {
      setChanges(await api.listRelationshipChanges(projectId));
    } catch (e: any) {
      showError("加载关系变更失败：" + e.message);
    } finally {
      setLoading(false);
    }
  }, [projectId, showError]);

  useEffect(() => {
    void load();
  }, [load]);

  return (
    <div className="p-4">
      {loading ? (
        <div className="flex items-center justify-center py-16 text-muted">
          <Loader2 className="h-4 w-4 animate-spin mr-2" /> 加载中…
        </div>
      ) : changes.length === 0 ? (
        <div className="flex h-full items-center justify-center py-16 text-sm text-muted">暂无关系变更记录</div>
      ) : (
        <div className="space-y-2">
          {changes.map((c) => (
            <div key={c.id} className="rounded-lg border border-border bg-surface-elevated p-3">
              <div className="flex flex-wrap items-center gap-2 text-sm">
                <span className="font-medium text-foreground">{c.source_id}</span>
                <span className="text-muted">→</span>
                <span className="font-medium text-foreground">{c.target_id}</span>
                <Badge variant="primary">{RELATION_FIELD_LABELS[c.field] ?? c.field}</Badge>
                <span className="text-xs text-muted">第{c.chapter}章</span>
              </div>
              <div className="mt-1 text-xs text-muted whitespace-pre-wrap">
                {c.old_value ? `原值：${c.old_value}` : "（无原值）"} → {c.new_value || "（清空）"}
              </div>
              {c.reason && <div className="mt-1 text-xs text-muted">原因：{c.reason}</div>}
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

// ==================== 世界状态 / 事件（只读） ====================

function formatPayload(payload: unknown): string {
  if (!payload) return "";
  if (typeof payload === "string") return payload;
  try {
    return JSON.stringify(payload, null, 1);
  } catch {
    return String(payload);
  }
}

export function StatesEventsView({ projectId }: { projectId: number }) {
  const { showError } = useToast();
  const [states, setStates] = useState<StateChange[]>([]);
  const [events, setEvents] = useState<TruthEvent[]>([]);
  const [loading, setLoading] = useState(false);

  const load = useCallback(async () => {
    if (!projectId) return;
    setLoading(true);
    try {
      const [s, e] = await Promise.all([api.listStates(projectId), api.listEvents(projectId)]);
      setStates(s);
      setEvents(e);
    } catch (err: any) {
      showError("加载世界状态失败：" + err.message);
    } finally {
      setLoading(false);
    }
  }, [projectId, showError]);

  useEffect(() => {
    void load();
  }, [load]);

  const sortedStates = useMemo(() => [...states].sort((a, b) => a.chapter - b.chapter), [states]);
  const sortedEvents = useMemo(
    () => [...events].sort((a, b) => (a.timestamp || "").localeCompare(b.timestamp || "") || a.chapter - b.chapter),
    [events],
  );

  return (
    <div className="p-4">
      {loading ? (
        <div className="flex items-center justify-center py-16 text-muted">
          <Loader2 className="h-4 w-4 animate-spin mr-2" /> 加载中…
        </div>
      ) : sortedStates.length === 0 && sortedEvents.length === 0 ? (
        <div className="flex h-full items-center justify-center py-16 text-sm text-muted">
          暂无世界状态与事件（提交章节后自动生成）
        </div>
      ) : (
        <div className="grid grid-cols-1 gap-4 lg:grid-cols-2">
          {/* 世界状态快照 */}
          <div className="space-y-2">
            <h4 className="text-xs font-semibold uppercase tracking-wide text-muted">
              世界状态快照（{sortedStates.length}）
            </h4>
            {sortedStates.length === 0 ? (
              <div className="text-sm text-muted py-8 text-center">暂无状态变更</div>
            ) : (
              sortedStates.map((s) => (
                <div key={s.id} className="rounded-lg border border-border bg-surface-elevated p-3">
                  <div className="flex flex-wrap items-center gap-2 text-sm">
                    <Badge variant="default">{s.entity_type}</Badge>
                    <span className="font-medium text-foreground">{s.entity_id}</span>
                    <Badge variant="primary">{s.field}</Badge>
                    <span className="text-xs text-muted">第{s.chapter}章</span>
                  </div>
                  <div className="mt-1 text-xs text-muted whitespace-pre-wrap">
                    {s.old_value ? `原值：${s.old_value}` : "（无原值）"} → {s.new_value || "（清空）"}
                  </div>
                </div>
              ))
            )}
          </div>

          {/* 事件流 */}
          <div className="space-y-2">
            <h4 className="text-xs font-semibold uppercase tracking-wide text-muted">
              事件流（{sortedEvents.length}）
            </h4>
            {sortedEvents.length === 0 ? (
              <div className="text-sm text-muted py-8 text-center">暂无事件</div>
            ) : (
              sortedEvents.map((e) => (
                <div key={e.id} className="rounded-lg border border-border bg-surface-elevated p-3">
                  <div className="flex flex-wrap items-center gap-2 text-sm">
                    <Badge className={cn("bg-secondary text-muted")}>{e.event_type}</Badge>
                    <span className="text-xs text-muted">
                      {e.chapter > 0 ? `第${e.chapter}章 · ` : ""}
                      {e.timestamp ? new Date(e.timestamp).toLocaleString() : ""}
                    </span>
                  </div>
                  {e.entity_id && <div className="mt-1 text-xs text-muted">实体：{e.entity_id}</div>}
                  {formatPayload(e.payload) && (
                    <div className="mt-1 text-xs text-muted whitespace-pre-wrap break-words">{formatPayload(e.payload)}</div>
                  )}
                </div>
              ))
            )}
          </div>
        </div>
      )}
    </div>
  );
}
