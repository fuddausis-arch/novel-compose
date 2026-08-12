import { useEffect, useMemo, useState } from "react";
import { Save, Trash2, Shield, Plus, ArrowRight, Sparkles } from "lucide-react";
import { api } from "@/api";
import { useAppStore } from "@/store";
import { useToast } from "@/hooks/useToast";
import { useConfirmDialog } from "@/hooks/useConfirmDialog";
import { AppearanceManager } from "@/components/entity/appearance-manager";
import type { Faction, FactionRelationship } from "@/types";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Textarea } from "@/components/ui/textarea";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { TagWeightFields } from "@/components/ui/tag-weight-fields";

interface FactionEditorViewProps {
  factionId: number;
  onBack?: () => void;
}

const RELATION_TYPES = ["同盟", "敌对", "中立", "附属", "竞争", "秘密合作", "其他"];
const FACTION_TIERS = ["顶级势力", "一流势力", "二流势力", "三流势力", "隐世势力"];

export function FactionEditorView({ factionId, onBack }: FactionEditorViewProps) {
  const store = useAppStore();
  const { showSuccess, showError } = useToast();
  const { confirm: confirmDelete, dialog: deleteDialog } = useConfirmDialog();

  const faction = useMemo(() => store.factions.find((f) => f.id === factionId), [store.factions, factionId]);
  const relationships = useMemo(
    () => store.factionRelationships.filter((r) => r.source_faction_id === factionId || r.target_faction_id === factionId),
    [store.factionRelationships, factionId]
  );

  const [form, setForm] = useState<Partial<Faction>>(() => faction || {});
  const [generating, setGenerating] = useState(false);

  useEffect(() => {
    setForm(faction || {});
  }, [factionId]);

  const [addingRel, setAddingRel] = useState(false);
  const [relForm, setRelForm] = useState<Partial<FactionRelationship>>({
    target_faction_id: undefined,
    relation_type: "中立",
    strength: 0,
    description: "",
  });

  if (!faction) {
    return (
      <div className="flex-1 flex items-center justify-center text-muted text-sm">势力不存在或已被删除</div>
    );
  }

  const handleAiGenerate = async () => {
    if (!store.currentProject) return;
    setGenerating(true);
    try {
      const created = await api.generateFaction(store.currentProject.id, {
        name_hint: form.name || "",
        type: form.type || "",
        alignment: form.alignment || "",
      });
      setForm(created);
      await store.refreshFactions();
      showSuccess("AI 已生成势力设定，已填入表单，点击「保存」生效");
    } catch (e: any) {
      showError("AI 生成失败：" + e.message);
    } finally {
      setGenerating(false);
    }
  };

  const handleSave = async () => {
    if (!store.currentProject) return;
    try {
      await api.updateFaction(store.currentProject.id, factionId, form);
      await store.refreshFactions();
      showSuccess("保存成功");
    } catch (e: any) {
      showError("保存失败：" + e.message);
    }
  };

  const handleDelete = async () => {
    if (!store.currentProject) return;
    const confirmed = await confirmDelete({
      title: "删除势力",
      description: `确定删除势力「${faction.name}」吗？此操作不可恢复。`,
      confirmText: "删除",
      cancelText: "取消",
      variant: "danger",
    });
    if (!confirmed) return;
    try {
      await api.deleteFaction(store.currentProject.id, factionId);
      // 删除势力会级联影响该势力相关的势力关系，刷新势力与势力关系两个切片
      await Promise.all([store.refreshFactions(), store.refreshFactionRelationships()]);
      showSuccess("删除成功");
      onBack?.();
    } catch (e: any) {
      showError("删除失败：" + e.message);
    }
  };

  const handleCreateRelationship = async () => {
    if (!store.currentProject || !relForm.target_faction_id) return;
    try {
      await api.createFactionRelationship(store.currentProject.id, {
        source_faction_id: factionId,
        target_faction_id: relForm.target_faction_id,
        relation_type: relForm.relation_type || "中立",
        strength: relForm.strength ?? 0,
        description: relForm.description || "",
      });
      setAddingRel(false);
      setRelForm({ target_faction_id: undefined, relation_type: "中立", strength: 0, description: "" });
      await store.refreshFactionRelationships();
      showSuccess("关系已添加");
    } catch (e: any) {
      showError("添加关系失败：" + e.message);
    }
  };

  const handleDeleteRelationship = async (relId: number) => {
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
      await api.deleteFactionRelationship(store.currentProject.id, relId);
      await store.refreshFactionRelationships();
      showSuccess("关系已删除");
    } catch (e: any) {
      showError("删除关系失败：" + e.message);
    }
  };

  const getFactionName = (id: number) => store.factions.find((f) => f.id === id)?.name || `势力#${id}`;

  const otherFactions = store.factions.filter((f) => f.id !== factionId);

  return (
    <div className="flex-1 flex flex-col gap-3 min-h-0 overflow-hidden">
      <Card className="flex-1 overflow-y-auto">
        <CardHeader>
          <div className="flex items-center justify-between">
            <CardTitle className="flex items-center gap-2">
              <Shield className="h-4 w-4 text-primary" />
              势力编辑
            </CardTitle>
            <div className="flex gap-2">
              <Button size="sm" variant="primary" onClick={handleAiGenerate} disabled={generating}>
                <Sparkles className="h-3.5 w-3.5 mr-1" />
                {generating ? "生成中…" : "AI 生成势力"}
              </Button>
              <Button size="sm" onClick={handleSave}><Save className="h-3.5 w-3.5 mr-1" /> 保存</Button>
              <Button size="sm" variant="danger" onClick={handleDelete}><Trash2 className="h-3.5 w-3.5 mr-1" /> 删除</Button>
            </div>
          </div>
        </CardHeader>
        <CardContent className="space-y-4">
          <div className="grid grid-cols-1 md:grid-cols-3 gap-3">
            <Input placeholder="名称" value={form.name || ""} onChange={(e) => setForm({ ...form, name: e.target.value })} />
            <Input placeholder="别名" value={form.alias || ""} onChange={(e) => setForm({ ...form, alias: e.target.value })} />
            <Input placeholder="类型" value={form.type || ""} onChange={(e) => setForm({ ...form, type: e.target.value })} />
            <Input placeholder="阵营" value={form.alignment || ""} onChange={(e) => setForm({ ...form, alignment: e.target.value })} />
            <Input placeholder="领土" value={form.territories || ""} onChange={(e) => setForm({ ...form, territories: e.target.value })} />
            <Input placeholder="资源" value={form.resources || ""} onChange={(e) => setForm({ ...form, resources: e.target.value })} />
            <select
              value={form.tier || ""}
              onChange={(e) => setForm({ ...form, tier: e.target.value })}
              className="h-10 w-full rounded-xl border border-border-strong bg-surface px-3 text-sm text-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary/50"
            >
              <option value="">势力等级</option>
              {FACTION_TIERS.map((t) => (
                <option key={t} value={t}>{t}</option>
              ))}
            </select>
          </div>
          <Textarea placeholder="简介" value={form.description || ""} onChange={(e) => setForm({ ...form, description: e.target.value })} />
          <Textarea placeholder="历史" value={form.history || ""} onChange={(e) => setForm({ ...form, history: e.target.value })} />
          <Textarea placeholder="目标" value={form.goals || ""} onChange={(e) => setForm({ ...form, goals: e.target.value })} />
          <Textarea placeholder="层级结构" value={form.hierarchy || ""} onChange={(e) => setForm({ ...form, hierarchy: e.target.value })} />

          <TagWeightFields
            tags={(form.tags || []) as string[]}
            weight={form.weight ?? 50}
            onTags={(t) => setForm({ ...form, tags: t })}
            onWeight={(w) => setForm({ ...form, weight: w })}
          />

          <div className="border border-border rounded-xl p-3 space-y-3">
            <div className="flex items-center justify-between">
              <h4 className="font-medium text-sm">关系</h4>
              <Button size="sm" variant="ghost" onClick={() => setAddingRel(!addingRel)}>
                <Plus className="h-3.5 w-3.5 mr-1" /> {addingRel ? "取消" : "添加关系"}
              </Button>
            </div>

            {addingRel && (
              <div className="space-y-2 border border-border rounded-lg p-3 bg-surface/50">
                <select
                  value={relForm.target_faction_id || ""}
                  onChange={(e) => setRelForm({ ...relForm, target_faction_id: Number(e.target.value) })}
                  className="h-10 w-full rounded-xl border border-border-strong bg-surface px-3 text-sm text-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary/50"
                >
                  <option value="">选择目标势力</option>
                  {otherFactions.map((f) => (
                    <option key={f.id} value={f.id}>{f.name}</option>
                  ))}
                </select>
                <div className="grid grid-cols-2 gap-2">
                  <select
                    value={relForm.relation_type || "中立"}
                    onChange={(e) => setRelForm({ ...relForm, relation_type: e.target.value })}
                    className="h-10 rounded-xl border border-border-strong bg-surface px-3 text-sm text-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary/50"
                  >
                    {RELATION_TYPES.map((t) => (
                      <option key={t} value={t}>{t}</option>
                    ))}
                  </select>
                  <Input
                    type="number"
                    placeholder="强度 (-10~10)"
                    value={relForm.strength ?? ""}
                    onChange={(e) => setRelForm({ ...relForm, strength: Number(e.target.value) })}
                  />
                </div>
                <Textarea
                  placeholder="关系描述"
                  value={relForm.description || ""}
                  onChange={(e) => setRelForm({ ...relForm, description: e.target.value })}
                />
                <Button size="sm" onClick={handleCreateRelationship} disabled={!relForm.target_faction_id}>添加</Button>
              </div>
            )}

            {relationships.length === 0 && <div className="text-sm text-muted">暂无关系</div>}
            <div className="space-y-2">
              {relationships.map((r) => {
                const isSource = r.source_faction_id === factionId;
                const otherId = isSource ? r.target_faction_id : r.source_faction_id;
                return (
                  <div key={r.id} className="flex items-center justify-between gap-2 rounded-lg border border-border p-2">
                    <div className="flex items-center gap-2 text-sm min-w-0">
                      <span className="font-medium truncate">{isSource ? faction.name : getFactionName(otherId)}</span>
                      <ArrowRight className="h-3 w-3 text-muted shrink-0" />
                      <span className="truncate">{isSource ? getFactionName(otherId) : faction.name}</span>
                      <Badge variant="primary">{r.relation_type}</Badge>
                      <span className="text-xs text-muted">强度 {r.strength}</span>
                    </div>
                    <button onClick={() => handleDeleteRelationship(r.id)} className="p-1 hover:bg-foreground/5 rounded shrink-0" aria-label="删除关系">
                      <Trash2 className="h-3.5 w-3.5 text-danger" />
                    </button>
                  </div>
                );
              })}
            </div>
          </div>

          <div className="border border-border rounded-xl p-3 space-y-3">
            {store.currentProject && (
              <AppearanceManager projectId={store.currentProject.id} entityType="faction" entityId={String(factionId)} />
            )}
          </div>
        </CardContent>
      </Card>
      {deleteDialog}
    </div>
  );
}
