/** 全局设置 · Skills 管理页：列表 + 详情，支持创建/编辑/删除/启停/自动注入/工作流专属 */
import { useCallback, useEffect, useMemo, useRef, useState, type ReactNode } from "react";
import { BookOpen, FileText, GitMerge, Loader2, Pencil, Plus, RefreshCw, Search, Trash2, Upload } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Textarea } from "@/components/ui/textarea";
import { EmptyState } from "@/components/ui/empty-state";
import { Markdown } from "@/components/markdown";
import { SettingToggleRow } from "@/components/ui/setting-toggle-row";
import { Dialog, DialogContent, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { cn } from "@/lib/utils";
import { useToast } from "@/hooks/useToast";
import { useConfirmDialog } from "@/hooks/useConfirmDialog";

interface SkillSummary {
  name: string;
  description: string;
  enabled: boolean;
}

interface SkillDetail {
  name: string;
  description: string;
  content: string;
  enabled: boolean;
  auto_inject: boolean;
  workflow_only: boolean;
}

/** 后端 GET /api/skills/{name} 返回的原始结构 */
interface SkillApiResponse {
  name: string;
  description?: string;
  enabled?: boolean;
  sections?: Array<{ name: string; content: string }>;
  auto_inject?: boolean;
  workflow_only?: boolean;
}

/** 后端 POST /api/skills 请求体 */
interface SkillCreateInput {
  name: string;
  description: string;
  enabled: boolean;
  sections: Array<{ name: string; content: string }>;
  tools: string[];
  references: string[];
}

/** 原生 fetch 封装：统一错误信息提取 */
async function fetchJson<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(path, { headers: { "Content-Type": "application/json" }, ...init });
  if (!res.ok) {
    const text = await res.text().catch(() => "");
    let msg = `请求失败（HTTP ${res.status}）`;
    try {
      const j = JSON.parse(text);
      if (j.detail) msg = String(j.detail);
      else if (j.message) msg = String(j.message);
    } catch {
      /* 非 JSON，忽略 */
    }
    throw new Error(msg);
  }
  if (res.status === 204) return undefined as T;
  return (await res.json()) as T;
}

/** 创建/编辑弹窗 */
function SkillEditorDialog({
  open,
  initial,
  onClose,
  onSave,
  saving,
}: {
  open: boolean;
  initial: SkillDetail | null;
  onClose: () => void;
  onSave: (data: { name: string; description: string; content: string; enabled: boolean }) => void;
  saving: boolean;
}) {
  const isEdit = !!initial;
  const [name, setName] = useState("");
  const [description, setDescription] = useState("");
  const [content, setContent] = useState("");
  const [enabled, setEnabled] = useState(true);

  useEffect(() => {
    if (open) {
      setName(initial?.name ?? "");
      setDescription(initial?.description ?? "");
      setContent(initial?.content ?? "");
      setEnabled(initial?.enabled ?? true);
    }
  }, [open, initial]);

  const canSave = name.trim() && !saving;

  return (
    <Dialog open={open} onOpenChange={(o) => !o && onClose()}>
      <DialogContent className="max-h-[90vh] max-w-2xl overflow-y-auto">
        <DialogHeader>
          <DialogTitle>{isEdit ? "编辑 Skill" : "新建 Skill"}</DialogTitle>
        </DialogHeader>
        <div className="space-y-4">
          <div>
            <Label htmlFor="skill-name">名称</Label>
            <Input
              id="skill-name"
              value={name}
              onChange={(e) => setName(e.target.value)}
              placeholder="支持中文，如：我的融合总纲"
              className="mt-1 font-mono"
            />
            {isEdit && <p className="mt-1 text-xs text-muted">改名会同步更新 Skill 文件名</p>}
          </div>
          <div>
            <Label htmlFor="skill-desc">描述</Label>
            <Input
              id="skill-desc"
              value={description}
              onChange={(e) => setDescription(e.target.value)}
              placeholder="简短说明这个 Skill 的用途"
              className="mt-1"
            />
          </div>
          <div>
            <Label htmlFor="skill-content">内容（prompt section 内容）</Label>
            <Textarea
              id="skill-content"
              value={content}
              onChange={(e) => setContent(e.target.value)}
              rows={10}
              placeholder="支持 Markdown 格式的 Skill 内容..."
              className="mt-1 font-mono text-xs"
            />
          </div>
          <SettingToggleRow
            label="启用"
            description="创建后立即生效"
            checked={enabled}
            onChange={setEnabled}
          />
        </div>
        <div className="mt-6 flex justify-end gap-2">
          <Button variant="outline" size="sm" onClick={onClose} disabled={saving}>
            取消
          </Button>
          <Button
            variant="default"
            size="sm"
            onClick={() => canSave && onSave({ name: name.trim(), description, content, enabled })}
            disabled={!canSave}
          >
            {saving ? <Loader2 className="mr-1 h-4 w-4 animate-spin" /> : null}
            {isEdit ? "保存" : "创建"}
          </Button>
        </div>
      </DialogContent>
    </Dialog>
  );
}

/** 拆书导入弹窗：上传书籍 -> SSE 进度 -> 生成 skill */
function BookImportDialog({
  open,
  onClose,
  onDone,
}: {
  open: boolean;
  onClose: () => void;
  onDone: () => void;
}) {
  const { showError, showSuccess } = useToast();
  const [file, setFile] = useState<File | null>(null);
  const [title, setTitle] = useState("");
  const [description, setDescription] = useState("");
  const [maxChapters, setMaxChapters] = useState(50);
  const [processing, setProcessing] = useState(false);
  const [progress, setProgress] = useState<{ current: number; total: number; title: string } | null>(null);

  useEffect(() => {
    if (open) {
      setFile(null);
      setTitle("");
      setDescription("");
      setMaxChapters(50);
      setProcessing(false);
      setProgress(null);
    }
  }, [open]);

  const handleUpload = async () => {
    if (!file) return;
    setProcessing(true);
    setProgress(null);
    try {
      const formData = new FormData();
      formData.append("file", file);
      formData.append("title", title || file.name.replace(/\.[^.]+$/, ""));
      formData.append("description", description);
      formData.append("max_chapters", String(maxChapters));

      const resp = await fetch("/api/skills/import-book", { method: "POST", body: formData });
      if (!resp.ok) {
        const text = await resp.text().catch(() => "");
        let msg = `上传失败（HTTP ${resp.status}）`;
        try { const j = JSON.parse(text); if (j.detail) msg = String(j.detail); } catch {}
        throw new Error(msg);
      }

      // 读取 SSE 流
      const reader = resp.body?.getReader();
      const decoder = new TextDecoder();
      let buffer = "";
      let done = false;

      while (reader && !done) {
        const { done: rDone, value } = await reader.read();
        if (rDone) break;
        buffer += decoder.decode(value, { stream: true });
        const lines = buffer.split("\n");
        buffer = lines.pop() || "";

        let currentEvent = "";
        for (const line of lines) {
          if (line.startsWith("event:")) {
            currentEvent = line.slice(6).trim();
          } else if (line.startsWith("data:")) {
            const dataStr = line.slice(5).trim();
            if (!dataStr) continue;
            let data: any;
            try { data = JSON.parse(dataStr); } catch { continue; }

            if (currentEvent === "progress") {
              setProgress({ current: data.current, total: data.total, title: data.title });
            } else if (currentEvent === "done") {
              showSuccess(`拆书完成！生成 ${data.sections_count} 章技能`);
              done = true;
              setProcessing(false);
              onClose();
              onDone();
              return;
            } else if (currentEvent === "error") {
              showError(`拆书失败：${data.error}`);
              setProcessing(false);
              return;
            }
          }
        }
      }
    } catch (e) {
      showError(e instanceof Error ? e.message : "拆书失败");
      setProcessing(false);
    }
  };

  const pct = progress ? Math.round((progress.current / progress.total) * 100) : 0;

  return (
    <Dialog open={open} onOpenChange={(o) => !o && onClose()}>
      <DialogContent className="max-h-[90vh] max-w-xl overflow-y-auto">
        <DialogHeader>
          <DialogTitle className="flex items-center gap-2">
            <FileText className="h-5 w-5 text-primary" />
            拆书导入 Skill
          </DialogTitle>
        </DialogHeader>

        <p className="text-sm text-muted">
          上传写作技法书或参考小说（PDF/EPUB/DOCX/TXT），系统自动拆分章节并 LLM 逐章提炼为可按需加载的技能。
        </p>

        <div className="mt-4 space-y-4">
          {/* 文件选择 */}
          <div>
            <Label>选择文件</Label>
            <div className="mt-1 flex items-center gap-2">
              <label className="flex-1 cursor-pointer rounded-lg border border-dashed border-border px-4 py-3 text-center text-sm text-muted hover:border-primary hover:text-primary transition-colors">
                <Upload className="mx-auto mb-1 h-4 w-4" />
                {file ? file.name : "点击选择文件"}
                <input
                  type="file"
                  className="hidden"
                  accept=".pdf,.epub,.docx,.txt,.md"
                  onChange={(e) => setFile(e.target.files?.[0] ?? null)}
                />
              </label>
            </div>
            <p className="mt-1 text-xs text-muted">支持 PDF、EPUB、DOCX、TXT、Markdown</p>
          </div>

          {/* 书名 */}
          <div>
            <Label>书名（可选，默认取文件名）</Label>
            <Input
              className="mt-1"
              value={title}
              onChange={(e) => setTitle(e.target.value)}
              placeholder="如：故事技巧"
            />
          </div>

          {/* 描述 */}
          <div>
            <Label>描述（可选）</Label>
            <Input
              className="mt-1"
              value={description}
              onChange={(e) => setDescription(e.target.value)}
              placeholder="简短说明这本书的用途"
            />
          </div>

          {/* 最大章节数 */}
          <div>
            <Label>最大处理章节数</Label>
            <Input
              type="number"
              className="mt-1"
              value={maxChapters}
              onChange={(e) => setMaxChapters(Math.max(1, parseInt(e.target.value) || 50))}
              min={1}
              max={200}
            />
            <p className="mt-1 text-xs text-muted">每章调用一次 LLM 提炼，章数越多耗时越长</p>
          </div>

          {/* 进度条 */}
          {progress && (
            <div className="rounded-lg border border-border bg-background p-3">
              <div className="flex items-center justify-between text-sm">
                <span className="text-muted">正在提炼第 {progress.current}/{progress.total} 章</span>
                <span className="font-mono text-primary">{pct}%</span>
              </div>
              <div className="mt-2 h-2 overflow-hidden rounded-full bg-secondary">
                <div className="h-full bg-primary transition-all" style={{ width: `${pct}%` }} />
              </div>
              <p className="mt-1 truncate text-xs text-muted">{progress.title}</p>
            </div>
          )}
        </div>

        <div className="mt-6 flex justify-end gap-2">
          <Button variant="outline" size="sm" onClick={onClose} disabled={processing}>
            取消
          </Button>
          <Button
            variant="default"
            size="sm"
            onClick={() => void handleUpload()}
            disabled={!file || processing}
          >
            {processing ? <Loader2 className="mr-1 h-4 w-4 animate-spin" /> : <FileText className="mr-1 h-4 w-4" />}
            {processing ? "拆书中..." : "开始拆书"}
          </Button>
        </div>
      </DialogContent>
    </Dialog>
  );
}

/** 多选 Skill 融合弹窗：POST /api/distillation/fuse（SSE 进度，可中断） */
function FusionDialog({
  open,
  names,
  onClose,
  onDone,
}: {
  open: boolean;
  names: string[];
  onClose: () => void;
  onDone: () => void;
}) {
  const { showError, showSuccess } = useToast();
  const [fusionName, setFusionName] = useState("");
  const [description, setDescription] = useState("");
  const [running, setRunning] = useState(false);
  const [progress, setProgress] = useState<string>("");
  const abortRef = useRef<AbortController | null>(null);

  useEffect(() => {
    if (open) {
      setFusionName(`Skill融合（${names.length} 个）`);
      setDescription("");
      setRunning(false);
      setProgress("");
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [open]);

  const stopFusion = () => {
    abortRef.current?.abort();
    setRunning(false);
    setProgress("已中断");
  };

  const startFusion = async () => {
    if (!fusionName.trim()) return;
    setRunning(true);
    setProgress("准备中…");
    const controller = new AbortController();
    abortRef.current = controller;
    try {
      const resp = await fetch("/api/distillation/fuse", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          name: fusionName.trim(),
          description,
          skill_ids: [],
          skill_files: names,
        }),
        signal: controller.signal,
      });
      if (!resp.ok) {
        const text = await resp.text().catch(() => "");
        let msg = `融合请求失败（HTTP ${resp.status}）`;
        try { const j = JSON.parse(text); if (j.detail) msg = String(j.detail); } catch {}
        throw new Error(msg);
      }
      const reader = resp.body?.getReader();
      const decoder = new TextDecoder();
      let buffer = "";
      let done = false;
      while (reader && !done) {
        const { done: rDone, value } = await reader.read();
        if (rDone) break;
        buffer += decoder.decode(value, { stream: true });
        const lines = buffer.split("\n");
        buffer = lines.pop() || "";
        for (const line of lines) {
          if (!line.startsWith("data:")) continue;
          const dataStr = line.slice(5).trim();
          if (!dataStr) continue;
          let data: any;
          try { data = JSON.parse(dataStr); } catch { continue; }
          const t = data.type || "";
          if (t === "fuse_start") {
            setProgress(`共 ${data.skill_count} 个 Skill，开始融合…`);
          } else if (t === "fuse_batch_start") {
            setProgress(`正在提炼第 ${data.batch}/${data.total} 批…`);
          } else if (t === "fuse_batch_done") {
            setProgress(`第 ${data.batch}/${data.total} 批完成`);
          } else if (t === "fuse_done") {
            done = true;
            setProgress("融合完成");
            setRunning(false);
            showSuccess(`融合完成！已生成 ${data.fusion?.skill_file || "新 Skill"}`);
            onClose();
            onDone();
            return;
          } else if (t === "error") {
            throw new Error(data.error || "融合失败");
          }
        }
      }
      setRunning(false);
    } catch (e) {
      if ((e as Error).name === "AbortError") return;
      showError(e instanceof Error ? e.message : "融合失败");
      setRunning(false);
    }
  };

  return (
    <Dialog open={open} onOpenChange={(o) => !o && !running && onClose()}>
      <DialogContent className="max-h-[90vh] max-w-xl overflow-y-auto">
        <DialogHeader>
          <DialogTitle className="flex items-center gap-2">
            <GitMerge className="h-5 w-5 text-primary" />
            融合所选 Skill（{names.length} 个）
          </DialogTitle>
        </DialogHeader>
        <div className="space-y-4">
          <p className="text-sm text-muted">
            将所选 Skill 交给 LLM 提炼浓缩为一份精炼总纲（非简单拼接）。选中的 Skill：
          </p>
          <div className="max-h-32 overflow-y-auto rounded-lg border border-border bg-background p-2 text-xs text-muted">
            {names.map((n) => (
              <div key={n} className="truncate py-0.5">{n}</div>
            ))}
          </div>
          <div>
            <Label htmlFor="fusion-name">融合方案名称</Label>
            <Input
              id="fusion-name"
              value={fusionName}
              onChange={(e) => setFusionName(e.target.value)}
              className="mt-1"
              placeholder="如：我的风格总纲"
            />
          </div>
          <div>
            <Label htmlFor="fusion-desc">描述（可选）</Label>
            <Input
              id="fusion-desc"
              value={description}
              onChange={(e) => setDescription(e.target.value)}
              className="mt-1"
              placeholder="简短说明这份总纲的用途"
            />
          </div>
          {running && (
            <div className="rounded-lg border border-border bg-background p-3 text-sm">
              <div className="flex items-center justify-between">
                <span className="text-muted">{progress}</span>
                <span className="flex items-center gap-1 text-primary">
                  <Loader2 className="h-3.5 w-3.5 animate-spin" /> 提炼中
                </span>
              </div>
            </div>
          )}
        </div>
        <div className="mt-6 flex justify-end gap-2">
          <Button variant="outline" size="sm" onClick={running ? stopFusion : onClose} disabled={false}>
            {running ? "中断" : "取消"}
          </Button>
          <Button
            variant="default"
            size="sm"
            onClick={() => void startFusion()}
            disabled={!fusionName.trim() || running}
          >
            {running ? <Loader2 className="mr-1 h-4 w-4 animate-spin" /> : <GitMerge className="mr-1 h-4 w-4" />}
            {running ? "融合中..." : "开始融合"}
          </Button>
        </div>
      </DialogContent>
    </Dialog>
  );
}

export default function SkillsPage() {
  const { showError, showSuccess } = useToast();
  const { confirm: confirmDelete, dialog: deleteDialog } = useConfirmDialog();
  const [skills, setSkills] = useState<SkillSummary[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [search, setSearch] = useState("");
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [detail, setDetail] = useState<SkillDetail | null>(null);
  const [detailLoading, setDetailLoading] = useState(false);
  const [reloading, setReloading] = useState(false);

  // 弹窗状态
  const [editorOpen, setEditorOpen] = useState(false);
  const [editorInitial, setEditorInitial] = useState<SkillDetail | null>(null);
  const [editorSaving, setEditorSaving] = useState(false);
  const [bookImportOpen, setBookImportOpen] = useState(false);

  // 多选融合状态
  const [selectedNames, setSelectedNames] = useState<Set<string>>(new Set());
  const [fuseOpen, setFuseOpen] = useState(false);

  const toggleSelect = (name: string) => {
    setSelectedNames((prev) => {
      const next = new Set(prev);
      if (next.has(name)) next.delete(name);
      else next.add(name);
      return next;
    });
  };

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const data = await fetchJson<{ skills: SkillSummary[] }>("/api/skills");
      setSkills(data.skills || []);
    } catch (e) {
      setError(e instanceof Error ? e.message : "加载失败");
      setSkills([]);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  const loadDetail = useCallback(
    async (name: string) => {
      setDetailLoading(true);
      try {
        const data = await fetchJson<SkillApiResponse>(`/api/skills/${encodeURIComponent(name)}`);
        setDetail({
          name: data.name,
          description: data.description ?? "",
          enabled: data.enabled ?? true,
          content: (data.sections ?? [])
            .map((s) => s.content)
            .filter(Boolean)
            .join("\n\n"),
          auto_inject: data.auto_inject ?? false,
          workflow_only: data.workflow_only ?? false,
        });
      } catch (e) {
        showError(e instanceof Error ? e.message : "加载详情失败");
        setDetail(null);
      } finally {
        setDetailLoading(false);
      }
    },
    [showError],
  );

  useEffect(() => {
    if (selectedId) void loadDetail(selectedId);
    else setDetail(null);
  }, [selectedId, loadDetail]);

  const handleToggle = async (field: "enabled" | "auto_inject" | "workflow_only", value: boolean) => {
    if (!detail) return;
    const prev = detail;
    setDetail({ ...prev, [field]: value });
    if (field === "enabled") {
      setSkills((s) => s.map((it) => (it.name === detail.name ? { ...it, enabled: value } : it)));
    }
    try {
      await fetchJson(`/api/skills/${encodeURIComponent(detail.name)}`, {
        method: "PUT",
        body: JSON.stringify({ [field]: value }),
      });
      showSuccess("已更新");
    } catch (e) {
      setDetail(prev);
      if (field === "enabled") {
        setSkills((s) => s.map((it) => (it.name === prev.name ? { ...it, enabled: prev.enabled } : it)));
      }
      showError(e instanceof Error ? e.message : "切换失败");
    }
  };

  const handleReload = async () => {
    setReloading(true);
    try {
      await load();
      showSuccess("已重新加载");
    } catch (e) {
      showError(e instanceof Error ? e.message : "重新加载失败");
    } finally {
      setReloading(false);
    }
  };

  // ---- 创建/编辑 ----
  const openCreate = () => {
    setEditorInitial(null);
    setEditorOpen(true);
  };

  const openEdit = () => {
    if (!detail) return;
    setEditorInitial(detail);
    setEditorOpen(true);
  };

  const handleSave = async (data: { name: string; description: string; content: string; enabled: boolean }) => {
    setEditorSaving(true);
    try {
      const isEdit = !!editorInitial;
      // 把 content 包装成一个名为 "main" 的 section
      const skillData: SkillCreateInput = {
        name: data.name,
        description: data.description,
        enabled: data.enabled,
        sections: data.content ? [{ name: "main", content: data.content }] : [],
        tools: [],
        references: [],
      };
      if (isEdit) {
        // 编辑：PUT（支持改名，name 变化时后端同步文件名 + 蒸馏 DB）
        await fetchJson(`/api/skills/${encodeURIComponent(editorInitial.name)}`, {
          method: "PUT",
          body: JSON.stringify({
            name: data.name,
            description: data.description,
            enabled: data.enabled,
            sections: skillData.sections,
            tools: [],
            references: [],
          }),
        });
        showSuccess("已保存");
        // 刷新详情（改名后选中新名称）
        if (selectedId === data.name || selectedId === editorInitial.name) {
          setSelectedId(data.name);
        } else {
          void loadDetail(data.name);
        }
      } else {
        // 创建：POST
        await fetchJson("/api/skills", {
          method: "POST",
          body: JSON.stringify(skillData),
        });
        showSuccess("已创建");
        setSelectedId(data.name);
      }
      setEditorOpen(false);
      await load();
    } catch (e) {
      showError(e instanceof Error ? e.message : "保存失败");
    } finally {
      setEditorSaving(false);
    }
  };

  // ---- 批量删除 ----
  const handleBatchDelete = async () => {
    const names = Array.from(selectedNames);
    if (names.length === 0) return;
    const ok = await confirmDelete({
      title: "批量删除 Skill",
      description: `确定要删除选中的 ${names.length} 个 Skill 吗？此操作不可撤销。`,
      confirmText: "确认删除",
      cancelText: "取消",
      variant: "danger",
    });
    if (!ok) return;
    try {
      const res = await fetchJson<{ deleted: string[]; failed: Array<{ name: string; error: string }> }>(
        "/api/skills/batch-delete",
        { method: "POST", body: JSON.stringify({ names }) },
      );
      setSelectedNames(new Set());
      if (selectedId && res.deleted.includes(selectedId)) {
        setSelectedId(null);
        setDetail(null);
      }
      await load();
      if (res.deleted.length > 0) showSuccess(`已删除 ${res.deleted.length} 个 Skill`);
      if (res.failed.length > 0) {
        showError(`部分删除失败：${res.failed.map((f) => `${f.name}（${f.error}）`).join("；")}`);
      }
    } catch (e) {
      showError(e instanceof Error ? e.message : "批量删除失败");
    }
  };

  // ---- 删除 ----
  const openDelete = async (name: string) => {
    const ok = await confirmDelete({
      title: "删除 Skill",
      description: `确定要删除 Skill ${name} 吗？此操作不可撤销。`,
      confirmText: "确认删除",
      cancelText: "取消",
      variant: "danger",
    });
    if (!ok) return;
    try {
      await fetchJson(`/api/skills/${encodeURIComponent(name)}`, { method: "DELETE" });
      showSuccess(`已删除 ${name}`);
      if (selectedId === name) {
        setSelectedId(null);
        setDetail(null);
      }
      await load();
    } catch (e) {
      showError(e instanceof Error ? e.message : "删除失败");
    }
  };

  const filtered = useMemo(() => {
    const kw = search.trim().toLowerCase();
    if (!kw) return skills;
    return skills.filter(
      (s) => s.name.toLowerCase().includes(kw) || s.description.toLowerCase().includes(kw),
    );
  }, [skills, search]);

  const enabledCount = skills.filter((s) => s.enabled).length;

  const header = (
    <div className="flex flex-col gap-4 sm:flex-row sm:items-center sm:justify-between">
      <div className="flex items-center gap-3">
        <div className="rounded-lg border border-border bg-primary-muted p-2 text-primary">
          <BookOpen className="h-5 w-5" />
        </div>
        <div>
          <h2 className="text-lg font-semibold">Skills 管理</h2>
          <p className="text-sm text-muted">管理可复用的知识与行为模块</p>
        </div>
      </div>
      <div className="flex gap-2">
        <Button
          variant="outline"
          size="sm"
          onClick={() => setFuseOpen(true)}
          disabled={selectedNames.size === 0}
          title={selectedNames.size === 0 ? "先勾选要融合的 Skill" : `融合选中的 ${selectedNames.size} 个 Skill`}
        >
          <GitMerge className="h-4 w-4" />
          融合选中{selectedNames.size > 0 ? `（${selectedNames.size}）` : ""}
        </Button>
        <Button
          variant="outline"
          size="sm"
          onClick={() => void handleBatchDelete()}
          disabled={selectedNames.size === 0}
          className="text-destructive hover:bg-destructive/10"
          title={selectedNames.size === 0 ? "先勾选要删除的 Skill" : `删除选中的 ${selectedNames.size} 个 Skill`}
        >
          <Trash2 className="h-4 w-4" />
          删除选中{selectedNames.size > 0 ? `（${selectedNames.size}）` : ""}
        </Button>
        <Button variant="default" size="sm" onClick={() => setBookImportOpen(true)}>
          <FileText className="h-4 w-4" />
          拆书导入
        </Button>
        <Button variant="outline" size="sm" onClick={openCreate}>
          <Plus className="h-4 w-4" />
          新建 Skill
        </Button>
        <Button variant="outline" size="sm" onClick={() => void handleReload()} disabled={reloading}>
          <RefreshCw className={cn("h-4 w-4", reloading && "animate-spin")} />
          重新加载
        </Button>
      </div>
    </div>
  );

  const stats = (
    <div className="grid grid-cols-3 gap-4">
      <Card className="p-4">
        <div className="text-xs text-muted">总计</div>
        <div className="mt-1 text-2xl font-bold tabular-nums">{skills.length}</div>
      </Card>
      <Card className="p-4">
        <div className="text-xs text-muted">已启用</div>
        <div className="mt-1 text-2xl font-bold tabular-nums text-success">{enabledCount}</div>
      </Card>
      <Card className="p-4">
        <div className="text-xs text-muted">已禁用</div>
        <div className="mt-1 text-2xl font-bold tabular-nums text-muted">{skills.length - enabledCount}</div>
      </Card>
    </div>
  );

  let body: ReactNode;
  if (loading) {
    body = (
      <div className="flex items-center justify-center py-20">
        <Loader2 className="mr-2 h-5 w-5 animate-spin text-muted" />
        <span className="text-sm text-muted">正在加载 Skills...</span>
      </div>
    );
  } else if (error || skills.length === 0) {
    body = (
      <EmptyState
        icon={<BookOpen className="h-10 w-10 text-muted" />}
        title={error ? "后端 Skills 系统尚未接入" : "暂无 Skill"}
        description={error ?? "点击「新建 Skill」创建第一个"}
      />
    );
  } else {
    body = (
      <div className="grid gap-4 lg:h-full lg:grid-cols-[320px_1fr]">
        {/* 左：列表（桌面独立滚动；窄屏随页面滚动） */}
        <div className="space-y-3 lg:h-full lg:overflow-y-auto lg:pr-1">
          <div className="relative">
            <Search className="pointer-events-none absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-muted" />
            <Input
              className="pl-9"
              placeholder="搜索 Skill..."
              value={search}
              onChange={(e) => setSearch(e.target.value)}
              aria-label="搜索 Skill"
            />
          </div>
          <div className="space-y-2">
            {filtered.map((s) => (
              <button
                key={s.name}
                type="button"
                onClick={() => setSelectedId(s.name)}
                className={cn(
                  "w-full rounded-lg border p-3 text-left transition-colors",
                  selectedId === s.name
                    ? "border-primary bg-primary-muted"
                    : "border-border bg-surface hover:bg-surface-hover",
                  !s.enabled && "opacity-60",
                )}
              >
                <div className="flex items-center justify-between gap-2">
                  <span className="flex min-w-0 items-center gap-2">
                    <span
                      role="checkbox"
                      aria-checked={selectedNames.has(s.name)}
                      tabIndex={-1}
                      onClick={(e) => {
                        e.stopPropagation();
                        toggleSelect(s.name);
                      }}
                      className={cn(
                        "flex h-4 w-4 shrink-0 cursor-pointer items-center justify-center rounded border transition-colors",
                        selectedNames.has(s.name)
                          ? "border-primary bg-primary text-primary-foreground"
                          : "border-border bg-background hover:border-primary",
                      )}
                    >
                      {selectedNames.has(s.name) && <span className="text-[10px] leading-none">✓</span>}
                    </span>
                    <span className="truncate font-mono text-sm font-medium">{s.name}</span>
                  </span>
                  <Badge variant={s.enabled ? "success" : "default"}>{s.enabled ? "启用" : "禁用"}</Badge>
                </div>
                <p className="mt-1 line-clamp-1 text-xs text-muted">{s.description || "（无描述）"}</p>
              </button>
            ))}
            {filtered.length === 0 && (
              <p className="py-4 text-center text-xs text-muted">未找到匹配的 Skill</p>
            )}
          </div>
        </div>

        {/* 右：详情（桌面独立滚动；窄屏随页面滚动） */}
        <Card className="p-5 lg:h-full lg:overflow-y-auto">
          {!selectedId ? (
            <div className="flex min-h-[320px] items-center justify-center text-sm text-muted">
              选择左侧 Skill 查看详情，或点击「新建 Skill」创建
            </div>
          ) : detailLoading ? (
            <div className="flex items-center justify-center py-20">
              <Loader2 className="mr-2 h-5 w-5 animate-spin text-muted" />
              <span className="text-sm text-muted">加载详情...</span>
            </div>
          ) : detail ? (
            <div className="space-y-4">
              <div className="flex items-start justify-between gap-2">
                <div className="min-w-0">
                  <h3 className="font-mono text-base font-semibold">{detail.name}</h3>
                  <p className="mt-1 text-sm text-muted">{detail.description || "（无描述）"}</p>
                </div>
                <div className="flex shrink-0 gap-1">
                  <Button variant="outline" size="sm" onClick={openEdit}>
                    <Pencil className="h-3.5 w-3.5" />
                    编辑
                  </Button>
                  <Button
                    variant="outline"
                    size="sm"
                    onClick={() => openDelete(detail.name)}
                    className="text-destructive hover:bg-destructive/10"
                  >
                    <Trash2 className="h-3.5 w-3.5" />
                    删除
                  </Button>
                </div>
              </div>
              <div>
                <div className="mb-1 text-xs font-medium text-muted">内容预览</div>
                <div className="max-h-[50vh] overflow-y-auto rounded-lg border border-border bg-background p-3 text-sm">
                  {detail.content ? (
                    <Markdown content={detail.content} />
                  ) : (
                    <span className="text-xs text-muted">（无内容）</span>
                  )}
                </div>
              </div>
              <div className="space-y-3 border-t border-border pt-4">
                <SettingToggleRow
                  label="启用 / 禁用"
                  description="控制该 Skill 是否参与注入"
                  checked={detail.enabled}
                  onChange={(v) => void handleToggle("enabled", v)}
                />
                <SettingToggleRow
                  label="自动注入"
                  description="是否在每次对话中自动注入"
                  checked={detail.auto_inject}
                  onChange={(v) => void handleToggle("auto_inject", v)}
                />
                <SettingToggleRow
                  label="工作流专属"
                  description="仅在工作流执行时生效"
                  checked={detail.workflow_only}
                  onChange={(v) => void handleToggle("workflow_only", v)}
                />
              </div>
            </div>
          ) : (
            <div className="flex min-h-[320px] items-center justify-center text-sm text-muted">
              加载详情失败
            </div>
          )}
        </Card>
      </div>
    );
  }

  return (
    <div className="flex h-full flex-col overflow-y-auto lg:overflow-hidden">
      {/* 顶部区（搜索/统计，窄屏随页面滚动） */}
      <div className="mx-auto w-full max-w-6xl space-y-6 p-6 lg:pb-3">
        {header}
        {stats}
      </div>
      {/* 主体区：桌面下占满剩余高度，左右两栏各自独立滚动 */}
      <div className="mx-auto w-full max-w-6xl min-h-0 flex-1 px-6 pb-6">
        {body}
      </div>
      <SkillEditorDialog
        open={editorOpen}
        initial={editorInitial}
        onClose={() => setEditorOpen(false)}
        onSave={handleSave}
        saving={editorSaving}
      />
      {deleteDialog}
      <BookImportDialog
        open={bookImportOpen}
        onClose={() => setBookImportOpen(false)}
        onDone={() => void load()}
      />
      <FusionDialog
        open={fuseOpen}
        names={Array.from(selectedNames)}
        onClose={() => setFuseOpen(false)}
        onDone={() => {
          setSelectedNames(new Set());
          void load();
        }}
      />
    </div>
  );
}
