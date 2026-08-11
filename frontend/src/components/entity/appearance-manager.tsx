/**
 * 出场记录管理：列表展示 + 新增 / 编辑 / 删除。
 * 数据走 /api/bible/{projectId}/entity-appearances（api.listEntityAppearances 等已有封装）。
 * 写操作成功后 bump("bible")，让依赖该数据的页面（百科卡等）自动刷新。
 */
import { useCallback, useEffect, useState } from "react";
import { BookOpen, Check, Loader2, Pencil, Plus, Trash2, X } from "lucide-react";
import { api } from "@/api";
import { bumpDataVersion } from "@/store/slices/dataVersion";
import { useToast } from "@/hooks/useToast";
import type { AppearanceRole, EntityAppearance, EntityType } from "@/types";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Select } from "@/components/ui/select";

const ROLE_OPTIONS: { value: AppearanceRole; label: string }[] = [
  { value: "lead", label: "主角" },
  { value: "participant", label: "参与者" },
  { value: "mention", label: "提及" },
  { value: "background", label: "背景" },
];

interface AppearanceManagerProps {
  projectId: number;
  entityType: EntityType;
  entityId: string;
}

interface FormState {
  chapter: number;
  role_in_chapter: AppearanceRole;
  context_snippet: string;
}

const EMPTY_FORM: FormState = { chapter: 0, role_in_chapter: "mention", context_snippet: "" };

export function AppearanceManager({ projectId, entityType, entityId }: AppearanceManagerProps) {
  const { showSuccess, showError } = useToast();
  const [items, setItems] = useState<EntityAppearance[]>([]);
  const [loading, setLoading] = useState(false);
  const [adding, setAdding] = useState(false);
  const [editingId, setEditingId] = useState<number | null>(null);
  const [form, setForm] = useState<FormState>(EMPTY_FORM);
  const [saving, setSaving] = useState(false);

  const load = useCallback(async (silent = false) => {
    // silent=true：静默刷新（保存/删除后用），不切 loading 保持容器常驻不跳顶
    if (!projectId) return;
    if (!silent) setLoading(true);
    try {
      const data = await api.listEntityAppearances(projectId, { entity_type: entityType, entity_id: entityId });
      setItems(data);
    } catch (e: any) {
      showError("加载出场记录失败：" + e.message);
    } finally {
      if (!silent) setLoading(false);
    }
  }, [projectId, entityType, entityId, showError]);

  useEffect(() => {
    void load();
  }, [load]);

  const openAdd = () => {
    setEditingId(null);
    setForm({ ...EMPTY_FORM, chapter: items.length > 0 ? Math.max(...items.map((i) => i.chapter)) + 1 : 1 });
    setAdding(true);
  };

  const openEdit = (a: EntityAppearance) => {
    setEditingId(a.id);
    setForm({
      chapter: a.chapter,
      role_in_chapter: a.role_in_chapter,
      context_snippet: a.context_snippet || "",
    });
    setAdding(true);
  };

  const cancelForm = () => {
    setAdding(false);
    setEditingId(null);
    setForm(EMPTY_FORM);
  };

  const handleSave = async () => {
    if (!projectId) return;
    if (!form.chapter || form.chapter <= 0) {
      showError("请填写有效的出场章节");
      return;
    }
    setSaving(true);
    try {
      const payload = {
        entity_type: entityType,
        entity_id: entityId,
        chapter: form.chapter,
        role_in_chapter: form.role_in_chapter,
        context_snippet: form.context_snippet,
      };
      if (editingId) {
        await api.updateEntityAppearance(projectId, editingId, payload);
        showSuccess("出场记录已更新");
      } else {
        await api.createEntityAppearance(projectId, payload);
        showSuccess("出场记录已添加");
      }
      cancelForm();
      bumpDataVersion("bible");
      await load(true);
    } catch (e: any) {
      showError("保存失败：" + e.message);
    } finally {
      setSaving(false);
    }
  };

  const handleDelete = async (a: EntityAppearance) => {
    if (!projectId) return;
    try {
      await api.deleteEntityAppearance(projectId, a.id);
      showSuccess("出场记录已删除");
      bumpDataVersion("bible");
      await load(true);
    } catch (e: any) {
      showError("删除失败：" + e.message);
    }
  };

  return (
    <div className="space-y-2">
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-2">
          <BookOpen className="h-4 w-4 text-muted" />
          <h4 className="font-medium text-sm">出场记录{loading ? "" : `（${items.length}）`}</h4>
        </div>
        {!adding && (
          <Button size="sm" variant="ghost" onClick={openAdd}>
            <Plus className="h-3.5 w-3.5 mr-1" /> 添加出场
          </Button>
        )}
      </div>

      {loading ? (
        <div className="flex items-center gap-2 py-3 text-sm text-muted">
          <Loader2 className="h-3.5 w-3.5 animate-spin" /> 加载中…
        </div>
      ) : items.length === 0 && !adding ? (
        <div className="text-sm text-muted">暂无出场记录</div>
      ) : (
        <div className="space-y-2">
          {adding && (
            <div className="space-y-2 rounded-lg border border-border bg-surface/50 p-3">
              <div className="grid grid-cols-1 sm:grid-cols-3 gap-2">
                <Input
                  type="number"
                  min={1}
                  placeholder="章节"
                  value={form.chapter || ""}
                  onChange={(e) => setForm((f) => ({ ...f, chapter: Number(e.target.value) || 0 }))}
                />
                <Select
                  value={form.role_in_chapter}
                  onChange={(e) => setForm((f) => ({ ...f, role_in_chapter: e.target.value as AppearanceRole }))}
                >
                  {ROLE_OPTIONS.map((r) => (
                    <option key={r.value} value={r.value}>{r.label}</option>
                  ))}
                </Select>
                <Input
                  placeholder="上下文（可选）"
                  value={form.context_snippet}
                  onChange={(e) => setForm((f) => ({ ...f, context_snippet: e.target.value }))}
                />
              </div>
              <div className="flex justify-end gap-2">
                <Button size="sm" variant="ghost" onClick={cancelForm} disabled={saving}>
                  <X className="h-3.5 w-3.5 mr-1" /> 取消
                </Button>
                <Button size="sm" variant="primary" onClick={handleSave} disabled={saving}>
                  <Check className="h-3.5 w-3.5 mr-1" /> {saving ? "保存中…" : editingId ? "保存修改" : "添加"}
                </Button>
              </div>
            </div>
          )}
          {items.map((a) => (
            <div key={a.id} className="flex items-center justify-between gap-2 rounded-lg border border-border p-2 text-sm">
              <div className="flex items-center gap-2 min-w-0">
                <Badge variant="primary">第{a.chapter}章</Badge>
                <Badge variant="default">{ROLE_OPTIONS.find((r) => r.value === a.role_in_chapter)?.label ?? a.role_in_chapter}</Badge>
                <span className="text-muted truncate">{a.context_snippet || "无上下文"}</span>
              </div>
              <div className="flex shrink-0 items-center gap-1">
                <button onClick={() => openEdit(a)} className="p-1 hover:bg-foreground/5 rounded" aria-label="编辑出场记录">
                  <Pencil className="h-3.5 w-3.5 text-muted" />
                </button>
                <button onClick={() => handleDelete(a)} className="p-1 hover:bg-foreground/5 rounded" aria-label="删除出场记录">
                  <Trash2 className="h-3.5 w-3.5 text-danger" />
                </button>
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
