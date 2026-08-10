import { useEffect, useMemo, useState } from "react";
import { Plus, Pencil, Trash2, Drama } from "lucide-react";
import { api } from "@/api";
import { useAppStore } from "@/store";
import { useToast } from "@/hooks/useToast";
import { useConfirmDialog } from "@/hooks/useConfirmDialog";
import type { Gag, GagCategory } from "@/types";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Textarea } from "@/components/ui/textarea";
import { Select } from "@/components/ui/select";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";

const CATEGORIES: GagCategory[] = ["笑点", "桥段", "彩蛋"];

const CATEGORY_BADGE: Record<GagCategory, string> = {
  笑点: "bg-warning/10 text-warning border border-warning/20",
  桥段: "bg-primary-muted text-primary border border-primary/20",
  彩蛋: "bg-success/10 text-success border border-success/20",
};

const STATUS_OPTIONS = ["待用", "使用中", "已用"];
const STATUS_LABELS: Record<string, string> = {
  待用: "待用",
  使用中: "使用中",
  已用: "已用",
};

const EMPTY_FORM: Partial<Gag> = {
  name: "",
  description: "",
  category: "笑点",
  status: "待用",
  first_chapter: null,
  usage_notes: "",
};

export function GagsView() {
  const store = useAppStore();
  const { showSuccess, showError } = useToast();
  const { confirm: confirmDelete, dialog: deleteDialog } = useConfirmDialog();

  const project = store.currentProject;
  const gags = store.gags;

  const [dialogOpen, setDialogOpen] = useState(false);
  const [editingId, setEditingId] = useState<number | null>(null);
  const [form, setForm] = useState<Partial<Gag>>(EMPTY_FORM);
  const [saving, setSaving] = useState(false);
  const [filterCategory, setFilterCategory] = useState<GagCategory | "all">("all");

  useEffect(() => {
    if (project) {
      store.refreshGags().catch(() => {});
    }
  }, [project?.id]);

  const filteredGags = useMemo(() => {
    if (filterCategory === "all") return gags;
    return gags.filter((g) => g.category === filterCategory);
  }, [gags, filterCategory]);

  const grouped = useMemo(() => {
    const map = new Map<GagCategory, Gag[]>();
    CATEGORIES.forEach((c) => map.set(c, []));
    filteredGags.forEach((g) => {
      const list = map.get(g.category) || [];
      list.push(g);
      map.set(g.category, list);
    });
    return Array.from(map.entries()).filter(([, list]) => list.length > 0);
  }, [filteredGags]);

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

  const openEdit = (g: Gag) => {
    setEditingId(g.id);
    setForm({ ...g });
    setDialogOpen(true);
  };

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!form.name || !form.name.trim()) {
      showError("请填写梗名称");
      return;
    }
    setSaving(true);
    try {
      const payload: Partial<Gag> = {
        name: form.name.trim(),
        description: form.description || "",
        category: form.category || "笑点",
        status: form.status || "待用",
        first_chapter: form.first_chapter ? Number(form.first_chapter) : null,
        usage_notes: form.usage_notes || "",
      };
      if (editingId) {
        await api.updateGag(project.id, editingId, payload);
        showSuccess("梗已保存");
      } else {
        await api.createGag(project.id, payload);
        showSuccess("梗已创建");
      }
      await store.refreshGags();
      setDialogOpen(false);
    } catch (err: any) {
      showError("保存失败：" + (err?.message || "未知错误"));
    } finally {
      setSaving(false);
    }
  };

  const handleDelete = async (g: Gag) => {
    const ok = await confirmDelete({
      title: "删除梗",
      description: `确定删除梗「${g.name}」吗？此操作不可恢复。`,
      confirmText: "删除",
      cancelText: "取消",
      variant: "danger",
    });
    if (!ok) return;
    try {
      await api.deleteGag(project.id, g.id);
      await store.refreshGags();
      showSuccess("已删除");
    } catch (err: any) {
      showError("删除失败：" + (err?.message || "未知错误"));
    }
  };

  return (
    <div className="flex-1 flex flex-col gap-3 min-h-0 overflow-hidden">
      <Card>
        <CardHeader>
          <div className="flex items-center justify-between gap-3 flex-wrap">
            <CardTitle className="flex items-center gap-2">
              <Drama className="h-4 w-4 text-primary" />
              梗管理
            </CardTitle>
            <div className="flex items-center gap-2">
              <Select
                value={filterCategory}
                onChange={(e) => setFilterCategory(e.target.value as GagCategory | "all")}
                className="h-8 w-32 text-xs"
              >
                <option value="all">全部分类</option>
                {CATEGORIES.map((c) => (
                  <option key={c} value={c}>{c}</option>
                ))}
              </Select>
              <Button size="sm" onClick={openCreate}>
                <Plus className="h-3.5 w-3.5 mr-1" /> 新建梗
              </Button>
            </div>
          </div>
        </CardHeader>
      </Card>

      <div className="flex-1 overflow-y-auto space-y-4 pr-1">
        {grouped.length === 0 && (
          <div className="text-center text-sm text-muted py-10">
            暂无梗，点击右上角新建。按分类管理笑点、桥段和彩蛋。
          </div>
        )}
        {grouped.map(([category, list]) => (
          <div key={category} className="space-y-2">
            <div className="flex items-center gap-2">
              <Badge className={CATEGORY_BADGE[category]}>{category}</Badge>
              <span className="text-xs text-muted">{list.length} 条</span>
            </div>
            <div className="space-y-2">
              {list.map((g) => (
                <Card key={g.id}>
                  <CardContent className="p-3 space-y-2">
                    <div className="flex items-start justify-between gap-2">
                      <div className="flex items-center gap-2 flex-wrap">
                        <h4 className="font-medium text-foreground">{g.name}</h4>
                        <Badge className={CATEGORY_BADGE[g.category]}>{g.category}</Badge>
                        {g.status && (
                          <Badge>{STATUS_LABELS[g.status] || g.status}</Badge>
                        )}
                      </div>
                      <div className="flex items-center gap-1 shrink-0">
                        <button onClick={() => openEdit(g)} className="p-1 hover:bg-foreground/5 rounded" aria-label="编辑">
                          <Pencil className="h-3.5 w-3.5 text-muted" />
                        </button>
                        <button onClick={() => handleDelete(g)} className="p-1 hover:bg-foreground/5 rounded" aria-label="删除">
                          <Trash2 className="h-3.5 w-3.5 text-danger" />
                        </button>
                      </div>
                    </div>
                    {g.description && (
                      <p className="text-sm text-muted whitespace-pre-wrap line-clamp-3">{g.description}</p>
                    )}
                    <div className="flex flex-wrap gap-3 text-xs text-muted">
                      {g.first_chapter != null && (
                        <span>首次出现：第 {g.first_chapter} 章</span>
                      )}
                      {g.usage_notes && <span>备注：{g.usage_notes}</span>}
                    </div>
                  </CardContent>
                </Card>
              ))}
            </div>
          </div>
        ))}
      </div>

      <Dialog open={dialogOpen} onOpenChange={setDialogOpen}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>{editingId ? "编辑梗" : "新建梗"}</DialogTitle>
          </DialogHeader>
          <form onSubmit={handleSubmit} className="space-y-3">
            <div className="space-y-1.5">
              <span className="text-sm font-medium">名称</span>
              <Input
                placeholder="如：主角的口头禅"
                value={form.name || ""}
                onChange={(e) => setForm({ ...form, name: e.target.value })}
                autoFocus
              />
            </div>
            <div className="grid grid-cols-2 gap-3">
              <div className="space-y-1.5">
                <span className="text-sm font-medium">分类</span>
                <Select
                  value={form.category || "笑点"}
                  onChange={(e) => setForm({ ...form, category: e.target.value as GagCategory })}
                >
                  {CATEGORIES.map((c) => (
                    <option key={c} value={c}>{c}</option>
                  ))}
                </Select>
              </div>
              <div className="space-y-1.5">
                <span className="text-sm font-medium">状态</span>
                <Select
                  value={form.status || "待用"}
                  onChange={(e) => setForm({ ...form, status: e.target.value })}
                >
                  {STATUS_OPTIONS.map((s) => (
                    <option key={s} value={s}>{STATUS_LABELS[s]}</option>
                  ))}
                </Select>
              </div>
            </div>
            <div className="space-y-1.5">
              <span className="text-sm font-medium">描述</span>
              <Textarea
                placeholder="梗的具体内容、表现形式…"
                value={form.description || ""}
                onChange={(e) => setForm({ ...form, description: e.target.value })}
                rows={3}
              />
            </div>
            <div className="space-y-1.5">
              <span className="text-sm font-medium">首次出现章节（可选）</span>
              <Input
                type="number"
                min={0}
                placeholder="如：5"
                value={form.first_chapter ?? ""}
                onChange={(e) => setForm({ ...form, first_chapter: e.target.value ? Number(e.target.value) : null })}
              />
            </div>
            <div className="space-y-1.5">
              <span className="text-sm font-medium">使用备注（可选）</span>
              <Textarea
                placeholder="使用场景、节奏、注意事项…"
                value={form.usage_notes || ""}
                onChange={(e) => setForm({ ...form, usage_notes: e.target.value })}
                rows={2}
              />
            </div>
            <div className="flex justify-end gap-2 pt-1">
              <Button type="button" variant="outline" onClick={() => setDialogOpen(false)} disabled={saving}>
                取消
              </Button>
              <Button type="submit" variant="primary" disabled={saving || !form.name?.trim()}>
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
