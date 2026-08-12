import { useEffect, useMemo, useState } from "react";
import { Save, Trash2, Map, Sparkles } from "lucide-react";
import { api } from "@/api";
import { useAppStore } from "@/store";
import { useToast } from "@/hooks/useToast";
import { useConfirmDialog } from "@/hooks/useConfirmDialog";
import type { Instance } from "@/types";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Textarea } from "@/components/ui/textarea";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { TagWeightFields } from "@/components/ui/tag-weight-fields";

interface InstanceEditorViewProps {
  instanceId: number;
  onBack?: () => void;
  onGenerateInstance?: () => void;
  generatingInstance?: boolean;
}

const INSTANCE_TYPES = ["文明副本", "量子隧穿", "迷宫", "试炼", "秘境", "关卡", "其他"];
const DIFFICULTIES = ["数值", "机制", "混合", "简单", "普通", "困难", "地狱"];

export function InstanceEditorView({ instanceId, onBack, onGenerateInstance, generatingInstance }: InstanceEditorViewProps) {
  const store = useAppStore();
  const { showSuccess, showError } = useToast();
  const { confirm: confirmDelete, dialog: deleteDialog } = useConfirmDialog();

  const instance = useMemo(() => store.instances.find((i) => i.id === instanceId), [store.instances, instanceId]);
  const [form, setForm] = useState<Partial<Instance>>(() => instance || {});

  useEffect(() => {
    setForm(instance || {});
  }, [instanceId]);

  if (!instance) {
    return (
      <div className="flex-1 flex items-center justify-center text-muted text-sm">副本不存在或已被删除</div>
    );
  }

  const handleSave = async () => {
    if (!store.currentProject) return;
    try {
      await api.updateInstance(store.currentProject.id, instanceId, form);
      await store.refreshInstances();
      showSuccess("保存成功");
    } catch (e: any) {
      showError("保存失败：" + e.message);
    }
  };

  const handleDelete = async () => {
    if (!store.currentProject) return;
    const confirmed = await confirmDelete({
      title: "删除副本",
      description: `确定删除副本「${instance.name}」吗？此操作不可恢复。`,
      confirmText: "删除",
      cancelText: "取消",
      variant: "danger",
    });
    if (!confirmed) return;
    try {
      await api.deleteInstance(store.currentProject.id, instanceId);
      await store.refreshInstances();
      showSuccess("删除成功");
      onBack?.();
    } catch (e: any) {
      showError("删除失败：" + e.message);
    }
  };

  const selectCls =
    "h-10 w-full rounded-xl border border-border-strong bg-surface px-3 text-sm text-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary/50";

  return (
    <div className="flex-1 flex flex-col gap-3 min-h-0 overflow-hidden">
      <Card className="flex-1 overflow-y-auto">
        <CardHeader>
          <div className="flex items-center justify-between">
            <CardTitle className="flex items-center gap-2">
              <Map className="h-4 w-4 text-primary" />
              副本编辑
            </CardTitle>
            <div className="flex gap-2">
              {onGenerateInstance && (
                <Button size="sm" variant="primary" onClick={onGenerateInstance} disabled={generatingInstance}>
                  <Sparkles className="h-3.5 w-3.5 mr-1" />
                  {generatingInstance ? "生成中…" : "AI 生成副本"}
                </Button>
              )}
              <Button size="sm" onClick={handleSave}><Save className="h-3.5 w-3.5 mr-1" /> 保存</Button>
              <Button size="sm" variant="danger" onClick={handleDelete}><Trash2 className="h-3.5 w-3.5 mr-1" /> 删除</Button>
            </div>
          </div>
        </CardHeader>
        <CardContent className="space-y-4">
          <div className="grid grid-cols-1 md:grid-cols-3 gap-3">
            <Input placeholder="副本名称" value={form.name || ""} onChange={(e) => setForm({ ...form, name: e.target.value })} />
            <select
              value={form.instance_type || ""}
              onChange={(e) => setForm({ ...form, instance_type: e.target.value })}
              className={selectCls}
            >
              <option value="">副本类型</option>
              {INSTANCE_TYPES.map((t) => (
                <option key={t} value={t}>{t}</option>
              ))}
            </select>
            <Input
              type="number"
              placeholder="所属卷（0=不限）"
              value={form.related_volume ?? 0}
              onChange={(e) => setForm({ ...form, related_volume: Number(e.target.value) })}
            />
            <Input
              placeholder="章节范围（如 86-100）"
              value={form.chapter_range || ""}
              onChange={(e) => setForm({ ...form, chapter_range: e.target.value })}
            />
            <select
              value={form.difficulty || ""}
              onChange={(e) => setForm({ ...form, difficulty: e.target.value })}
              className={selectCls}
            >
              <option value="">难度</option>
              {DIFFICULTIES.map((d) => (
                <option key={d} value={d}>{d}</option>
              ))}
            </select>
            <Input
              placeholder="基调（悲壮/轻松/紧张/悬疑…）"
              value={form.tone || ""}
              onChange={(e) => setForm({ ...form, tone: e.target.value })}
            />
          </div>
          <Textarea
            placeholder="副本目的（为什么要进这个副本，解决什么）"
            value={form.objective || ""}
            onChange={(e) => setForm({ ...form, objective: e.target.value })}
          />
          <Textarea
            placeholder="副本机制（规则、玩法、通关条件）"
            value={form.mechanism || ""}
            onChange={(e) => setForm({ ...form, mechanism: e.target.value })}
          />
          <Textarea
            placeholder="奖励"
            value={form.rewards || ""}
            onChange={(e) => setForm({ ...form, rewards: e.target.value })}
          />
          <Textarea
            placeholder="代价（失败惩罚/消耗）"
            value={form.cost || ""}
            onChange={(e) => setForm({ ...form, cost: e.target.value })}
          />
          <Textarea
            placeholder="详细描述"
            value={form.description || ""}
            onChange={(e) => setForm({ ...form, description: e.target.value })}
            rows={6}
          />
          <Input
            type="number"
            placeholder="排序"
            value={form.order ?? 0}
            onChange={(e) => setForm({ ...form, order: Number(e.target.value) })}
          />

          <TagWeightFields
            tags={(form.tags || []) as string[]}
            weight={form.weight ?? 50}
            onTags={(t) => setForm({ ...form, tags: t })}
            onWeight={(w) => setForm({ ...form, weight: w })}
          />
        </CardContent>
      </Card>
      {deleteDialog}
    </div>
  );
}
