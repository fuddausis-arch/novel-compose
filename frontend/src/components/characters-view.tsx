import { useState } from "react";
import { Users, Plus, Sparkles, Trash2, Save, X, Edit2 } from "lucide-react";
import { api } from "@/api";
import { useToast } from "@/hooks/useToast";
import { useConfirmDialog } from "@/hooks/useConfirmDialog";
import { AppearanceManager } from "@/components/entity/appearance-manager";
import type { Project, Character } from "@/types";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Textarea } from "@/components/ui/textarea";
import { Select } from "@/components/ui/select";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { AiPreviewDialog } from "@/components/ai-preview-dialog";
import { AiSuggestionDialog } from "@/components/ai-suggestion-dialog";
import { GenerationStreamDialog, type GenStreamItem } from "@/components/generation-stream-dialog";
import { TagWeightFields } from "@/components/ui/tag-weight-fields";

interface CharactersViewProps {
  project: Project | null;
  characters: Character[];
  refresh: () => Promise<void>;
  setLoading?: (loading: boolean) => void;
}

const ROLES = ["主角", "配角", "反派"];

export function CharactersView({ project, characters, refresh }: CharactersViewProps) {
  if (!project) {
    return (
      <div className="flex-1 flex items-center justify-center text-muted text-sm">
        请先选择或创建一个项目
      </div>
    );
  }

  const { showSuccess, showError } = useToast();
  const { confirm: confirmDelete, dialog: deleteDialog } = useConfirmDialog();
  const [protagonistCount, setProtagonistCount] = useState(1);
  const [supportingCount, setSupportingCount] = useState(3);
  const [antagonistCount, setAntagonistCount] = useState(2);
  const [style, setStyle] = useState(project.style || "热血");

  const [adding, setAdding] = useState(false);
  const [newForm, setNewForm] = useState<Partial<Character>>({ name: "", role: "配角" });

  const [editingId, setEditingId] = useState<number | null>(null);
  const [editForm, setEditForm] = useState<Partial<Character>>({});

  const [previewOpen, setPreviewOpen] = useState(false);
  const [previewItems, setPreviewItems] = useState<Partial<Character>[]>([]);
  const [suggestOpen, setSuggestOpen] = useState(false);
  const [streamOpen, setStreamOpen] = useState(false);
  const [generatingChar, setGeneratingChar] = useState(false);

  // 单条 AI 生成：调用 /generate-character 生成新角色并填入当前编辑表单
  const handleGenerateOne = async () => {
    if (!editingId) return;
    setGeneratingChar(true);
    try {
      const created = await api.generateCharacter(project.id, {
        name_hint: editForm.name || "",
        role_hint: editForm.role || "",
        importance_hint: editForm.importance || "",
      });
      setEditForm({ ...editForm, ...created });
      showSuccess("AI 已生成角色设定，已填入表单，点击「保存」生效");
    } catch (e: any) {
      showError("AI 生成失败：" + e.message);
    } finally {
      setGeneratingChar(false);
    }
  };

  const handleGenerate = async () => {
    setStreamOpen(true);
  };

  // 流式生成：创建 EventSource
  const createStreamSource = () => api.generateCharactersStream(project.id, protagonistCount, supportingCount, antagonistCount, style);

  // 流式生成完成/导入后：逐条导入角色
  const handleStreamImport = async (items: GenStreamItem[]) => {
    try {
      await api.importCharacters(project.id, items as any[]);
      await refresh();
      showSuccess(`已导入 ${items.length} 位角色`);
    } catch (e: any) {
      showError("导入失败：" + e.message);
    }
  };

  // 单条导入
  const handleStreamImportOne = async (item: GenStreamItem) => {
    try {
      await api.importCharacters(project.id, [item as any]);
      await refresh();
      showSuccess(`已导入：${item.name || "未命名"}`);
    } catch (e: any) {
      showError("导入失败：" + e.message);
    }
  };

  const handleImport = async (selected: Partial<Character>[]) => {
    try {
      await api.importCharacters(project.id, selected as any[]);
      await refresh();
      setPreviewOpen(false);
      setPreviewItems([]);
      showSuccess(`已导入 ${selected.length} 位角色`);
    } catch (e: any) {
      showError("导入失败：" + e.message);
    }
  };

  const handlePreviewClose = async () => {
    setPreviewOpen(false);
    setPreviewItems([]);
  };

  const handleCreate = async () => {
    if (!(newForm.name ?? "").trim()) {
      showError("请输入角色姓名");
      return;
    }
    try {
      await api.createCharacter(project.id, {
        name: (newForm.name ?? "").trim(),
        role: newForm.role || "配角",
      });
      setAdding(false);
      setNewForm({ name: "", role: "配角" });
      await refresh();
      showSuccess("已添加角色");
    } catch (e: any) {
      showError("添加失败：" + e.message);
    }
  };

  const startEdit = (c: Character) => {
    setEditingId(c.id);
    setEditForm({ ...c });
  };

  const handleUpdate = async () => {
    if (!editingId) return;
    try {
      const target = characters.find((c) => c.id === editingId);
      if (!target) return;
      await api.updateCharacter(project.id, target.id, editForm);
      setEditingId(null);
      await refresh();
      showSuccess("已保存");
    } catch (e: any) {
      showError("保存失败：" + e.message);
    }
  };

  const handleDelete = async (c: Character) => {
    const confirmed = await confirmDelete({
      title: "删除角色",
      description: `确定删除角色「${c.name}」吗？此操作不可恢复。`,
      confirmText: "删除",
      cancelText: "取消",
      variant: "danger",
    });
    if (!confirmed) return;
    try {
      await api.deleteCharacter(project.id, c.id);
      await refresh();
      showSuccess("已删除");
    } catch (e: any) {
      showError("删除失败：" + e.message);
    }
  };

  const roleBadge = (role: string) => {
    if (role === "主角") return "text-primary border-primary";
    if (role === "反派") return "text-danger border-danger";
    return "text-muted border-border-strong";
  };

  const fields: { key: keyof Character; label: string; rows?: number }[] = [
    { key: "name", label: "姓名" },
    { key: "role", label: "身份" },
    { key: "age", label: "年龄" },
    { key: "gender", label: "性别" },
    { key: "appearance", label: "外貌", rows: 2 },
    { key: "personality", label: "性格", rows: 2 },
    { key: "motivation", label: "动机", rows: 2 },
    { key: "background", label: "背景", rows: 2 },
    { key: "arc", label: "角色弧线", rows: 2 },
    { key: "language_style", label: "语言风格/台词", rows: 3 },
    { key: "combat_style", label: "战斗风格", rows: 3 },
    { key: "growth_curve", label: "成长曲线", rows: 3 },
    { key: "emotional_anchor", label: "情感锚点", rows: 2 },
    { key: "relationships", label: "关系", rows: 2 },
    { key: "secrets", label: "秘密", rows: 2 },
  ];

  return (
    <div className="flex-1 flex flex-col gap-3 min-h-0 overflow-hidden">
      <GenerationStreamDialog
        open={streamOpen}
        title="角色"
        type="character"
        createSource={createStreamSource}
        onClose={() => setStreamOpen(false)}
        onImport={handleStreamImport}
        onImportOne={handleStreamImportOne}
      />
      <Card>
        <CardHeader>
          <div className="flex items-center justify-between">
            <CardTitle className="flex items-center gap-2">
              <Users className="h-4 w-4 text-primary" />
              角色工坊
            </CardTitle>
            <Button size="sm" onClick={() => setAdding(!adding)}>
              <Plus className="h-3.5 w-3.5 mr-1" /> 新增角色
            </Button>
            <Button size="sm" variant="default" onClick={() => setSuggestOpen(true)}>
              <Sparkles className="h-3.5 w-3.5 mr-1" /> AI 建议
            </Button>
          </div>
        </CardHeader>
        <CardContent className="space-y-3">
          <div className="flex flex-wrap items-center gap-2">
            <Input type="number" className="w-20" value={protagonistCount} onChange={(e) => setProtagonistCount(Number(e.target.value))} />
            <span className="text-xs text-muted">主角</span>
            <Input type="number" className="w-20" value={supportingCount} onChange={(e) => setSupportingCount(Number(e.target.value))} />
            <span className="text-xs text-muted">配角</span>
            <Input type="number" className="w-20" value={antagonistCount} onChange={(e) => setAntagonistCount(Number(e.target.value))} />
            <span className="text-xs text-muted">反派</span>
            <Input className="w-32" placeholder="风格" value={style} onChange={(e) => setStyle(e.target.value)} />
            <Button variant="primary" onClick={handleGenerate}>
              <Sparkles className="h-3.5 w-3.5 mr-1" />
              AI 生成角色
            </Button>
          </div>

          {adding && (
            <div className="flex gap-2 border border-border rounded-xl p-3">
              <Input placeholder="姓名" value={newForm.name} onChange={(e) => setNewForm({ ...newForm, name: e.target.value })} />
              <Select value={newForm.role} onChange={(e) => setNewForm({ ...newForm, role: e.target.value })}>
                {ROLES.map((r) => (
                  <option key={r} value={r}>{r}</option>
                ))}
              </Select>
              <Button size="sm" onClick={handleCreate} disabled={!(newForm.name ?? "").trim()} title={(newForm.name ?? "").trim() ? "" : "请输入角色姓名"}>保存</Button>
              <Button size="sm" variant="ghost" onClick={() => setAdding(false)}>取消</Button>
            </div>
          )}
        </CardContent>
      </Card>

      <div className="flex-1 overflow-y-auto space-y-3 pr-1">
        {characters.length === 0 && (
          <div className="text-center text-sm text-muted py-10">暂无角色，点击上方 AI 生成或手动添加。</div>
        )}
        {characters.map((c) => (
          <Card key={c.id}>
            <CardContent className="p-3">
              {editingId === c.id ? (
                <div className="space-y-2">
                  <div className="grid grid-cols-2 md:grid-cols-4 gap-2">
                    <Input value={editForm.name} onChange={(e) => setEditForm({ ...editForm, name: e.target.value })} placeholder="姓名" />
                    <Select value={editForm.role} onChange={(e) => setEditForm({ ...editForm, role: e.target.value })}>
                      {ROLES.map((r) => (
                        <option key={r} value={r}>{r}</option>
                      ))}
                    </Select>
                    <Input value={editForm.age} onChange={(e) => setEditForm({ ...editForm, age: e.target.value })} placeholder="年龄" />
                    <Input value={editForm.gender} onChange={(e) => setEditForm({ ...editForm, gender: e.target.value })} placeholder="性别" />
                  </div>
                  {fields.slice(4).map((f) => (
                    <Textarea
                      key={f.key}
                      placeholder={f.label}
                      rows={f.rows}
                      value={(editForm[f.key] as string) || ""}
                      onChange={(e) => setEditForm({ ...editForm, [f.key]: e.target.value })}
                    />
                  ))}
                  <TagWeightFields
                    tags={(editForm.tags || []) as string[]}
                    weight={editForm.weight ?? 50}
                    onTags={(t) => setEditForm({ ...editForm, tags: t })}
                    onWeight={(w) => setEditForm({ ...editForm, weight: w })}
                  />
                  <div className="flex gap-2">
                    <Button size="sm" variant="primary" onClick={handleGenerateOne} disabled={generatingChar}>
                      <Sparkles className="h-3.5 w-3.5 mr-1" />
                      {generatingChar ? "生成中…" : "AI 生成"}
                    </Button>
                    <Button size="sm" onClick={handleUpdate}><Save className="h-3.5 w-3.5 mr-1" /> 保存</Button>
                    <Button size="sm" variant="ghost" onClick={() => setEditingId(null)}><X className="h-3.5 w-3.5 mr-1" /> 取消</Button>
                  </div>
                  <div className="rounded-lg border border-border p-3">
                    <AppearanceManager projectId={project.id} entityType="character" entityId={String(c.id)} />
                  </div>
                </div>
              ) : (
                <div>
                  <div className="flex items-start justify-between gap-2">
                    <div className="flex items-center gap-2">
                      <h4 className="font-medium text-foreground">{c.name}</h4>
                      <Badge className={roleBadge(c.role)}>{c.role || "配角"}</Badge>
                      {(c.age || c.gender) && (
                        <span className="text-xs text-muted">{c.age} {c.gender}</span>
                      )}
                    </div>
                    <div className="flex items-center gap-1">
                      <button onClick={() => startEdit(c)} className="p-1 hover:bg-foreground/5 rounded"><Edit2 className="h-3.5 w-3.5 text-muted" /></button>
                      <button onClick={() => handleDelete(c)} className="p-1 hover:bg-foreground/5 rounded"><Trash2 className="h-3.5 w-3.5 text-danger" /></button>
                    </div>
                  </div>
                  <div className="mt-2 grid grid-cols-1 md:grid-cols-2 gap-2 text-xs text-muted">
                    {c.appearance && <p><span className="text-foreground">外貌：</span>{c.appearance}</p>}
                    {c.personality && <p><span className="text-foreground">性格：</span>{c.personality}</p>}
                    {c.motivation && <p><span className="text-foreground">动机：</span>{c.motivation}</p>}
                    {c.background && <p><span className="text-foreground">背景：</span>{c.background}</p>}
                    {c.arc && <p><span className="text-foreground">弧线：</span>{c.arc}</p>}
                    {c.language_style && <p><span className="text-foreground">语言风格：</span>{c.language_style}</p>}
                    {c.combat_style && <p><span className="text-foreground">战斗风格：</span>{c.combat_style}</p>}
                    {c.growth_curve && <p><span className="text-foreground">成长曲线：</span>{c.growth_curve}</p>}
                    {c.emotional_anchor && <p><span className="text-foreground">情感锚点：</span>{c.emotional_anchor}</p>}
                    {c.relationships && <p><span className="text-foreground">关系：</span>{c.relationships}</p>}
                    {c.secrets && <p><span className="text-foreground">秘密：</span>{c.secrets}</p>}
                    {(c.tags && c.tags.length > 0) && <p><span className="text-foreground">标签：</span>{c.tags.join("、")}</p>}
                    {c.weight !== undefined && <p><span className="text-foreground">权重：</span>{c.weight}</p>}
                  </div>
                </div>
              )}
            </CardContent>
          </Card>
        ))}
      </div>

      {deleteDialog}

      <AiPreviewDialog
        open={previewOpen}
        title="AI 生成的角色"
        items={previewItems}
        getKey={(item) => String(item.id)}
        renderItem={(item) => (
          <div>
            <div className="flex items-center gap-2">
              <h4 className="font-medium">{item.name}</h4>
              <Badge className={item.role === "主角" ? "text-primary border-primary" : item.role === "反派" ? "text-danger border-danger" : "text-muted border-border-strong"}>
                {item.role}
              </Badge>
            </div>
            <p className="text-sm text-muted mt-1 line-clamp-4">{item.personality || item.background || "暂无描述"}</p>
          </div>
        )}
        onClose={handlePreviewClose}
        onImport={handleImport}
      />

      <AiSuggestionDialog
        open={suggestOpen}
        project={project}
        contextType="character"
        contextId=""
        defaultSuggestType="character"
        onClose={() => setSuggestOpen(false)}
        onAdopted={() => { refresh(); showSuccess("建议已采纳"); }}
      />
    </div>
  );
}
