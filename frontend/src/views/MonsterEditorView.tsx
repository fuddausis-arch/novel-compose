import { useEffect, useMemo, useState } from "react";
import { Save, Trash2, Skull, Sparkles } from "lucide-react";
import { api } from "@/api";
import { useAppStore } from "@/store";
import { useToast } from "@/hooks/useToast";
import { useConfirmDialog } from "@/hooks/useConfirmDialog";
import { AppearanceManager } from "@/components/entity/appearance-manager";
import type { Monster } from "@/types";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Textarea } from "@/components/ui/textarea";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { TagWeightFields } from "@/components/ui/tag-weight-fields";

interface MonsterEditorViewProps {
  monsterId: number;
  onBack?: () => void;
}

const MONSTER_TIERS = ["BOSS", "精英", "首领", "小怪", "普通"];

export function MonsterEditorView({ monsterId, onBack }: MonsterEditorViewProps) {
  const store = useAppStore();
  const { showSuccess, showError } = useToast();
  const { confirm: confirmDelete, dialog: deleteDialog } = useConfirmDialog();

  const monster = useMemo(() => store.monsters.find((m) => m.id === monsterId), [store.monsters, monsterId]);
  const [form, setForm] = useState<Partial<Monster>>(() => monster || {});
  const [generating, setGenerating] = useState(false);

  useEffect(() => {
    setForm(monster || {});
  }, [monsterId]);

  if (!monster) {
    return (
      <div className="flex-1 flex items-center justify-center text-muted text-sm">怪物不存在或已被删除</div>
    );
  }

  const handleAiGenerate = async () => {
    if (!store.currentProject) return;
    setGenerating(true);
    try {
      const created = await api.generateMonster(store.currentProject.id, {
        name_hint: form.name || "",
        rank: form.rank || "",
        species: form.species || "",
      });
      setForm(created);
      await store.refreshMonsters();
      showSuccess("AI 已生成怪物设定，已填入表单，点击「保存」生效");
    } catch (e: any) {
      showError("AI 生成失败：" + e.message);
    } finally {
      setGenerating(false);
    }
  };

  const handleSave = async () => {
    if (!store.currentProject) return;
    try {
      await api.updateMonster(store.currentProject.id, monsterId, form);
      await store.refreshMonsters();
      showSuccess("保存成功");
    } catch (e: any) {
      showError("保存失败：" + e.message);
    }
  };

  const handleDelete = async () => {
    if (!store.currentProject) return;
    const confirmed = await confirmDelete({
      title: "删除怪物",
      description: `确定删除怪物「${monster.name}」吗？此操作不可恢复。`,
      confirmText: "删除",
      cancelText: "取消",
      variant: "danger",
    });
    if (!confirmed) return;
    try {
      await api.deleteMonster(store.currentProject.id, monsterId);
      await store.refreshMonsters();
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
              <Skull className="h-4 w-4 text-primary" />
              怪物编辑
            </CardTitle>
            <div className="flex gap-2">
              <Button size="sm" variant="primary" onClick={handleAiGenerate} disabled={generating}>
                <Sparkles className="h-3.5 w-3.5 mr-1" />
                {generating ? "生成中…" : "AI 生成怪物"}
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
            <Input placeholder="种族" value={form.species || ""} onChange={(e) => setForm({ ...form, species: e.target.value })} />
            <Input placeholder="等级" value={form.rank || ""} onChange={(e) => setForm({ ...form, rank: e.target.value })} />
            <Input placeholder="栖息地" value={form.habitats || ""} onChange={(e) => setForm({ ...form, habitats: e.target.value })} />
            <Input
              type="number"
              placeholder="首次出场章节"
              value={form.first_appearance ?? ""}
              onChange={(e) => setForm({ ...form, first_appearance: Number(e.target.value) })}
            />
            <select
              value={form.tier || ""}
              onChange={(e) => setForm({ ...form, tier: e.target.value })}
              className="h-10 w-full rounded-xl border border-border-strong bg-surface px-3 text-sm text-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary/50"
            >
              <option value="">怪物等级</option>
              {MONSTER_TIERS.map((t) => (
                <option key={t} value={t}>{t}</option>
              ))}
            </select>
          </div>
          <Textarea
            placeholder="属性（JSON 字符串）"
            value={form.attributes || ""}
            onChange={(e) => setForm({ ...form, attributes: e.target.value })}
            className="font-mono text-xs"
          />
          <Textarea
            placeholder="技能（JSON 字符串）"
            value={form.skills || ""}
            onChange={(e) => setForm({ ...form, skills: e.target.value })}
            className="font-mono text-xs"
          />
          <Textarea
            placeholder="掉落（JSON 字符串）"
            value={form.drops || ""}
            onChange={(e) => setForm({ ...form, drops: e.target.value })}
            className="font-mono text-xs"
          />
          <Textarea placeholder="行为" value={form.behavior || ""} onChange={(e) => setForm({ ...form, behavior: e.target.value })} />
          <Textarea placeholder="弱点" value={form.weaknesses || ""} onChange={(e) => setForm({ ...form, weaknesses: e.target.value })} />
          <Textarea placeholder="背景传说" value={form.lore || ""} onChange={(e) => setForm({ ...form, lore: e.target.value })} />

          <TagWeightFields
            tags={(form.tags || []) as string[]}
            weight={form.weight ?? 50}
            onTags={(t) => setForm({ ...form, tags: t })}
            onWeight={(w) => setForm({ ...form, weight: w })}
          />

          <div className="border border-border rounded-xl p-3 space-y-3">
            {store.currentProject && (
              <AppearanceManager projectId={store.currentProject.id} entityType="monster" entityId={String(monsterId)} />
            )}
          </div>
        </CardContent>
      </Card>
      {deleteDialog}
    </div>
  );
}
