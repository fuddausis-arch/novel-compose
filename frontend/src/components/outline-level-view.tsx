import { useEffect, useMemo, useState } from "react";
import { List, Plus, Sparkles, Trash2, Save, X, Edit2, Loader2 } from "lucide-react";
import { api } from "@/api";
import { useToast } from "@/hooks/useToast";
import { useConfirmDialog } from "@/hooks/useConfirmDialog";
import type { Project, Outline } from "@/types";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Textarea } from "@/components/ui/textarea";
import { Select } from "@/components/ui/select";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { AiPreviewEditor } from "@/components/ai-preview-editor";
import { AiSuggestionDialog } from "@/components/ai-suggestion-dialog";

interface OutlineLevelViewProps {
  project: Project;
  level: "volume" | "arc" | "chapter";
  parentLevel?: "volume" | "arc";
  title: string;
  refresh?: () => Promise<void>;
  setLoading?: (loading: boolean) => void;
}

const ACTS = ["开端", "发展", "小高潮", "转折", "大高潮", "结局"];
const STRANDS = [
  { value: "quest", label: "主线" },
  { value: "fire", label: "感情" },
  { value: "constellation", label: "世界观" },
];

export function OutlineLevelView({ project, level, parentLevel, title, refresh, setLoading }: OutlineLevelViewProps) {
  const { showSuccess, showError } = useToast();
  const { confirm: confirmDelete, dialog: deleteDialog } = useConfirmDialog();

  const [items, setItems] = useState<Outline[]>([]);
  const [parents, setParents] = useState<Outline[]>([]);
  const [parentId, setParentId] = useState<number | null>(null);
  const [loading, setLocalLoading] = useState(false);

  const [generating, setGenerating] = useState(false);
  const [count, setCount] = useState(level === "volume" ? 3 : level === "arc" ? 5 : 10);
  const [customPrompt, setCustomPrompt] = useState("");

  const [adding, setAdding] = useState(false);
  const [newForm, setNewForm] = useState<Partial<Outline>>({
    order: 1,
    level,
    parent_id: parentId,
    title: "",
    summary: "",
    act: "发展",
    strand: "quest",
  });

  const [editingId, setEditingId] = useState<number | null>(null);
  const [editForm, setEditForm] = useState<Partial<Outline>>({});

  const [previewOpen, setPreviewOpen] = useState(false);
  const [previewItems, setPreviewItems] = useState<Outline[]>([]);
  const [regenerating, setRegenerating] = useState(false);
  const [suggestOpen, setSuggestOpen] = useState(false);

  const load = async () => {
    setLocalLoading(true);
    try {
      const data = await api.listOutlines(project.id, level, parentId ?? undefined);
      setItems(data);
      if (refresh) await refresh();
    } catch (e: any) {
      showError("加载失败：" + e.message);
    } finally {
      setLocalLoading(false);
    }
  };

  const loadParents = async () => {
    if (!parentLevel) {
      setParents([]);
      setParentId(null);
      return;
    }
    try {
      const data = await api.listOutlines(project.id, parentLevel);
      setParents(data);
      if (data.length > 0 && parentId === null) {
        setParentId(data[0].id);
      }
    } catch (e: any) {
      showError("加载父级失败：" + e.message);
    }
  };

  useEffect(() => {
    loadParents();
  }, [project.id, parentLevel]);

  useEffect(() => {
    load();
  }, [project.id, level, parentId]);

  useEffect(() => {
    setNewForm((prev) => ({ ...prev, parent_id: parentId }));
  }, [parentId]);

  const sorted = useMemo(() => [...items].sort((a, b) => a.order - b.order), [items]);

  const handleGenerate = async () => {
    setGenerating(true);
    setLoading?.(true);
    try {
      const r = await doGenerate(customPrompt);
      if (r.items && r.items.length > 0) {
        setPreviewItems(r.items as Outline[]);
        setPreviewOpen(true);
      } else {
        await load();
        showSuccess("AI 未返回内容");
      }
    } catch (e: any) {
      showError("生成失败：" + e.message);
    } finally {
      setGenerating(false);
      setLoading?.(false);
    }
  };

  const discardGenerated = async (items: Outline[]) => {
    await Promise.all(items.map((item) => item.id ? api.deleteOutline(project.id, item.id) : Promise.resolve()));
  };

  const doGenerate = async (prompt: string) => {
    if (level === "volume") {
      return await api.generateVolumes(project.id, count, prompt);
    } else if (level === "arc") {
      if (!parentId) throw new Error("请先选择所属卷");
      return await api.generateArcs(project.id, parentId, count, prompt);
    } else {
      if (!parentId) throw new Error("请先选择所属细纲");
      return await api.generateChapters(project.id, parentId, count, prompt);
    }
  };

  const handleRegenerate = async (prompt: string) => {
    setRegenerating(true);
    setLoading?.(true);
    try {
      const r = await doGenerate(prompt);
      if (r.items && r.items.length > 0) {
        const newItems = r.items as Outline[];
        await discardGenerated(previewItems);
        setPreviewItems(newItems);
        setCustomPrompt(prompt);
        showSuccess(`已重新生成 ${newItems.length} 条${title}`);
      } else {
        showSuccess("AI 未返回内容");
      }
    } catch (e: any) {
      showError("重新生成失败：" + e.message);
    } finally {
      setRegenerating(false);
      setLoading?.(false);
    }
  };

  const handleImport = async (selected: Outline[]) => {
    const discarded = previewItems.filter((item) => !selected.find((s) => s.id === item.id));
    // 保存选中项的编辑内容
    await Promise.all(
      selected.map((item) =>
        item.id ? api.updateOutline(project.id, item.id, item) : Promise.resolve()
      )
    );
    await discardGenerated(discarded);
    await load();
    setPreviewOpen(false);
    setPreviewItems([]);
    showSuccess(`已导入 ${selected.length} 条${title}`);
  };

  const handlePreviewClose = async () => {
    await discardGenerated(previewItems);
    await load();
    setPreviewOpen(false);
    setPreviewItems([]);
  };

  const handleCreate = async () => {
    if (!newForm.title?.trim()) return;
    try {
      await api.createOutline(project.id, { ...newForm, level, parent_id: parentId });
      setAdding(false);
      setNewForm({ order: (sorted.length || 0) + 1, level, parent_id: parentId, title: "", summary: "", act: "发展", strand: "quest" });
      await load();
      showSuccess("创建成功");
    } catch (e: any) {
      showError("创建失败：" + e.message);
    }
  };

  const startEdit = (item: Outline) => {
    setEditingId(item.id);
    setEditForm({ ...item });
  };

  const cancelEdit = () => {
    setEditingId(null);
    setEditForm({});
  };

  const saveEdit = async () => {
    if (!editingId) return;
    try {
      await api.updateOutline(project.id, editingId, editForm);
      setEditingId(null);
      setEditForm({});
      await load();
      showSuccess("保存成功");
    } catch (e: any) {
      showError("保存失败：" + e.message);
    }
  };

  const handleDelete = async (id: number) => {
    const ok = await confirmDelete({ title: "确认删除？", description: "删除将级联删除其下所有子级，且无法恢复。", variant: "danger" });
    if (!ok) return;
    try {
      await api.deleteOutline(project.id, id);
      await load();
      showSuccess("删除成功");
    } catch (e: any) {
      showError("删除失败：" + e.message);
    }
  };

  const levelBadge = {
    volume: "卷",
    arc: "细纲",
    chapter: "章纲",
  };

  return (
    <Card className="flex-1 flex flex-col min-h-0">
      <CardHeader className="pb-2">
        <CardTitle className="text-base flex items-center gap-2">
          <List className="h-4 w-4" />
          {title}
        </CardTitle>
      </CardHeader>
      <CardContent className="flex-1 overflow-y-auto space-y-3">
        <div className="flex flex-wrap items-center gap-2">
          {parentLevel && (
            <Select
              className="min-w-[160px]"
              value={parentId ?? ""}
              onChange={(e) => setParentId(e.target.value ? Number(e.target.value) : null)}
            >
              <option value="">选择{parentLevel === "volume" ? "卷" : "细纲"}</option>
              {parents.map((p) => (
                <option key={p.id} value={p.id}>
                  {p.order}. {p.title}
                </option>
              ))}
            </Select>
          )}
          <Input type="number" className="w-20" value={count} onChange={(e) => setCount(Number(e.target.value))} />
          <span className="text-xs text-muted">条</span>
          <Input className="flex-1 min-w-[200px]" placeholder="自定义要求（可选）" value={customPrompt} onChange={(e) => setCustomPrompt(e.target.value)} />
          <Button variant="primary" onClick={handleGenerate} disabled={generating || (parentLevel ? !parentId : false)}>
            {generating ? <Loader2 className="h-3.5 w-3.5 mr-1 animate-spin" /> : <Sparkles className="h-3.5 w-3.5 mr-1" />}
            {generating ? "AI 生成中…" : `AI 生成${title}`}
          </Button>
          <Button variant="outline" onClick={() => setSuggestOpen(true)} disabled={parentLevel ? !parentId : false}>
            <Sparkles className="h-3.5 w-3.5 mr-1" />
            AI 建议后续
          </Button>
          <Button size="sm" variant="ghost" onClick={() => setAdding(!adding)}>
            <Plus className="h-4 w-4 mr-1" /> 手动添加
          </Button>
        </div>

        {adding && (
          <div className="space-y-2 border border-border rounded-xl p-3">
            <div className="flex gap-2">
              <Input type="number" className="w-20" placeholder="顺序" value={newForm.order} onChange={(e) => setNewForm({ ...newForm, order: Number(e.target.value) })} />
              <Input placeholder="标题" value={newForm.title} onChange={(e) => setNewForm({ ...newForm, title: e.target.value })} />
              <Select value={newForm.act} onChange={(e) => setNewForm({ ...newForm, act: e.target.value })}>
                {ACTS.map((a) => (
                  <option key={a} value={a}>{a}</option>
                ))}
              </Select>
              {level !== "volume" && (
                <Select value={newForm.strand} onChange={(e) => setNewForm({ ...newForm, strand: e.target.value as Outline["strand"] })}>
                  {STRANDS.map((s) => (
                    <option key={s.value} value={s.value}>{s.label}</option>
                  ))}
                </Select>
              )}
            </div>
            <Textarea placeholder="摘要" value={newForm.summary} onChange={(e) => setNewForm({ ...newForm, summary: e.target.value })} />
            <div className="flex gap-2 justify-end">
              <Button size="sm" variant="ghost" onClick={() => setAdding(false)}><X className="h-4 w-4 mr-1" /> 取消</Button>
              <Button size="sm" variant="primary" onClick={handleCreate}><Save className="h-4 w-4 mr-1" /> 保存</Button>
            </div>
          </div>
        )}

        {loading ? (
          <div className="text-sm text-muted flex items-center gap-2"><Loader2 className="h-4 w-4 animate-spin" /> 加载中…</div>
        ) : sorted.length === 0 ? (
          <div className="text-sm text-muted">暂无{title}，点击上方按钮生成或手动添加。</div>
        ) : (
          <div className="space-y-2">
            {sorted.map((item) => (
              <div key={item.id} className="border border-border rounded-xl p-3 hover:border-primary/30 transition-colors">
                {editingId === item.id ? (
                  <div className="space-y-2">
                    <div className="flex gap-2">
                      <Input type="number" className="w-20" value={editForm.order} onChange={(e) => setEditForm({ ...editForm, order: Number(e.target.value) })} />
                      <Input value={editForm.title} onChange={(e) => setEditForm({ ...editForm, title: e.target.value })} />
                      <Select value={editForm.act} onChange={(e) => setEditForm({ ...editForm, act: e.target.value })}>
                        {ACTS.map((a) => (
                          <option key={a} value={a}>{a}</option>
                        ))}
                      </Select>
                      {level !== "volume" && (
                        <Select value={editForm.strand} onChange={(e) => setEditForm({ ...editForm, strand: e.target.value as Outline["strand"] })}>
                          {STRANDS.map((s) => (
                            <option key={s.value} value={s.value}>{s.label}</option>
                          ))}
                        </Select>
                      )}
                    </div>
                    <Textarea value={editForm.summary} onChange={(e) => setEditForm({ ...editForm, summary: e.target.value })} />
                    <div className="flex gap-2 justify-end">
                      <Button size="sm" variant="ghost" onClick={cancelEdit}><X className="h-4 w-4 mr-1" /> 取消</Button>
                      <Button size="sm" variant="primary" onClick={saveEdit}><Save className="h-4 w-4 mr-1" /> 保存</Button>
                    </div>
                  </div>
                ) : (
                  <div className="flex items-start gap-3">
                    <Badge variant="default" className="mt-0.5">{levelBadge[item.level]}</Badge>
                    <div className="flex-1 min-w-0">
                      <div className="font-medium text-sm">
                        {item.order}. {item.title}
                        {item.act && <span className="text-xs text-muted ml-2">[{item.act}]</span>}
                        {item.strand && <span className="text-xs text-muted ml-2">({STRANDS.find((s) => s.value === item.strand)?.label || item.strand})</span>}
                      </div>
                      <div className="text-xs text-muted mt-1 whitespace-pre-wrap">{item.summary}</div>
                    </div>
                    <div className="flex gap-1">
                      <Button size="sm" variant="ghost" className="h-8 w-8 px-0" onClick={() => startEdit(item)}><Edit2 className="h-3.5 w-3.5" /></Button>
                      <Button size="sm" variant="ghost" className="h-8 w-8 px-0" onClick={() => handleDelete(item.id)}><Trash2 className="h-3.5 w-3.5" /></Button>
                    </div>
                  </div>
                )}
              </div>
            ))}
          </div>
        )}
      </CardContent>

      <AiPreviewEditor
        open={previewOpen}
        title={`AI 生成${title}预览`}
        items={previewItems}
        level={level}
        customPrompt={customPrompt}
        onClose={handlePreviewClose}
        onImport={handleImport}
        onRegenerate={handleRegenerate}
        regenerating={regenerating}
      />
      <AiSuggestionDialog
        open={suggestOpen}
        project={project}
        contextType="outline"
        contextId={parentId ?? ""}
        defaultSuggestType="plot"
        onClose={() => setSuggestOpen(false)}
        onAdopted={() => {
          load();
          showSuccess("建议已采纳");
        }}
      />
      {deleteDialog}
    </Card>
  );
}
