import { useEffect, useMemo, useState } from "react";
import { Save, Trash2, Network, Sparkles } from "lucide-react";
import { api } from "@/api";
import { useAppStore } from "@/store";
import { useToast } from "@/hooks/useToast";
import { useConfirmDialog } from "@/hooks/useConfirmDialog";
import type { CharacterRelationship } from "@/types";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Textarea } from "@/components/ui/textarea";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";

interface RelationshipEditorViewProps {
  relationshipId: number;
  onBack?: () => void;
}

const RELATION_TYPES = ["亲情", "友情", "爱情", "师徒", "敌对", "竞争", "同门", "上下级", "同盟", "其他"];
const STATUSES = ["active", "dormant", "resolved", "broken"];

export function RelationshipEditorView({ relationshipId, onBack }: RelationshipEditorViewProps) {
  const store = useAppStore();
  const { showSuccess, showError } = useToast();
  const { confirm: confirmDelete, dialog: deleteDialog } = useConfirmDialog();

  const relationship = useMemo(
    () => store.characterRelationships.find((r) => r.id === relationshipId),
    [store.characterRelationships, relationshipId]
  );

  const [form, setForm] = useState<Partial<CharacterRelationship>>(() => relationship || {});
  const [generating, setGenerating] = useState(false);

  useEffect(() => {
    setForm(relationship || {});
  }, [relationshipId]);

  if (!relationship) {
    return (
      <div className="flex-1 flex items-center justify-center text-muted text-sm">关系不存在或已被删除</div>
    );
  }

  const characterNames = useMemo(
    () => store.characters.map((c) => c.name).filter(Boolean),
    [store.characters]
  );

  const handleAiGenerate = async () => {
    if (!store.currentProject) return;
    setGenerating(true);
    try {
      const created = await api.generateCharacterRelationship(store.currentProject.id, {
        source_character: form.source_character || "",
        target_character: form.target_character || "",
        relation_type_hint: form.relation_type || "",
      });
      setForm({
        ...form,
        source_character: created.source_character,
        target_character: created.target_character,
        relation_type: created.relation_type,
        relation_subtype: created.relation_subtype,
        strength: created.strength,
        description: created.description,
        since_chapter: created.since_chapter,
        status: created.status,
        is_bidirectional: created.is_bidirectional,
      });
      await store.refreshCharacterRelationships();
      showSuccess("AI 已生成关系设定，已填入表单，点击「保存」生效");
    } catch (e: any) {
      showError("AI 生成失败：" + e.message);
    } finally {
      setGenerating(false);
    }
  };

  const handleSave = async () => {
    if (!store.currentProject) return;
    try {
      await api.updateCharacterRelationship(store.currentProject.id, relationshipId, form);
      await store.refreshCharacterRelationships();
      showSuccess("保存成功");
    } catch (e: any) {
      showError("保存失败：" + e.message);
    }
  };

  const handleDelete = async () => {
    if (!store.currentProject) return;
    const confirmed = await confirmDelete({
      title: "删除关系",
      description: "确定删除这条关系吗？此操作不可恢复。",
      confirmText: "删除",
      cancelText: "取消",
      variant: "danger",
    });
    if (!confirmed) return;
    try {
      await api.deleteCharacterRelationship(store.currentProject.id, relationshipId);
      await store.refreshCharacterRelationships();
      showSuccess("删除成功");
      onBack?.();
    } catch (e: any) {
      showError("删除失败：" + e.message);
    }
  };

  return (
    <div className="flex-1 flex flex-col gap-3 min-h-0 overflow-hidden">
      <Card className="flex-1 overflow-y-auto">
        <CardHeader>
          <div className="flex items-center justify-between">
            <CardTitle className="flex items-center gap-2">
              <Network className="h-4 w-4 text-primary" />
              关系编辑
            </CardTitle>
            <div className="flex gap-2">
              <Button size="sm" variant="primary" onClick={handleAiGenerate} disabled={generating}>
                <Sparkles className="h-3.5 w-3.5 mr-1" />
                {generating ? "生成中…" : "AI 生成关系"}
              </Button>
              <Button size="sm" onClick={handleSave}><Save className="h-3.5 w-3.5 mr-1" /> 保存</Button>
              <Button size="sm" variant="danger" onClick={handleDelete}><Trash2 className="h-3.5 w-3.5 mr-1" /> 删除</Button>
            </div>
          </div>
        </CardHeader>
        <CardContent className="space-y-4">
          <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
            <div className="space-y-1">
              <span className="text-xs text-muted">源角色</span>
              <select
                value={form.source_character || ""}
                onChange={(e) => setForm({ ...form, source_character: e.target.value })}
                className="h-10 w-full rounded-xl border border-border-strong bg-surface px-3 text-sm text-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary/50"
              >
                <option value="">选择角色</option>
                {characterNames.map((name) => (
                  <option key={name} value={name}>{name}</option>
                ))}
              </select>
            </div>
            <div className="space-y-1">
              <span className="text-xs text-muted">目标角色</span>
              <select
                value={form.target_character || ""}
                onChange={(e) => setForm({ ...form, target_character: e.target.value })}
                className="h-10 w-full rounded-xl border border-border-strong bg-surface px-3 text-sm text-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary/50"
              >
                <option value="">选择角色</option>
                {characterNames.map((name) => (
                  <option key={name} value={name}>{name}</option>
                ))}
              </select>
            </div>
            <div className="space-y-1">
              <span className="text-xs text-muted">关系类型</span>
              <select
                value={form.relation_type || "其他"}
                onChange={(e) => setForm({ ...form, relation_type: e.target.value })}
                className="h-10 w-full rounded-xl border border-border-strong bg-surface px-3 text-sm text-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary/50"
              >
                {RELATION_TYPES.map((t) => (
                  <option key={t} value={t}>{t}</option>
                ))}
              </select>
            </div>
            <Input
              placeholder="子类型"
              value={form.relation_subtype || ""}
              onChange={(e) => setForm({ ...form, relation_subtype: e.target.value })}
            />
            <Input
              type="number"
              placeholder="强度 (-10~10)"
              value={form.strength ?? ""}
              onChange={(e) => setForm({ ...form, strength: Number(e.target.value) })}
            />
            <Input
              type="number"
              placeholder="起始章节"
              value={form.since_chapter ?? ""}
              onChange={(e) => setForm({ ...form, since_chapter: Number(e.target.value) })}
            />
            <div className="space-y-1">
              <span className="text-xs text-muted">状态</span>
              <select
                value={form.status || "active"}
                onChange={(e) => setForm({ ...form, status: e.target.value })}
                className="h-10 w-full rounded-xl border border-border-strong bg-surface px-3 text-sm text-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary/50"
              >
                {STATUSES.map((s) => (
                  <option key={s} value={s}>{s}</option>
                ))}
              </select>
            </div>
            <label className="flex items-center gap-2 h-10 px-3 rounded-xl border border-border-strong bg-surface text-sm text-foreground cursor-pointer">
              <input
                type="checkbox"
                checked={form.is_bidirectional ?? true}
                onChange={(e) => setForm({ ...form, is_bidirectional: e.target.checked })}
                className="rounded border-border-strong"
              />
              双向关系
            </label>
          </div>
          <Textarea
            placeholder="关系描述"
            value={form.description || ""}
            onChange={(e) => setForm({ ...form, description: e.target.value })}
          />
        </CardContent>
      </Card>
      {deleteDialog}
    </div>
  );
}
