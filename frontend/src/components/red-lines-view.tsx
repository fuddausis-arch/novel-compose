import { useEffect, useState } from "react";
import { Plus, Pencil, Trash2, ShieldAlert } from "lucide-react";
import { api } from "@/api";
import { useAppStore } from "@/store";
import { useToast } from "@/hooks/useToast";
import { useConfirmDialog } from "@/hooks/useConfirmDialog";
import type { RedLine } from "@/types";
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

const SCOPES: RedLine["scope"][] = ["project", "chapter"];
const SEVERITIES: RedLine["severity"][] = ["hard", "soft"];

const SCOPE_LABELS: Record<RedLine["scope"], string> = {
  project: "项目级",
  chapter: "章级",
};

const SEVERITY_LABELS: Record<RedLine["severity"], string> = {
  hard: "硬性",
  soft: "软性",
};

const SEVERITY_BADGE: Record<RedLine["severity"], string> = {
  hard: "bg-danger/10 text-danger border border-danger/20",
  soft: "bg-warning/10 text-warning border border-warning/20",
};

const SCOPE_BADGE = "bg-primary-muted text-primary border border-primary/20";

const EMPTY_FORM: Partial<RedLine> = {
  content: "",
  scope: "project",
  chapter_num: null,
  severity: "hard",
};

export function RedLinesView() {
  const store = useAppStore();
  const { showSuccess, showError } = useToast();
  const { confirm: confirmDelete, dialog: deleteDialog } = useConfirmDialog();

  const project = store.currentProject;
  const redLines = store.redLines;

  const [dialogOpen, setDialogOpen] = useState(false);
  const [editingId, setEditingId] = useState<number | null>(null);
  const [form, setForm] = useState<Partial<RedLine>>(EMPTY_FORM);
  const [saving, setSaving] = useState(false);

  useEffect(() => {
    if (project) {
      store.refreshRedLines().catch(() => {});
    }
  }, [project?.id]);

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

  const openEdit = (r: RedLine) => {
    setEditingId(r.id);
    setForm({ ...r });
    setDialogOpen(true);
  };

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!form.content || !form.content.trim()) {
      showError("请填写红线内容");
      return;
    }
    if (form.scope === "chapter" && (!form.chapter_num || Number(form.chapter_num) <= 0)) {
      showError("章级红线需要填写有效章节号");
      return;
    }
    setSaving(true);
    try {
      const payload: Partial<RedLine> = {
        content: form.content.trim(),
        scope: form.scope || "project",
        severity: form.severity || "hard",
        chapter_num: form.scope === "chapter" ? Number(form.chapter_num) : null,
      };
      if (editingId) {
        await api.updateRedLine(project.id, editingId, payload);
        showSuccess("红线已保存");
      } else {
        await api.createRedLine(project.id, payload);
        showSuccess("红线已创建");
      }
      await store.refreshRedLines();
      setDialogOpen(false);
    } catch (err: any) {
      showError("保存失败：" + (err?.message || "未知错误"));
    } finally {
      setSaving(false);
    }
  };

  const handleDelete = async (r: RedLine) => {
    const ok = await confirmDelete({
      title: "删除红线",
      description: `确定删除这条红线吗？此操作不可恢复。`,
      confirmText: "删除",
      cancelText: "取消",
      variant: "danger",
    });
    if (!ok) return;
    try {
      await api.deleteRedLine(project.id, r.id);
      await store.refreshRedLines();
      showSuccess("已删除");
    } catch (err: any) {
      showError("删除失败：" + (err?.message || "未知错误"));
    }
  };

  const projectLines = redLines.filter((r) => r.scope === "project");
  const chapterLines = redLines.filter((r) => r.scope === "chapter");

  const renderCard = (r: RedLine) => (
    <Card key={r.id}>
      <CardContent className="p-3 space-y-2">
        <div className="flex items-start justify-between gap-2">
          <div className="flex items-center gap-2 flex-wrap">
            <Badge className={SEVERITY_BADGE[r.severity]}>
              {SEVERITY_LABELS[r.severity]}
            </Badge>
            <Badge className={SCOPE_BADGE}>{SCOPE_LABELS[r.scope]}</Badge>
            {r.scope === "chapter" && r.chapter_num && (
              <span className="text-xs text-muted">第 {r.chapter_num} 章</span>
            )}
          </div>
          <div className="flex items-center gap-1 shrink-0">
            <button onClick={() => openEdit(r)} className="p-1 hover:bg-foreground/5 rounded" aria-label="编辑">
              <Pencil className="h-3.5 w-3.5 text-muted" />
            </button>
            <button onClick={() => handleDelete(r)} className="p-1 hover:bg-foreground/5 rounded" aria-label="删除">
              <Trash2 className="h-3.5 w-3.5 text-danger" />
            </button>
          </div>
        </div>
        {r.content && (
          <p className="text-sm text-foreground whitespace-pre-wrap">{r.content}</p>
        )}
      </CardContent>
    </Card>
  );

  return (
    <div className="flex-1 flex flex-col gap-3 min-h-0 overflow-hidden">
      <Card>
        <CardHeader>
          <div className="flex items-center justify-between">
            <CardTitle className="flex items-center gap-2">
              <ShieldAlert className="h-4 w-4 text-danger" />
              红线管理
            </CardTitle>
            <Button size="sm" onClick={openCreate}>
              <Plus className="h-3.5 w-3.5 mr-1" /> 新建红线
            </Button>
          </div>
        </CardHeader>
      </Card>

      <div className="flex-1 overflow-y-auto space-y-4 pr-1">
        <div className="space-y-2">
          <div className="text-xs font-semibold text-muted uppercase tracking-wide">项目级红线</div>
          {projectLines.length === 0 ? (
            <div className="text-center text-sm text-muted py-6">暂无项目级红线</div>
          ) : (
            <div className="space-y-2">{projectLines.map(renderCard)}</div>
          )}
        </div>

        <div className="space-y-2">
          <div className="text-xs font-semibold text-muted uppercase tracking-wide">章级红线</div>
          {chapterLines.length === 0 ? (
            <div className="text-center text-sm text-muted py-6">暂无章级红线</div>
          ) : (
            <div className="space-y-2">{chapterLines.map(renderCard)}</div>
          )}
        </div>

        {redLines.length === 0 && (
          <div className="text-center text-sm text-muted py-10">
            暂无红线，点击右上角新建。硬性红线（红色）不可违反，软性红线（黄色）需谨慎处理。
          </div>
        )}
      </div>

      <Dialog open={dialogOpen} onOpenChange={setDialogOpen}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>{editingId ? "编辑红线" : "新建红线"}</DialogTitle>
          </DialogHeader>
          <form onSubmit={handleSubmit} className="space-y-3">
            <div className="space-y-1.5">
              <span className="text-sm font-medium">内容</span>
              <Textarea
                placeholder="描述不可违反的红线，如：主角绝不滥杀无辜"
                value={form.content || ""}
                onChange={(e) => setForm({ ...form, content: e.target.value })}
                rows={3}
                autoFocus
              />
            </div>
            <div className="grid grid-cols-2 gap-3">
              <div className="space-y-1.5">
                <span className="text-sm font-medium">范围</span>
                <Select
                  value={form.scope || "project"}
                  onChange={(e) => setForm({ ...form, scope: e.target.value as RedLine["scope"] })}
                >
                  {SCOPES.map((s) => (
                    <option key={s} value={s}>{SCOPE_LABELS[s]}</option>
                  ))}
                </Select>
              </div>
              <div className="space-y-1.5">
                <span className="text-sm font-medium">严重程度</span>
                <Select
                  value={form.severity || "hard"}
                  onChange={(e) => setForm({ ...form, severity: e.target.value as RedLine["severity"] })}
                >
                  {SEVERITIES.map((s) => (
                    <option key={s} value={s}>{SEVERITY_LABELS[s]}</option>
                  ))}
                </Select>
              </div>
            </div>
            {form.scope === "chapter" && (
              <div className="space-y-1.5">
                <span className="text-sm font-medium">章节号</span>
                <Input
                  type="number"
                  min={1}
                  placeholder="如：12"
                  value={form.chapter_num ?? ""}
                  onChange={(e) => setForm({ ...form, chapter_num: Number(e.target.value) })}
                />
              </div>
            )}
            <div className="flex justify-end gap-2 pt-1">
              <Button type="button" variant="outline" onClick={() => setDialogOpen(false)} disabled={saving}>
                取消
              </Button>
              <Button type="submit" variant="primary" disabled={saving || !form.content?.trim()}>
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
