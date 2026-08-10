import { useEffect, useMemo, useRef, useState } from "react";
import { useVirtualizer } from "@tanstack/react-virtual";
import { List, Plus, Sparkles, Trash2, Save, X, Edit2, Loader2, CheckSquare, Square, Hash } from "lucide-react";
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
import { GenerationStreamDialog, type GenStreamItem, type GenStreamType } from "@/components/generation-stream-dialog";

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

export function OutlineLevelView({ project, level, parentLevel, title, setLoading }: OutlineLevelViewProps) {
  const { showSuccess, showError } = useToast();
  const { confirm: confirmDelete, dialog: deleteDialog } = useConfirmDialog();

  const [items, setItems] = useState<Outline[]>([]);
  const [parents, setParents] = useState<Outline[]>([]);
  const [parentId, setParentId] = useState<number | null>(null);
  const [loading, setLocalLoading] = useState(false);

  // 章纲生成模式：by_arc=按细纲，by_volume=按卷纲
  const [chapterMode, setChapterMode] = useState<"by_arc" | "by_volume">("by_arc");
  const [volumes, setVolumes] = useState<Outline[]>([]);
  const [volumeId, setVolumeId] = useState<number | null>(null);

  const [count, setCount] = useState(level === "volume" ? 3 : level === "arc" ? 5 : 10);

  // 按卷纲生成时，count=0 表示自动决定章数；仅在首次切到某模式时设默认值，避免覆盖用户输入
  const modeInitRef = useRef<{ by_volume: boolean; by_arc: boolean }>({ by_volume: false, by_arc: false });
  // 记录每个 volume 是否已经自动同步过 planned_chapters，避免用户手动修改后被覆盖
  const volumeSyncRef = useRef<Set<number>>(new Set());

  useEffect(() => {
    if (level !== "chapter") return;
    if (chapterMode === "by_volume" && !modeInitRef.current.by_volume) {
      // 初始不置 0，等 volumeId 确定后从卷大纲的 planned_chapters 读取
      modeInitRef.current.by_volume = true;
    } else if (chapterMode === "by_arc" && !modeInitRef.current.by_arc) {
      setCount(10);
      modeInitRef.current.by_arc = true;
    }
  }, [level, chapterMode]);

  // 按卷纲生成时，根据选中卷的 planned_chapters 自动设置生成章数
  useEffect(() => {
    if (level !== "chapter" || chapterMode !== "by_volume" || volumeId === null) return;
    if (volumeSyncRef.current.has(volumeId)) return;
    const vol = volumes.find((v) => v.id === volumeId);
    const planned = vol?.planned_chapters;
    if (planned && planned > 0) {
      setCount(planned);
    } else {
      setCount(0);
    }
    volumeSyncRef.current.add(volumeId);
  }, [level, chapterMode, volumeId, volumes]);
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
    required_beats: "",
    owed_debts: "",
    required_hooks: "",
    character_constraints: "",
    phase: "regular",
  });

  const [editingId, setEditingId] = useState<number | null>(null);
  const [editForm, setEditForm] = useState<Partial<Outline>>({});

  const [previewOpen, setPreviewOpen] = useState(false);
  const [previewItems, setPreviewItems] = useState<Outline[]>([]);
  const [regenerating, setRegenerating] = useState(false);
  const [suggestOpen, setSuggestOpen] = useState(false);
  const [selectedIds, setSelectedIds] = useState<Set<number>>(new Set());
  const [batchMode, setBatchMode] = useState(false);

  // 流式生成弹窗
  const [streamOpen, setStreamOpen] = useState(false);
  const [streamType, setStreamType] = useState<GenStreamType>("arc");

  const load = async () => {
    // by_volume 模式下按卷过滤章纲，不依赖 parentId
    if (level === "chapter" && chapterMode === "by_volume") {
      if (!volumeId) { setItems([]); setLocalLoading(false); return; }
      const arcIds = parents.map((p) => p.id);
      if (arcIds.length === 0) { setItems([]); setLocalLoading(false); return; }
      setLocalLoading(true);
      try {
        const data = await api.listOutlines(project.id, "chapter");
        setItems(data.filter((ch) => arcIds.includes(ch.parent_id ?? -1)));
      } catch (e: any) {
        showError("加载失败：" + e.message);
      } finally {
        setLocalLoading(false);
      }
      return;
    }
    // 章纲/细纲需要选中父级才能加载，防止 parent_id=None 的数据全混在一起
    if (level !== "volume" && parentId === null) {
      setItems([]);
      setLocalLoading(false);
      return;
    }
    setLocalLoading(true);
    try {
      const data = await api.listOutlines(project.id, level, parentId ?? undefined);
      setItems(data);
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
      // 章纲按细纲生成时，只加载选中卷下的细纲
      const filterParentId = level === "chapter" && parentLevel === "arc" ? (volumeId ?? undefined) : undefined;
      const data = await api.listOutlines(project.id, parentLevel, filterParentId);
      setParents(data);
      if (data.length > 0 && (parentId === null || !data.find((d) => d.id === parentId))) {
        setParentId(data[0].id);
      }
    } catch (e: any) {
      showError("加载父级失败：" + e.message);
    }
  };

  // 加载卷列表（章纲按卷纲生成时使用）
  const loadVolumes = async () => {
    if (level !== "chapter") return;
    try {
      const data = await api.listOutlines(project.id, "volume");
      // 按 order 排序，防止数据 order 不连续时下拉框乱序
      data.sort((a, b) => a.order - b.order);
      setVolumes(data);
      if (data.length > 0 && volumeId === null) {
        setVolumeId(data[0].id);
      }
    } catch {
      // 忽略
    }
  };

  useEffect(() => {
    loadParents();
    loadVolumes();
  }, [project.id, parentLevel, volumeId]);

  useEffect(() => {
    load();
  }, [project.id, level, parentId, chapterMode, volumeId]);

  useEffect(() => {
    setNewForm((prev) => ({ ...prev, parent_id: parentId }));
  }, [parentId]);

  const sorted = useMemo(() => [...items].sort((a, b) => a.order - b.order), [items]);

  // 章纲列表（可能数百上千条）使用虚拟滚动，避免一次性渲染数万 DOM 节点
  const scrollRef = useRef<HTMLDivElement>(null);
  const virtualizer = useVirtualizer({
    count: sorted.length,
    getScrollElement: () => scrollRef.current,
    estimateSize: () => 120,
    overscan: 5,
  });

  const handleGenerate = async () => {
    // 校验
    if (level === "arc" && !parentId) { showError("请先选择所属卷"); return; }
    if (level === "chapter") {
      if (chapterMode === "by_volume") {
        if (!volumeId) { showError("请先选择所属卷"); return; }
      } else {
        if (!parentId) { showError("请先选择所属细纲"); return; }
      }
    }
    // 打开流式生成弹窗
    if (level === "volume") setStreamType("volume");
    else if (level === "arc") setStreamType("arc");
    else if (level === "chapter") setStreamType(chapterMode === "by_volume" ? "chapter_by_volume" : "chapter");
    setStreamOpen(true);
  };

  // 流式生成：创建 EventSource
  const createStreamSource = () => {
    if (level === "volume") {
      return api.generateVolumesStream(project.id, count, customPrompt);
    } else if (level === "arc") {
      return api.generateArcsStream(project.id, parentId!, count, customPrompt);
    } else {
      if (chapterMode === "by_volume") {
        return api.generateChaptersByVolumeStream(project.id, volumeId!, count, customPrompt);
      } else {
        return api.generateChaptersStream(project.id, parentId!, count, customPrompt);
      }
    }
  };

  // 流式生成完成/导入后刷新列表
  const handleStreamImport = async (_items: GenStreamItem[]) => {
    await load();
    if (_items.length > 0) showSuccess(`已导入 ${_items.length} 条${title}`);
  };

  const discardGenerated = async (items: Outline[]) => {
    await Promise.all(items.map((item) => item.id ? api.deleteOutline(project.id, item.id) : Promise.resolve()));
  };

  const handleRenumber = async () => {
    if (level === "chapter" && chapterMode === "by_volume") return;
    const ok = await confirmDelete({
      title: "重新编号？",
      description: "将所有大纲按当前顺序重新编号为 1, 2, 3...，修复跳号问题。",
    });
    if (!ok) return;
    try {
      const pid = level === "arc" ? parentId : level === "chapter" && chapterMode === "by_arc" ? parentId : undefined;
      const r = await api.renumberOutlines(project.id, level, pid ?? undefined);
      if (r.renumbered > 0) {
        showSuccess(`已重新编号 ${r.renumbered} 条（共 ${r.total} 条），编号已连续`);
      } else {
        showSuccess(`编号已连续，无需调整（共 ${r.total} 条）`);
      }
      await load();
    } catch (e: any) {
      showError("重新编号失败：" + e.message);
    }
  };

  const doGenerate = async (prompt: string): Promise<{ created: number; items: Partial<Outline>[]; warning?: string }> => {
    if (level === "volume") {
      return await api.generateVolumes(project.id, count, prompt);
    } else if (level === "arc") {
      if (!parentId) throw new Error("请先选择所属卷");
      return await api.generateArcs(project.id, parentId, count, prompt);
    } else {
      // 章纲：按细纲 or 按卷纲
      if (chapterMode === "by_volume") {
        if (!volumeId) throw new Error("请先选择所属卷");
        return await api.generateChaptersByVolume(project.id, volumeId, count, prompt);
      } else {
        if (!parentId) throw new Error("请先选择所属细纲");
        return await api.generateChapters(project.id, parentId, count, prompt);
      }
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
        if (r.warning) showError(r.warning);
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
      setNewForm({ order: (sorted.length || 0) + 1, level, parent_id: parentId, title: "", summary: "", act: "发展", strand: "quest", required_beats: "", owed_debts: "", required_hooks: "", character_constraints: "", phase: "regular" });
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

  const toggleSelect = (id: number) => {
    setSelectedIds((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  };

  const toggleSelectAll = () => {
    if (selectedIds.size === sorted.length) {
      setSelectedIds(new Set());
    } else {
      setSelectedIds(new Set(sorted.map((item) => item.id)));
    }
  };

  const handleBatchDelete = async () => {
    if (selectedIds.size === 0) return;
    const ok = await confirmDelete({
      title: `确认批量删除？`,
      description: `将删除 ${selectedIds.size} 条${title}及其所有子级，且无法恢复。`,
      variant: "danger",
    });
    if (!ok) return;
    try {
      const ids = Array.from(selectedIds);
      const result = await api.batchDeleteOutlines(project.id, ids);
      setSelectedIds(new Set());
      setBatchMode(false);
      await load();
      showSuccess(`已删除 ${result.deleted_count} 条${title}`);
    } catch (e: any) {
      showError("批量删除失败：" + e.message);
    }
  };

  const [enrichingId, setEnrichingId] = useState<number | null>(null);
  const handleEnrich = async (id: number) => {
    setEnrichingId(id);
    try {
      await api.enrichOutline(project.id, id);
      await load();
      showSuccess("大纲内容已丰富");
    } catch (e: any) {
      showError("丰富失败：" + e.message);
    } finally {
      setEnrichingId(null);
    }
  };

  const levelBadge = {
    volume: "卷",
    arc: "细纲",
    chapter: "章纲",
  };

  const renderItemContent = (item: Outline) => {
    if (editingId === item.id) {
      return (
        <div className="space-y-2">
          <div className="flex flex-wrap gap-2">
            <Input type="number" className="w-20" value={editForm.order} onChange={(e) => setEditForm({ ...editForm, order: Number(e.target.value) })} />
            <Input className="flex-1 min-w-[140px]" value={editForm.title} onChange={(e) => setEditForm({ ...editForm, title: e.target.value })} />
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
          <Textarea placeholder="必备节拍（required_beats）" value={editForm.required_beats || ""} onChange={(e) => setEditForm({ ...editForm, required_beats: e.target.value })} />
          <Textarea placeholder="欠账/待回收（owed_debts）" value={editForm.owed_debts || ""} onChange={(e) => setEditForm({ ...editForm, owed_debts: e.target.value })} />
          <Textarea placeholder="必备钩子（required_hooks）" value={editForm.required_hooks || ""} onChange={(e) => setEditForm({ ...editForm, required_hooks: e.target.value })} />
          <Textarea placeholder="角色约束（character_constraints）" value={editForm.character_constraints || ""} onChange={(e) => setEditForm({ ...editForm, character_constraints: e.target.value })} />
          <div className="flex gap-2 justify-end">
            <Button size="sm" variant="ghost" onClick={cancelEdit}><X className="h-4 w-4 mr-1" /> 取消</Button>
            <Button size="sm" variant="primary" onClick={saveEdit}><Save className="h-4 w-4 mr-1" /> 保存</Button>
          </div>
        </div>
      );
    }
    return (
      <div className="flex items-start gap-3">
        {batchMode && (
          <button onClick={() => toggleSelect(item.id)} className="mt-1 shrink-0">
            {selectedIds.has(item.id)
              ? <CheckSquare className="h-4 w-4 text-primary" />
              : <Square className="h-4 w-4 text-muted" />}
          </button>
        )}
        <Badge variant="default" className="mt-0.5">{levelBadge[item.level]}</Badge>
        <div className="flex-1 min-w-0">
          <div className="font-medium text-sm">
            {item.order}. {item.title}
            {item.act && <span className="text-xs text-muted ml-2">[{item.act}]</span>}
            {item.strand && <span className="text-xs text-muted ml-2">({STRANDS.find((s) => s.value === item.strand)?.label || item.strand})</span>}
          </div>
          <div className="text-xs text-muted mt-1 whitespace-pre-wrap">{item.summary}</div>
          {item.phase && item.phase !== "regular" && (
            <span className="text-xs text-muted ml-1">阶段：{item.phase === "opening" ? "开局" : "上架"}</span>
          )}
          {item.required_beats && <div className="text-xs text-muted mt-1 whitespace-pre-wrap"><span className="text-foreground/70">必备节拍：</span>{item.required_beats}</div>}
          {item.owed_debts && <div className="text-xs text-muted mt-1 whitespace-pre-wrap"><span className="text-foreground/70">欠账/待回收：</span>{item.owed_debts}</div>}
          {item.required_hooks && <div className="text-xs text-muted mt-1 whitespace-pre-wrap"><span className="text-foreground/70">必备钩子：</span>{item.required_hooks}</div>}
          {item.character_constraints && <div className="text-xs text-muted mt-1 whitespace-pre-wrap"><span className="text-foreground/70">角色约束：</span>{item.character_constraints}</div>}
        </div>
        <div className="flex gap-1">
          <Button size="sm" variant="ghost" className="h-8 px-2" onClick={() => handleEnrich(item.id)} disabled={enrichingId === item.id} title="AI丰富详情">
            {enrichingId === item.id ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <Sparkles className="h-3.5 w-3.5" />}
          </Button>
          <Button size="sm" variant="ghost" className="h-8 w-8 px-0" onClick={() => startEdit(item)}><Edit2 className="h-3.5 w-3.5" /></Button>
          <Button size="sm" variant="ghost" className="h-8 w-8 px-0" onClick={() => handleDelete(item.id)}><Trash2 className="h-3.5 w-3.5" /></Button>
        </div>
      </div>
    );
  };

  return (
    <>
      <GenerationStreamDialog
        open={streamOpen}
        title={title}
        type={streamType}
        createSource={createStreamSource}
        onClose={() => setStreamOpen(false)}
        onImport={handleStreamImport}
      />
      <Card className="flex-1 flex flex-col min-h-0">
      <CardHeader className="pb-2">
        <CardTitle className="text-base flex items-center gap-2">
          <List className="h-4 w-4" />
          {title}
        </CardTitle>
      </CardHeader>
      <CardContent className={level === "chapter" ? "flex-1 flex flex-col min-h-0 space-y-3" : "flex-1 overflow-y-auto space-y-3"}>
        <div className="flex flex-wrap items-center gap-2">
          {level === "chapter" && (
            <Select
              className="min-w-[120px]"
              value={chapterMode}
              onChange={(e) => { setChapterMode(e.target.value as "by_arc" | "by_volume"); setParentId(null); }}
            >
              <option value="by_arc">按细纲生成</option>
              <option value="by_volume">按卷纲生成</option>
            </Select>
          )}
          {level === "chapter" && chapterMode === "by_volume" ? (
            <Select
              className="min-w-[160px]"
              value={volumeId ?? ""}
              onChange={(e) => setVolumeId(e.target.value ? Number(e.target.value) : null)}
            >
              <option value="">选择卷</option>
              {volumes.map((v) => (
                <option key={v.id} value={v.id}>
                  {v.order}. {v.title}
                </option>
              ))}
            </Select>
          ) : level === "chapter" && chapterMode === "by_arc" ? (
            <>
              <Select
                className="min-w-[160px]"
                value={volumeId ?? ""}
                onChange={(e) => {
                  const v = e.target.value ? Number(e.target.value) : null;
                  setVolumeId(v);
                  setParentId(null);
                }}
              >
                <option value="">选择卷</option>
                {volumes.map((v) => (
                  <option key={v.id} value={v.id}>
                    {v.order}. {v.title}
                  </option>
                ))}
              </Select>
              <Select
                className="min-w-[200px]"
                value={parentId ?? ""}
                onChange={(e) => setParentId(e.target.value ? Number(e.target.value) : null)}
                disabled={!volumeId}
              >
                <option value="">选择细纲</option>
                {parents.map((p) => (
                  <option key={p.id} value={p.id}>
                    {p.order}. {p.title}
                  </option>
                ))}
              </Select>
            </>
          ) : parentLevel ? (
            <Select
              className="min-w-[200px]"
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
          ) : null}
          <Input type="number" className="w-20" value={count} onChange={(e) => setCount(Number(e.target.value))} />
          <span className="text-xs text-muted">{count === 0 ? "自动" : "条"}</span>
          <Input className="flex-1 min-w-[200px]" placeholder="自定义要求（可选）" value={customPrompt} onChange={(e) => setCustomPrompt(e.target.value)} />
          <Button variant="primary" onClick={handleGenerate} disabled={level === "chapter" && chapterMode === "by_volume" ? !volumeId : parentLevel ? !parentId : false}>
            <Sparkles className="h-3.5 w-3.5 mr-1" />
            {`AI 生成${title}`}
          </Button>
          <Button variant="outline" onClick={() => setSuggestOpen(true)} disabled={level === "chapter" && chapterMode === "by_volume" ? !volumeId : parentLevel ? !parentId : false}>
            <Sparkles className="h-3.5 w-3.5 mr-1" />
            AI 建议后续
          </Button>
          <Button size="sm" variant="ghost" onClick={() => setAdding(!adding)}>
            <Plus className="h-4 w-4 mr-1" /> 手动添加
          </Button>
          <Button size="sm" variant="ghost" onClick={handleRenumber} disabled={items.length === 0}>
            <Hash className="h-4 w-4 mr-1" /> 重新编号
          </Button>
          <Button size="sm" variant={batchMode ? "primary" : "ghost"} onClick={() => { setBatchMode(!batchMode); setSelectedIds(new Set()); }}>
            <CheckSquare className="h-4 w-4 mr-1" /> 批量
          </Button>
          {batchMode && sorted.length > 0 && (
            <>
              <Button size="sm" variant="ghost" onClick={toggleSelectAll}>
                {selectedIds.size === sorted.length ? "取消全选" : "全选"}
              </Button>
              {selectedIds.size > 0 && (
                <Button size="sm" variant="danger" onClick={handleBatchDelete}>
                  <Trash2 className="h-3.5 w-3.5 mr-1" /> 删除选中({selectedIds.size})
                </Button>
              )}
            </>
          )}
        </div>

        {adding && (
          <div className="space-y-2 border border-border rounded-xl p-3">
            <div className="flex flex-wrap gap-2">
              <Input type="number" className="w-20" placeholder="顺序" value={newForm.order} onChange={(e) => setNewForm({ ...newForm, order: Number(e.target.value) })} />
              <Input className="flex-1 min-w-[140px]" placeholder="标题" value={newForm.title} onChange={(e) => setNewForm({ ...newForm, title: e.target.value })} />
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
            <Textarea placeholder="必备节拍（required_beats）" value={newForm.required_beats || ""} onChange={(e) => setNewForm({ ...newForm, required_beats: e.target.value })} />
            <Textarea placeholder="欠账/待回收（owed_debts）" value={newForm.owed_debts || ""} onChange={(e) => setNewForm({ ...newForm, owed_debts: e.target.value })} />
            <Textarea placeholder="必备钩子（required_hooks）" value={newForm.required_hooks || ""} onChange={(e) => setNewForm({ ...newForm, required_hooks: e.target.value })} />
            <Textarea placeholder="角色约束（character_constraints）" value={newForm.character_constraints || ""} onChange={(e) => setNewForm({ ...newForm, character_constraints: e.target.value })} />
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
        ) : level === "chapter" ? (
          <div ref={scrollRef} className="flex-1 min-h-0 overflow-y-auto">
            <div style={{ height: virtualizer.getTotalSize(), position: "relative", width: "100%" }}>
              {virtualizer.getVirtualItems().map((vi) => {
                const item = sorted[vi.index];
                return (
                  <div
                    key={item.id}
                    ref={virtualizer.measureElement}
                    data-index={vi.index}
                    style={{ position: "absolute", top: 0, left: 0, width: "100%", transform: `translateY(${vi.start}px)`, paddingBottom: 8 }}
                  >
                    <div className="border border-border rounded-xl p-3 hover:border-primary/30 transition-colors">
                      {renderItemContent(item)}
                    </div>
                  </div>
                );
              })}
            </div>
          </div>
        ) : (
          <div className="space-y-2">
            {sorted.map((item) => (
              <div key={item.id} className="border border-border rounded-xl p-3 hover:border-primary/30 transition-colors">
                {renderItemContent(item)}
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
    </>
  );
}
