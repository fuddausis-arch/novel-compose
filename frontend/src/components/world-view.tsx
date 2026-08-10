import { useEffect, useMemo, useState } from "react";
import { Globe, Plus, Sparkles, Trash2, Save, X, Edit2 } from "lucide-react";
import { api } from "@/api";
import { useToast } from "@/hooks/useToast";
import { useConfirmDialog } from "@/hooks/useConfirmDialog";
import type { Project, WorldSetting } from "@/types";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Textarea } from "@/components/ui/textarea";
import { Select } from "@/components/ui/select";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { AiPreviewDialog } from "@/components/ai-preview-dialog";
import { AiSuggestionDialog } from "@/components/ai-suggestion-dialog";
import { GenerationStreamDialog, type GenStreamItem } from "@/components/generation-stream-dialog";

interface WorldViewProps {
  project: Project | null;
  worldSettings: WorldSetting[];
  refresh: () => Promise<void>;
  setLoading?: (loading: boolean) => void;
}

const MULTI_LAYER_GENRES = ["都市异能", "规则怪谈", "悬疑脑洞", "无限流", "科幻未来"];

function getCategoriesForGenre(genre: string | undefined): string[] {
  const base = ["世界观", "力量体系", "势力", "地点", "规则", "历史", "其他"];
  if (genre && MULTI_LAYER_GENRES.some(g => genre.includes(g))) {
    return ["世界观", "现实层", "力量体系", "异能层", "势力", "地点", "规则", "历史", "神明层", "其他"];
  }
  return base;
}

function getDefaultRequirements(genre: string | undefined): string {
  if (genre && MULTI_LAYER_GENRES.some(g => genre.includes(g))) {
    return "设计多层世界观：现实层、异能层、神明层";
  }
  return "设计完整世界观：世界观、力量体系、势力、地点、规则、历史";
}

export function WorldView({ project, worldSettings, refresh }: WorldViewProps) {
  if (!project) {
    return (
      <div className="flex-1 flex items-center justify-center text-muted text-sm">
        请先选择或创建一个项目
      </div>
    );
  }

  const { showSuccess, showError } = useToast();
  const { confirm: confirmDelete, dialog: deleteDialog } = useConfirmDialog();
  // CATEGORIES 按题材动态推导（修真题材不加"异能层"，避免串味）
  const CATEGORIES = useMemo(() => getCategoriesForGenre(project?.genre), [project?.genre]);
  const [requirements, setRequirements] = useState(() => getDefaultRequirements(project?.genre));
  // 切换项目时同步默认 requirements
  useEffect(() => {
    setRequirements(getDefaultRequirements(project?.genre));
  }, [project?.genre]);
  const [style, setStyle] = useState(project.style || "热血");

  const [adding, setAdding] = useState(false);
  const [newForm, setNewForm] = useState<Partial<WorldSetting>>({
    category: "世界观",
    title: "",
    content: "",
  });

  const [editingId, setEditingId] = useState<number | null>(null);
  const [editForm, setEditForm] = useState<Partial<WorldSetting>>({});

  const [previewOpen, setPreviewOpen] = useState(false);
  const [previewItems, setPreviewItems] = useState<Partial<WorldSetting>[]>([]);
  const [suggestOpen, setSuggestOpen] = useState(false);
  const [streamOpen, setStreamOpen] = useState(false);

  const grouped = useMemo(() => {
    const map = new Map<string, WorldSetting[]>();
    CATEGORIES.forEach((c) => map.set(c, []));
    worldSettings.forEach((s) => {
      const list = map.get(s.category) || [];
      list.push(s);
      map.set(s.category, list);
    });
    return Array.from(map.entries()).filter(([, list]) => list.length > 0);
  }, [worldSettings, CATEGORIES]);

  const handleGenerate = async () => {
    setStreamOpen(true);
  };

  // 流式生成：创建 EventSource
  const createStreamSource = () => api.generateWorldStream(project.id, requirements, style);

  // 流式生成完成/导入后：逐条导入世界观
  const handleStreamImport = async (items: GenStreamItem[]) => {
    try {
      await api.importWorld(project.id, items as any[]);
      await refresh();
      showSuccess(`已导入 ${items.length} 条世界观设定`);
    } catch (e: any) {
      showError("导入失败：" + e.message);
    }
  };

  // 单条导入
  const handleStreamImportOne = async (item: GenStreamItem) => {
    try {
      await api.importWorld(project.id, [item as any]);
      await refresh();
      showSuccess(`已导入：${item.title || "未命名"}`);
    } catch (e: any) {
      showError("导入失败：" + e.message);
    }
  };

  const handleImport = async (selected: Partial<WorldSetting>[]) => {
    try {
      await api.importWorld(project.id, selected as any[]);
      await refresh();
      setPreviewOpen(false);
      setPreviewItems([]);
      showSuccess(`已导入 ${selected.length} 条世界观设定`);
    } catch (e: any) {
      showError("导入失败：" + e.message);
    }
  };

  const handlePreviewClose = async () => {
    setPreviewOpen(false);
    setPreviewItems([]);
  };

  const handleCreate = async () => {
    try {
      await api.createWorldSetting(project.id, {
        category: newForm.category || "其他",
        title: newForm.title || "未命名",
        content: newForm.content || "",
        order: worldSettings.length,
      });
      setAdding(false);
      setNewForm({ category: "世界观", title: "", content: "" });
      await refresh();
      showSuccess("已添加");
    } catch (e: any) {
      showError("添加失败：" + e.message);
    }
  };

  const startEdit = (s: WorldSetting) => {
    setEditingId(s.id);
    setEditForm({ ...s });
  };

  const handleUpdate = async () => {
    if (!editingId) return;
    try {
      await api.updateWorldSetting(project.id, editingId, editForm);
      setEditingId(null);
      await refresh();
      showSuccess("已保存");
    } catch (e: any) {
      showError("保存失败：" + e.message);
    }
  };

  const handleDelete = async (id: number) => {
    const setting = worldSettings.find((s) => s.id === id);
    const confirmed = await confirmDelete({
      title: "删除世界观设定",
      description: `确定删除设定「${setting?.title || id}」吗？此操作不可恢复。`,
      confirmText: "删除",
      cancelText: "取消",
      variant: "danger",
    });
    if (!confirmed) return;
    try {
      await api.deleteWorldSetting(project.id, id);
      await refresh();
      showSuccess("已删除");
    } catch (e: any) {
      showError("删除失败：" + e.message);
    }
  };

  return (
    <div className="flex-1 flex flex-col gap-3 min-h-0 overflow-hidden">
      <GenerationStreamDialog
        open={streamOpen}
        title="世界观"
        type="world"
        createSource={createStreamSource}
        onClose={() => setStreamOpen(false)}
        onImport={handleStreamImport}
        onImportOne={handleStreamImportOne}
      />
      <Card>
        <CardHeader>
          <div className="flex items-center justify-between">
            <CardTitle className="flex items-center gap-2">
              <Globe className="h-4 w-4 text-primary" />
              世界观引擎
            </CardTitle>
            <Button size="sm" onClick={() => setAdding(!adding)}>
              <Plus className="h-3.5 w-3.5 mr-1" /> 新增设定
            </Button>
            <Button size="sm" variant="default" onClick={() => setSuggestOpen(true)}>
              <Sparkles className="h-3.5 w-3.5 mr-1" /> AI 建议
            </Button>
          </div>
        </CardHeader>
        <CardContent className="space-y-3">
          <div className="flex flex-wrap gap-2">
            <Input
              className="flex-1 min-w-[200px]"
              placeholder="生成要求，例如：设计现实层/异能层/神明层三层体系"
              value={requirements}
              onChange={(e) => setRequirements(e.target.value)}
            />
            <Input
              className="w-32"
              placeholder="风格"
              value={style}
              onChange={(e) => setStyle(e.target.value)}
            />
            <Button variant="primary" onClick={handleGenerate}>
              <Sparkles className="h-3.5 w-3.5 mr-1" />
              AI 生成世界观
            </Button>
          </div>

          {adding && (
            <div className="space-y-2 border border-border rounded-xl p-3">
              <div className="flex gap-2">
                <Select value={newForm.category} onChange={(e) => setNewForm({ ...newForm, category: e.target.value })}>
                  {CATEGORIES.map((c) => (
                    <option key={c} value={c}>{c}</option>
                  ))}
                </Select>
                <Input placeholder="标题" value={newForm.title} onChange={(e) => setNewForm({ ...newForm, title: e.target.value })} />
              </div>
              <Textarea placeholder="内容" value={newForm.content} onChange={(e) => setNewForm({ ...newForm, content: e.target.value })} />
              <div className="flex gap-2">
                <Button size="sm" onClick={handleCreate}>保存</Button>
                <Button size="sm" variant="ghost" onClick={() => setAdding(false)}>取消</Button>
              </div>
            </div>
          )}
        </CardContent>
      </Card>

      <div className="flex-1 overflow-y-auto space-y-3 pr-1">
        {grouped.length === 0 && (
          <div className="text-center text-sm text-muted py-10">暂无世界观设定，点击上方 AI 生成或手动添加。</div>
        )}
        {grouped.map(([category, list]) => (
          <Card key={category}>
            <CardHeader>
              <CardTitle className="text-sm flex items-center gap-2">
                <Badge>{category}</Badge>
                <span className="text-muted text-xs">{list.length} 条</span>
              </CardTitle>
            </CardHeader>
            <CardContent className="space-y-2">
              {list.map((s) => (
                <div key={s.id} className="rounded-xl border border-border bg-surface p-3">
                  {editingId === s.id ? (
                    <div className="space-y-2">
                      <div className="flex gap-2">
                        <Select value={editForm.category} onChange={(e) => setEditForm({ ...editForm, category: e.target.value })}>
                          {CATEGORIES.map((c) => (
                            <option key={c} value={c}>{c}</option>
                          ))}
                        </Select>
                        <Input value={editForm.title} onChange={(e) => setEditForm({ ...editForm, title: e.target.value })} />
                      </div>
                      <Textarea value={editForm.content} onChange={(e) => setEditForm({ ...editForm, content: e.target.value })} />
                      <div className="flex gap-2">
                        <Button size="sm" onClick={handleUpdate}><Save className="h-3.5 w-3.5 mr-1" /> 保存</Button>
                        <Button size="sm" variant="ghost" onClick={() => setEditingId(null)}><X className="h-3.5 w-3.5 mr-1" /> 取消</Button>
                      </div>
                    </div>
                  ) : (
                    <div>
                      <div className="flex items-start justify-between gap-2">
                        <h4 className="font-medium text-foreground">{s.title}</h4>
                        <div className="flex items-center gap-1">
                          <button onClick={() => startEdit(s)} className="p-1 hover:bg-foreground/5 rounded"><Edit2 className="h-3.5 w-3.5 text-muted" /></button>
                          <button onClick={() => handleDelete(s.id)} className="p-1 hover:bg-foreground/5 rounded"><Trash2 className="h-3.5 w-3.5 text-danger" /></button>
                        </div>
                      </div>
                      <p className="text-sm text-muted mt-1 whitespace-pre-wrap">{s.content}</p>
                    </div>
                  )}
                </div>
              ))}
            </CardContent>
          </Card>
        ))}
      </div>

      {deleteDialog}

      <AiPreviewDialog
        open={previewOpen}
        title="AI 生成的世界观设定"
        items={previewItems}
        getKey={(item) => String(item.id)}
        renderItem={(item) => (
          <div>
            <div className="flex items-center gap-2">
              <Badge>{item.category}</Badge>
              <span className="font-medium">{item.title}</span>
            </div>
            <p className="text-sm text-muted mt-1 whitespace-pre-wrap line-clamp-6">{item.content}</p>
          </div>
        )}
        onClose={handlePreviewClose}
        onImport={handleImport}
      />

      <AiSuggestionDialog
        open={suggestOpen}
        project={project}
        contextType="world"
        contextId=""
        defaultSuggestType="world"
        onClose={() => setSuggestOpen(false)}
        onAdopted={() => { refresh(); showSuccess("建议已采纳"); }}
      />
    </div>
  );
}
