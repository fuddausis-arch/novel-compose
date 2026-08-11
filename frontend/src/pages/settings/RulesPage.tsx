/** 全局设置 · Rules 管理页：列表 + 详情，支持创建/编辑/删除/启停/冲突检测 */
import { useCallback, useEffect, useMemo, useState, type ReactNode } from "react";
import { AlertTriangle, Loader2, Pencil, Plus, RefreshCw, ScrollText, Search, Trash2 } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Textarea } from "@/components/ui/textarea";
import { EmptyState } from "@/components/ui/empty-state";
import { SettingToggleRow } from "@/components/ui/setting-toggle-row";
import { Dialog, DialogContent, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { cn } from "@/lib/utils";
import { useToast } from "@/hooks/useToast";
import { useConfirmDialog } from "@/hooks/useConfirmDialog";

interface RuleSummary {
  id: string;
  name: string;
  description: string;
  group: string;
  enabled: boolean;
  rule_text?: string;
  priority?: number;
}

interface RuleDetail {
  id: string;
  name: string;
  description: string;
  rule_text: string;
  group: string;
  priority: number;
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

/** 创建/编辑弹窗 */
function RuleEditorDialog({
  open,
  initial,
  onClose,
  onSave,
  saving,
}: {
  open: boolean;
  initial: RuleDetail | null;
  onClose: () => void;
  onSave: (data: { name: string; description: string; rule_text: string; group: string; priority: number; enabled: boolean }) => void;
  saving: boolean;
}) {
  const isEdit = !!initial;
  const [name, setName] = useState("");
  const [description, setDescription] = useState("");
  const [ruleText, setRuleText] = useState("");
  const [group, setGroup] = useState("default");
  const [priority, setPriority] = useState(0);
  const [enabled, setEnabled] = useState(true);

  useEffect(() => {
    if (open) {
      setName(initial?.name ?? "");
      setDescription(initial?.description ?? "");
      setRuleText(initial?.rule_text ?? "");
      setGroup(initial?.group ?? "default");
      setPriority(initial?.priority ?? 0);
      setEnabled(initial?.enabled ?? true);
    }
  }, [open, initial]);

  const canSave = name.trim() && ruleText.trim() && !saving;

  return (
    <Dialog open={open} onOpenChange={(o) => !o && onClose()}>
      <DialogContent className="max-h-[90vh] max-w-2xl overflow-y-auto">
        <DialogHeader>
          <DialogTitle>{isEdit ? "编辑规则" : "新建规则"}</DialogTitle>
        </DialogHeader>
        <div className="space-y-4">
          <div>
            <Label htmlFor="rule-name">名称</Label>
            <Input id="rule-name" value={name} onChange={(e) => setName(e.target.value)} placeholder="规则的唯一名称" className="mt-1" />
          </div>
          <div>
            <Label htmlFor="rule-desc">描述</Label>
            <Input id="rule-desc" value={description} onChange={(e) => setDescription(e.target.value)} placeholder="简短说明规则用途" className="mt-1" />
          </div>
          <div className="grid grid-cols-2 gap-4">
            <div>
              <Label htmlFor="rule-group">分组</Label>
              <Input id="rule-group" value={group} onChange={(e) => setGroup(e.target.value)} placeholder="如 default / writing / audit" className="mt-1 font-mono" />
            </div>
            <div>
              <Label htmlFor="rule-priority">优先级（数字越大越优先）</Label>
              <Input
                id="rule-priority"
                type="number"
                value={priority}
                onChange={(e) => setPriority(Number(e.target.value) || 0)}
                className="mt-1"
              />
            </div>
          </div>
          <div>
            <Label htmlFor="rule-text">规则内容</Label>
            <Textarea
              id="rule-text"
              value={ruleText}
              onChange={(e) => setRuleText(e.target.value)}
              rows={8}
              placeholder="规则的 prompt 文本，会注入到 system prompt 的 <rules> 标签中"
              className="mt-1 font-mono text-xs"
            />
          </div>
          <SettingToggleRow label="启用" description="启用后注入到 system prompt" checked={enabled} onChange={setEnabled} />
        </div>
        <div className="mt-6 flex justify-end gap-2">
          <Button variant="outline" size="sm" onClick={onClose} disabled={saving}>
            取消
          </Button>
          <Button
            variant="default"
            size="sm"
            onClick={() => canSave && onSave({ name: name.trim(), description, rule_text: ruleText, group, priority, enabled })}
            disabled={!canSave}
          >
            {saving ? <Loader2 className="mr-1 h-4 w-4 animate-spin" /> : null}
            {isEdit ? "保存" : "创建"}
          </Button>
        </div>
      </DialogContent>
    </Dialog>
  );
}

export default function RulesPage() {
  const { showError, showSuccess } = useToast();
  const { confirm: confirmDelete, dialog: deleteDialog } = useConfirmDialog();
  const [rules, setRules] = useState<RuleSummary[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [search, setSearch] = useState("");
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [detail, setDetail] = useState<RuleDetail | null>(null);
  const [reloading, setReloading] = useState(false);
  const [conflicts, setConflicts] = useState<number>(0);

  // 弹窗状态
  const [editorOpen, setEditorOpen] = useState(false);
  const [editorInitial, setEditorInitial] = useState<RuleDetail | null>(null);
  const [editorSaving, setEditorSaving] = useState(false);

  const load = useCallback(async (silent = false) => {
    // silent=true：静默刷新（保存/删除/启停后用），不切换 loading，保持滚动容器常驻不跳顶
    if (!silent) setLoading(true);
    setError(null);
    try {
      const data = await fetchJson<{ rules: RuleSummary[] }>("/api/rules");
      setRules((data.rules || []).map((r) => ({ ...r, id: r.id || r.name })));
      // 顺便检测冲突
      try {
        const c = await fetchJson<{ conflicts: unknown[]; total: number }>("/api/rules/conflicts");
        setConflicts(c.total ?? 0);
      } catch {
        setConflicts(0);
      }
    } catch (e) {
      setError(e instanceof Error ? e.message : "加载失败");
      setRules([]);
    } finally {
      if (!silent) setLoading(false);
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  useEffect(() => {
    if (!selectedId) {
      setDetail(null);
      return;
    }
    const found = rules.find((r) => r.id === selectedId);
    setDetail(
      found
        ? {
            id: found.id,
            name: found.name,
            description: found.description ?? "",
            rule_text: found.rule_text ?? "",
            group: found.group ?? "default",
            priority: found.priority ?? 0,
            enabled: found.enabled ?? true,
          }
        : null,
    );
  }, [selectedId, rules]);

  const handleReload = async () => {
    setReloading(true);
    try {
      await load();
      showSuccess("已重新加载");
    } catch (e) {
      showError(e instanceof Error ? e.message : "重新加载失败");
    } finally {
      setReloading(false);
    }
  };

  // ---- 创建/编辑 ----
  const openCreate = () => {
    setEditorInitial(null);
    setEditorOpen(true);
  };

  const openEdit = () => {
    if (!detail) return;
    setEditorInitial(detail);
    setEditorOpen(true);
  };

  const handleSave = async (data: { name: string; description: string; rule_text: string; group: string; priority: number; enabled: boolean }) => {
    setEditorSaving(true);
    try {
      const isEdit = !!editorInitial;
      if (isEdit) {
        await fetchJson(`/api/rules/${encodeURIComponent(editorInitial.id)}`, {
          method: "PUT",
          body: JSON.stringify(data),
        });
        showSuccess("已保存");
      } else {
        await fetchJson("/api/rules", {
          method: "POST",
          body: JSON.stringify(data),
        });
        showSuccess("已创建");
      }
      setEditorOpen(false);
      await load(true);
    } catch (e) {
      showError(e instanceof Error ? e.message : "保存失败");
    } finally {
      setEditorSaving(false);
    }
  };

  // ---- 删除 ----
  const openDelete = async (id: string, name: string) => {
    const ok = await confirmDelete({
      title: "删除规则",
      description: `确定要删除规则 ${name} 吗？此操作不可撤销。`,
      confirmText: "确认删除",
      cancelText: "取消",
      variant: "danger",
    });
    if (!ok) return;
    try {
      await fetchJson(`/api/rules/${encodeURIComponent(id)}`, { method: "DELETE" });
      showSuccess(`已删除 ${name}`);
      if (selectedId === id) {
        setSelectedId(null);
        setDetail(null);
      }
      await load(true);
    } catch (e) {
      showError(e instanceof Error ? e.message : "删除失败");
    }
  };

  // ---- 启停 ----
  const handleToggle = async (value: boolean) => {
    if (!detail) return;
    const prev = detail;
    setDetail({ ...prev, enabled: value });
    setRules((rs) => rs.map((r) => (r.id === detail.id ? { ...r, enabled: value } : r)));
    try {
      await fetchJson(`/api/rules/${encodeURIComponent(detail.id)}`, {
        method: "PUT",
        body: JSON.stringify({ enabled: value }),
      });
      showSuccess(value ? "已启用" : "已禁用");
      await load(true);
    } catch (e) {
      setDetail(prev);
      setRules((rs) => rs.map((r) => (r.id === prev.id ? { ...r, enabled: prev.enabled } : r)));
      showError(e instanceof Error ? e.message : "切换失败");
    }
  };

  const filtered = useMemo(() => {
    const kw = search.trim().toLowerCase();
    if (!kw) return rules;
    return rules.filter(
      (r) =>
        r.name.toLowerCase().includes(kw) ||
        r.description.toLowerCase().includes(kw) ||
        r.group.toLowerCase().includes(kw),
    );
  }, [rules, search]);

  const enabledCount = rules.filter((r) => r.enabled).length;

  const header = (
    <div className="flex flex-col gap-4 sm:flex-row sm:items-center sm:justify-between">
      <div className="flex items-center gap-3">
        <div className="rounded-lg border border-border bg-primary-muted p-2 text-primary">
          <ScrollText className="h-5 w-5" />
        </div>
        <div>
          <h2 className="text-lg font-semibold">Rules 管理</h2>
          <p className="text-sm text-muted">管理注入 system prompt 的创作规则</p>
        </div>
      </div>
      <div className="flex gap-2">
        <Button variant="default" size="sm" onClick={openCreate}>
          <Plus className="h-4 w-4" />
          新建规则
        </Button>
        <Button variant="outline" size="sm" onClick={() => void handleReload()} disabled={reloading}>
          <RefreshCw className={cn("h-4 w-4", reloading && "animate-spin")} />
          重新加载
        </Button>
      </div>
    </div>
  );

  const stats = (
    <div className="grid grid-cols-4 gap-4">
      <Card className="p-4">
        <div className="text-xs text-muted">总计</div>
        <div className="mt-1 text-2xl font-bold tabular-nums">{rules.length}</div>
      </Card>
      <Card className="p-4">
        <div className="text-xs text-muted">已启用</div>
        <div className="mt-1 text-2xl font-bold tabular-nums text-success">{enabledCount}</div>
      </Card>
      <Card className="p-4">
        <div className="text-xs text-muted">已禁用</div>
        <div className="mt-1 text-2xl font-bold tabular-nums text-muted">{rules.length - enabledCount}</div>
      </Card>
      <Card className={cn("p-4", conflicts > 0 && "border-destructive")}>
        <div className="flex items-center gap-1 text-xs text-muted">
          {conflicts > 0 && <AlertTriangle className="h-3 w-3 text-destructive" />}
          冲突
        </div>
        <div className={cn("mt-1 text-2xl font-bold tabular-nums", conflicts > 0 ? "text-destructive" : "text-muted")}>
          {conflicts}
        </div>
      </Card>
    </div>
  );

  let body: ReactNode;
  if (loading) {
    body = (
      <div className="flex items-center justify-center py-20">
        <Loader2 className="mr-2 h-5 w-5 animate-spin text-muted" />
        <span className="text-sm text-muted">正在加载 Rules...</span>
      </div>
    );
  } else if (error || rules.length === 0) {
    body = (
      <EmptyState
        icon={<ScrollText className="h-10 w-10 text-muted" />}
        title={error ? "后端 Rules 系统尚未接入" : "暂无规则"}
        description={error ?? "点击「新建规则」创建第一条规则"}
      />
    );
  } else {
    body = (
      <div className="grid gap-4 lg:h-full lg:grid-cols-[320px_1fr]">
        {/* 左：列表（桌面独立滚动） */}
        <div className="space-y-3 lg:h-full lg:overflow-y-auto lg:pr-1">
          <div className="relative">
            <Search className="pointer-events-none absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-muted" />
            <Input
              className="pl-9"
              placeholder="搜索规则..."
              value={search}
              onChange={(e) => setSearch(e.target.value)}
              aria-label="搜索规则"
            />
          </div>
          <div className="space-y-2">
            {filtered.map((r) => (
              <button
                key={r.id}
                type="button"
                onClick={() => setSelectedId(r.id)}
                className={cn(
                  "w-full rounded-lg border p-3 text-left transition-colors",
                  selectedId === r.id
                    ? "border-primary bg-primary-muted"
                    : "border-border bg-surface hover:bg-surface-hover",
                  !r.enabled && "opacity-60",
                )}
              >
                <div className="flex items-center justify-between gap-2">
                  <span className="truncate text-sm font-medium">{r.name}</span>
                  <Badge variant={r.enabled ? "success" : "default"}>{r.enabled ? "启用" : "禁用"}</Badge>
                </div>
                <p className="mt-1 line-clamp-1 text-xs text-muted">{r.description || r.group || "（无描述）"}</p>
              </button>
            ))}
            {filtered.length === 0 && (
              <p className="py-4 text-center text-xs text-muted">未找到匹配的规则</p>
            )}
          </div>
        </div>

        {/* 右：详情（桌面独立滚动） */}
        <Card className="p-5 lg:h-full lg:overflow-y-auto">
          {!selectedId ? (
            <div className="flex min-h-[320px] items-center justify-center text-sm text-muted">
              选择左侧规则查看详情，或点击「新建规则」创建
            </div>
          ) : detail ? (
            <div className="space-y-4">
              <div className="flex flex-wrap items-start justify-between gap-2">
                <div className="min-w-0 flex-1">
                  <div className="flex flex-wrap items-center gap-2">
                    <h3 className="text-base font-semibold">{detail.name}</h3>
                    <Badge variant="primary">{detail.group}</Badge>
                    <Badge variant="default">P{detail.priority}</Badge>
                    <Badge variant={detail.enabled ? "success" : "default"}>
                      {detail.enabled ? "启用" : "禁用"}
                    </Badge>
                  </div>
                  {detail.description && <p className="mt-1 text-sm text-muted">{detail.description}</p>}
                </div>
                <div className="flex shrink-0 gap-1">
                  <Button variant="outline" size="sm" onClick={openEdit}>
                    <Pencil className="h-3.5 w-3.5" />
                    编辑
                  </Button>
                  <Button
                    variant="outline"
                    size="sm"
                    onClick={() => openDelete(detail.id, detail.name)}
                    className="text-destructive hover:bg-destructive/10"
                  >
                    <Trash2 className="h-3.5 w-3.5" />
                    删除
                  </Button>
                </div>
              </div>
              <div>
                <div className="mb-1 text-xs font-medium text-muted">规则内容</div>
                <pre className="max-h-80 overflow-auto whitespace-pre-wrap rounded-lg border border-border bg-background p-3 text-xs text-muted">
                  {detail.rule_text || "（无内容）"}
                </pre>
              </div>
              <div className="border-t border-border pt-4">
                <SettingToggleRow
                  label="启用 / 禁用"
                  description="控制该规则是否注入到 system prompt"
                  checked={detail.enabled}
                  onChange={(v) => void handleToggle(v)}
                />
              </div>
            </div>
          ) : (
            <div className="flex min-h-[320px] items-center justify-center text-sm text-muted">
              加载详情失败
            </div>
          )}
        </Card>
      </div>
    );
  }

  return (
    <div className="flex h-full flex-col overflow-y-auto lg:overflow-hidden">
      <div className="mx-auto w-full max-w-6xl space-y-6 p-6 lg:pb-3">
        {header}
        {stats}
      </div>
      <div className="mx-auto w-full max-w-6xl min-h-0 flex-1 px-6 pb-6">
        {body}
      </div>
      <RuleEditorDialog
        open={editorOpen}
        initial={editorInitial}
        onClose={() => setEditorOpen(false)}
        onSave={handleSave}
        saving={editorSaving}
      />
      {deleteDialog}
    </div>
  );
}
