import { useState } from "react";
import { Plus, Pencil, Trash2, Lightbulb } from "lucide-react";
import { api } from "@/api";
import { useAppStore } from "@/store";
import { useToast } from "@/hooks/useToast";
import { useConfirmDialog } from "@/hooks/useConfirmDialog";
import type { Foreshadow } from "@/types";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Textarea } from "@/components/ui/textarea";
import { Select } from "@/components/ui/select";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { TagWeightFields } from "@/components/ui/tag-weight-fields";
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";

const TIERS = ["primary", "secondary", "tertiary"];
const STATUSES = ["planted", "resolved", "abandoned"];

const TIER_LABELS: Record<string, string> = {
  primary: "主线",
  secondary: "支线",
  tertiary: "细节",
};

const STATUS_LABELS: Record<string, string> = {
  planted: "已埋下",
  resolved: "已回收",
  abandoned: "已废弃",
};

const TIER_BADGE: Record<string, string> = {
  primary: "text-primary border-primary",
  secondary: "text-muted border-border-strong",
  tertiary: "text-muted border-border-strong",
};

const STATUS_BADGE: Record<string, string> = {
  planted: "text-warning border-warning",
  resolved: "text-success border-success",
  abandoned: "text-muted border-border-strong",
};

export interface ForeshadowsViewProps {
  onSelectAsset?: (type: string, id: string) => void;
}

const EMPTY_FORM: Partial<Foreshadow> = {
  foreshadow_id: "",
  tier: "secondary",
  status: "planted",
  description: "",
  plant_chapter: 1,
  planned_resolve_chapter: 1,
  depends_on: "",
};

export function ForeshadowsView(_: ForeshadowsViewProps) {
  const store = useAppStore();
  const { showSuccess, showError } = useToast();
  const { confirm: confirmDelete, dialog: deleteDialog } = useConfirmDialog();

  const project = store.currentProject;
  const foreshadows = store.foreshadows;

  const [dialogOpen, setDialogOpen] = useState(false);
  const [editingId, setEditingId] = useState<string | null>(null);
  const [form, setForm] = useState<Partial<Foreshadow>>(EMPTY_FORM);
  const [saving, setSaving] = useState(false);

  if (!project) {
    return (
      <div className="flex-1 flex items-center justify-center text-muted text-sm">
        请先选择或创建一个项目
      </div>
    );
  }

  const openCreate = () => {
    setEditingId(null);
    setForm({ ...EMPTY_FORM });
    setDialogOpen(true);
  };

  const openEdit = (f: Foreshadow) => {
    setEditingId(f.foreshadow_id);
    setForm({ ...f });
    setDialogOpen(true);
  };

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!form.foreshadow_id || !form.foreshadow_id.trim()) {
      showError("请填写伏笔标识");
      return;
    }
    setSaving(true);
    try {
      const payload: Partial<Foreshadow> = {
        foreshadow_id: form.foreshadow_id.trim(),
        tier: form.tier || "secondary",
        status: form.status || "planted",
        description: form.description || "",
        plant_chapter: Number(form.plant_chapter) || 0,
        planned_resolve_chapter: Number(form.planned_resolve_chapter) || 0,
        depends_on: form.depends_on || "",
      };
      if (editingId) {
        await api.updateForeshadow(project.id, editingId, payload);
        showSuccess("伏笔已保存");
      } else {
        await api.createForeshadow(project.id, payload);
        showSuccess("伏笔已创建");
      }
      await store.refreshForeshadows();
      setDialogOpen(false);
    } catch (err: any) {
      showError("保存失败：" + (err?.message || "未知错误"));
    } finally {
      setSaving(false);
    }
  };

  const handleDelete = async (f: Foreshadow) => {
    const ok = await confirmDelete({
      title: "删除伏笔",
      description: `确定删除伏笔「${f.foreshadow_id}」吗？此操作不可恢复。`,
      confirmText: "删除",
      cancelText: "取消",
      variant: "danger",
    });
    if (!ok) return;
    try {
      await api.deleteForeshadow(project.id, f.foreshadow_id);
      await store.refreshForeshadows();
      showSuccess("已删除");
    } catch (err: any) {
      showError("删除失败：" + (err?.message || "未知错误"));
    }
  };

  return (
    <div className="flex-1 flex flex-col gap-3 min-h-0 overflow-hidden">
      <Card>
        <CardHeader>
          <div className="flex items-center justify-between">
            <CardTitle className="flex items-center gap-2">
              <Lightbulb className="h-4 w-4 text-primary" />
              伏笔
            </CardTitle>
            <Button size="sm" onClick={openCreate}>
              <Plus className="h-3.5 w-3.5 mr-1" /> 新建伏笔
            </Button>
          </div>
        </CardHeader>
      </Card>

      <div className="flex-1 overflow-y-auto space-y-3 pr-1">
        {foreshadows.length === 0 && (
          <div className="text-center text-sm text-muted py-10">暂无伏笔，点击右上角新建。</div>
        )}
        {foreshadows.map((f) => (
          <Card key={f.id}>
            <CardContent className="p-3 space-y-2">
              <div className="flex items-start justify-between gap-2">
                <div className="flex items-center gap-2 flex-wrap">
                  <h4 className="font-medium text-foreground">{f.foreshadow_id}</h4>
                  {f.tier && <Badge className={TIER_BADGE[f.tier] || ""}>{TIER_LABELS[f.tier] || f.tier}</Badge>}
                  {f.status && <Badge className={STATUS_BADGE[f.status] || ""}>{STATUS_LABELS[f.status] || f.status}</Badge>}
                </div>
                <div className="flex items-center gap-1 shrink-0">
                  <button onClick={() => openEdit(f)} className="p-1 hover:bg-foreground/5 rounded" aria-label="编辑">
                    <Pencil className="h-3.5 w-3.5 text-muted" />
                  </button>
                  <button onClick={() => handleDelete(f)} className="p-1 hover:bg-foreground/5 rounded" aria-label="删除">
                    <Trash2 className="h-3.5 w-3.5 text-danger" />
                  </button>
                </div>
              </div>
              {f.description && (
                <p className="text-sm text-muted whitespace-pre-wrap line-clamp-3">{f.description}</p>
              )}
              <div className="flex flex-wrap gap-3 text-xs text-muted">
                <span>埋下：第{f.plant_chapter}章</span>
                <span>计划回收：第{f.planned_resolve_chapter}章</span>
                {f.depends_on && <span>依赖：{f.depends_on}</span>}
                {f.tags && f.tags.length > 0 && <span>标签：{f.tags.join("、")}</span>}
                {f.weight !== undefined && <span>权重：{f.weight}</span>}
              </div>
            </CardContent>
          </Card>
        ))}
      </div>

      <Dialog open={dialogOpen} onOpenChange={setDialogOpen}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>{editingId ? "编辑伏笔" : "新建伏笔"}</DialogTitle>
          </DialogHeader>
          <form onSubmit={handleSubmit} className="space-y-3">
            <div className="space-y-1.5">
              <span className="text-sm font-medium">伏笔标识</span>
              <Input
                placeholder="如：神秘玉佩的来历"
                value={form.foreshadow_id || ""}
                onChange={(e) => setForm({ ...form, foreshadow_id: e.target.value })}
                autoFocus
              />
            </div>
            <div className="grid grid-cols-2 gap-3">
              <div className="space-y-1.5">
                <span className="text-sm font-medium">层级</span>
                <Select value={form.tier || "secondary"} onChange={(e) => setForm({ ...form, tier: e.target.value })}>
                  {TIERS.map((t) => (
                    <option key={t} value={t}>{TIER_LABELS[t]}</option>
                  ))}
                </Select>
              </div>
              <div className="space-y-1.5">
                <span className="text-sm font-medium">状态</span>
                <Select value={form.status || "planted"} onChange={(e) => setForm({ ...form, status: e.target.value })}>
                  {STATUSES.map((s) => (
                    <option key={s} value={s}>{STATUS_LABELS[s]}</option>
                  ))}
                </Select>
              </div>
            </div>
            <div className="space-y-1.5">
              <span className="text-sm font-medium">描述</span>
              <Textarea
                placeholder="伏笔内容与意图…"
                value={form.description || ""}
                onChange={(e) => setForm({ ...form, description: e.target.value })}
                rows={3}
              />
            </div>
            <div className="grid grid-cols-2 gap-3">
              <div className="space-y-1.5">
                <span className="text-sm font-medium">埋下章节</span>
                <Input
                  type="number"
                  value={form.plant_chapter ?? ""}
                  onChange={(e) => setForm({ ...form, plant_chapter: Number(e.target.value) })}
                />
              </div>
              <div className="space-y-1.5">
                <span className="text-sm font-medium">计划回收章节</span>
                <Input
                  type="number"
                  value={form.planned_resolve_chapter ?? ""}
                  onChange={(e) => setForm({ ...form, planned_resolve_chapter: Number(e.target.value) })}
                />
              </div>
            </div>
            <div className="space-y-1.5">
              <span className="text-sm font-medium">依赖（可选）</span>
              <Input
                placeholder="依赖的其他伏笔或事件"
                value={form.depends_on || ""}
                onChange={(e) => setForm({ ...form, depends_on: e.target.value })}
              />
            </div>
            <TagWeightFields
              tags={(form.tags || []) as string[]}
              weight={form.weight ?? 50}
              onTags={(t) => setForm({ ...form, tags: t })}
              onWeight={(w) => setForm({ ...form, weight: w })}
            />
            <div className="flex justify-end gap-2 pt-1">
              <Button type="button" variant="outline" onClick={() => setDialogOpen(false)} disabled={saving}>
                取消
              </Button>
              <Button type="submit" variant="primary" disabled={saving || !form.foreshadow_id?.trim()}>
                {saving ? "保存中…" : "保存"}
              </Button>
            </div>
          </form>
        </DialogContent>
      </Dialog>

      {deleteDialog}
    </div>
  );
}
