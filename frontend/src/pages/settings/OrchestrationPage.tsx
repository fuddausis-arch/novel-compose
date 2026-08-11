/** 全局设置 · 编排页：4 个子 tab（提示词 Sections / Agent 定义 / 工具列表 / 用户注入）
 * 全部支持创建/编辑/删除，接入后端完整 CRUD API。
 */
import { useCallback, useEffect, useMemo, useState } from "react";
import { Bot, FileCode, Loader2, Plus, Save, UserRound, Wrench } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Switch } from "@/components/ui/switch";
import { Textarea } from "@/components/ui/textarea";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { EmptyState } from "@/components/ui/empty-state";
import { Dialog, DialogContent, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { cn } from "@/lib/utils";
import { useToast } from "@/hooks/useToast";

// ---- 通用 fetch 封装 ----
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

function Loading({ text }: { text: string }) {
  return (
    <div className="flex items-center justify-center py-16">
      <Loader2 className="mr-2 h-5 w-5 animate-spin text-muted" />
      <span className="text-sm text-muted">{text}</span>
    </div>
  );
}

function useAsync<T>(fetcher: () => Promise<T>, deps: unknown[]) {
  const [data, setData] = useState<T | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const run = useCallback(() => {
    let cancelled = false;
    setLoading(true);
    setError(null);
    fetcher()
      .then((d) => {
        if (!cancelled) setData(d);
      })
      .catch((e) => {
        if (!cancelled) setError(e instanceof Error ? e.message : "加载失败");
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, deps);

  useEffect(() => run(), [run]);

  const runSilent = useCallback(() => {
    // 静默刷新：不切 loading，保持滚动容器常驻不跳顶
    let cancelled = false;
    fetcher()
      .then((d) => {
        if (!cancelled) setData(d);
      })
      .catch((e) => {
        if (!cancelled) setError(e instanceof Error ? e.message : "加载失败");
      });
    return () => {
      cancelled = true;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, deps);

  return { data, loading, error, reload: run, reloadSilent: runSilent };
}

// ==================== 提示词 Sections Tab ====================

interface PromptSection {
  name: string;
  content: string;
  enabled: boolean;
  order: number;
}

interface AgentEntry {
  agent_type: string;
}

function PromptSectionsTab() {
  const { showError, showSuccess } = useToast();
  // 先获取所有 agent 类型
  const { data: agentsData } = useAsync<{ agents: Record<string, AgentEntry> }>(
    () => fetchJson("/api/agents"),
    [],
  );
  const agentTypes = useMemo(() => {
    const list = Object.keys(agentsData?.agents || {});
    return list.length > 0 ? list : ["main"];
  }, [agentsData]);

  const [selectedAgent, setSelectedAgent] = useState<string>("main");
  const [sections, setSections] = useState<PromptSection[]>([]);
  const [loading, setLoading] = useState(false);
  const [selectedSection, setSelectedSection] = useState<string | null>(null);
  const [editContent, setEditContent] = useState("");
  const [editEnabled, setEditEnabled] = useState(true);
  const [saving, setSaving] = useState(false);
  // 创建弹窗
  const [createOpen, setCreateOpen] = useState(false);
  const [newName, setNewName] = useState("");
  const [newContent, setNewContent] = useState("");
  const [creating, setCreating] = useState(false);

  const current = sections.find((s) => s.name === selectedSection) ?? null;

  const loadSections = useCallback(async (agentType: string, silent = false, preferName?: string) => {
    // silent=true：静默刷新（保存/创建后用），不切 loading 保持滚动容器常驻不跳顶
    if (!silent) setLoading(true);
    try {
      const data = await fetchJson<{ sections: PromptSection[] }>(
        `/api/prompts/${encodeURIComponent(agentType)}`,
      );
      setSections(data.sections || []);
      const target = preferName
        ? (data.sections || []).find((s) => s.name === preferName)
        : silent
          ? (data.sections || []).find((s) => s.name === selectedSection)
          : undefined;
      if (target) {
        setSelectedSection(target.name);
        setEditContent(target.content);
        setEditEnabled(target.enabled);
      } else if (data.sections && data.sections.length > 0) {
        setSelectedSection(data.sections[0].name);
        setEditContent(data.sections[0].content);
        setEditEnabled(data.sections[0].enabled);
      } else {
        setSelectedSection(null);
      }
    } catch {
      setSections([]);
      setSelectedSection(null);
    } finally {
      if (!silent) setLoading(false);
    }
  }, [selectedSection]);

  useEffect(() => {
    if (agentTypes.length > 0 && !agentTypes.includes(selectedAgent)) {
      setSelectedAgent(agentTypes[0]);
    }
  }, [agentTypes, selectedAgent]);

  useEffect(() => {
    void loadSections(selectedAgent);
  }, [selectedAgent, loadSections]);

  useEffect(() => {
    if (current) {
      setEditContent(current.content);
      setEditEnabled(current.enabled);
    }
  }, [selectedSection, current]);

  const handleSelect = (name: string) => {
    setSelectedSection(name);
    const s = sections.find((x) => x.name === name);
    if (s) {
      setEditContent(s.content);
      setEditEnabled(s.enabled);
    }
  };

  const handleSave = async () => {
    if (!current) return;
    setSaving(true);
    try {
      await fetchJson(`/api/prompts/${encodeURIComponent(selectedAgent)}/${encodeURIComponent(current.name)}`, {
        method: "PUT",
        body: JSON.stringify({ content: editContent, enabled: editEnabled }),
      });
      showSuccess("已保存");
      await loadSections(selectedAgent, true);
    } catch (e) {
      showError(e instanceof Error ? e.message : "保存失败");
    } finally {
      setSaving(false);
    }
  };

  const handleToggle = async (name: string, enabled: boolean) => {
    try {
      await fetchJson(`/api/prompts/${encodeURIComponent(selectedAgent)}/${encodeURIComponent(name)}/toggle`, {
        method: "PUT",
        body: JSON.stringify({ enabled }),
      });
      setSections((ss) => ss.map((s) => (s.name === name ? { ...s, enabled } : s)));
    } catch (e) {
      showError(e instanceof Error ? e.message : "切换失败");
    }
  };

  const handleDelete = async (name: string) => {
    if (!confirm(`确定删除 Section "${name}"？`)) return;
    try {
      await fetchJson(`/api/prompts/${encodeURIComponent(selectedAgent)}/${encodeURIComponent(name)}`, {
        method: "DELETE",
      });
      showSuccess("已删除");
      await loadSections(selectedAgent);
    } catch (e) {
      showError(e instanceof Error ? e.message : "删除失败");
    }
  };

  const handleCreate = async () => {
    if (!newName.trim()) return;
    setCreating(true);
    try {
      await fetchJson(`/api/prompts/${encodeURIComponent(selectedAgent)}`, {
        method: "POST",
        body: JSON.stringify({ name: newName.trim(), content: newContent, enabled: true, order: sections.length }),
      });
      showSuccess("已创建");
      setCreateOpen(false);
      setNewName("");
      setNewContent("");
      await loadSections(selectedAgent, true, newName.trim());
    } catch (e) {
      showError(e instanceof Error ? e.message : "创建失败");
    } finally {
      setCreating(false);
    }
  };

  const tokenEstimate = editContent ? Math.ceil(editContent.length / 4) : 0;

  if (loading) return <Loading text="正在加载 Sections..." />;
  if (sections.length === 0)
    return (
      <div className="space-y-3">
        <div className="flex justify-end">
          <Button size="sm" onClick={() => setCreateOpen(true)}>
            <Plus className="h-4 w-4" />
            新建 Section
          </Button>
        </div>
        <EmptyState icon={<FileCode className="h-10 w-10 text-muted" />} title="暂无 Section" description="点击「新建 Section」创建第一个" className="py-14" />
        {createOpen && (
          <SectionCreateDialog
            newName={newName}
            newContent={newContent}
            creating={creating}
            onName={setNewName}
            onContent={setNewContent}
            onClose={() => setCreateOpen(false)}
            onCreate={handleCreate}
          />
        )}
      </div>
    );

  return (
    <div className="flex h-full min-h-0 flex-col space-y-3">
      {/* agent 选择 + 新建按钮 */}
      <div className="flex shrink-0 flex-wrap items-center justify-between gap-2">
        <div className="flex items-center gap-2">
          <Label htmlFor="agent-select" className="text-xs text-muted">Agent:</Label>
          <select
            id="agent-select"
            value={selectedAgent}
            onChange={(e) => setSelectedAgent(e.target.value)}
            className="rounded-md border border-border bg-surface px-2 py-1 text-sm"
          >
            {agentTypes.map((t) => (
              <option key={t} value={t}>{t}</option>
            ))}
          </select>
          <Badge variant="primary">{sections.length} 个 section</Badge>
        </div>
        <Button size="sm" onClick={() => setCreateOpen(true)}>
          <Plus className="h-4 w-4" />
          新建 Section
        </Button>
      </div>

      <div className="grid min-h-0 flex-1 gap-4 lg:grid-cols-[260px_1fr]">
        {/* 左：列表（桌面独立滚动） */}
        <div className="space-y-2 lg:h-full lg:overflow-y-auto lg:pr-1">
          {sections.map((s) => (
            <div
              key={s.name}
              className={cn(
                "rounded-lg border p-2.5 transition-colors",
                selectedSection === s.name
                  ? "border-primary bg-primary-muted"
                  : "border-border bg-surface hover:bg-surface-hover",
                !s.enabled && "opacity-60",
              )}
            >
              <div className="flex items-center justify-between gap-1">
                <button
                  type="button"
                  onClick={() => handleSelect(s.name)}
                  className="min-w-0 flex-1 truncate text-left font-mono text-sm font-medium"
                >
                  {s.name}
                </button>
                <Switch
                  checked={s.enabled}
                  onCheckedChange={(v) => void handleToggle(s.name, v)}
                  aria-label="开关"
                />
              </div>
              <button
                type="button"
                onClick={() => handleSelect(s.name)}
                className="mt-0.5 block w-full truncate text-left text-[10px] text-muted"
              >
                {s.content.slice(0, 60) || "（空）"}
              </button>
              <div className="mt-1 flex justify-end">
                <button
                  type="button"
                  onClick={() => void handleDelete(s.name)}
                  className="text-[10px] text-destructive hover:underline"
                >
                  删除
                </button>
              </div>
            </div>
          ))}
        </div>

        {/* 右：编辑器（桌面独立滚动） */}
        <Card className="space-y-3 p-4 lg:h-full lg:overflow-y-auto">
          {current ? (
            <>
              <div className="flex items-center justify-between">
                <span className="font-mono text-sm font-semibold">{current.name}</span>
                <div className="flex items-center gap-2">
                  <Label htmlFor="sec-enabled" className="text-xs text-muted">启用</Label>
                  <Switch
                    id="sec-enabled"
                    checked={editEnabled}
                    onCheckedChange={setEditEnabled}
                  />
                </div>
              </div>
              <Textarea
                rows={12}
                value={editContent}
                onChange={(e) => setEditContent(e.target.value)}
                className="font-mono text-xs"
                aria-label="Section 内容"
              />
              <div className="flex items-center justify-between">
                <Badge variant="primary">约 {tokenEstimate} tokens</Badge>
                <Button size="sm" onClick={() => void handleSave()} disabled={saving}>
                  {saving ? <Loader2 className="mr-1 h-4 w-4 animate-spin" /> : <Save className="mr-1 h-4 w-4" />}
                  保存
                </Button>
              </div>
            </>
          ) : (
            <p className="py-10 text-center text-sm text-muted">选择左侧 Section 编辑内容</p>
          )}
        </Card>
      </div>

      {createOpen && (
        <SectionCreateDialog
          newName={newName}
          newContent={newContent}
          creating={creating}
          onName={setNewName}
          onContent={setNewContent}
          onClose={() => setCreateOpen(false)}
          onCreate={handleCreate}
        />
      )}
    </div>
  );
}

function SectionCreateDialog({
  newName,
  newContent,
  creating,
  onName,
  onContent,
  onClose,
  onCreate,
}: {
  newName: string;
  newContent: string;
  creating: boolean;
  onName: (v: string) => void;
  onContent: (v: string) => void;
  onClose: () => void;
  onCreate: () => void;
}) {
  const [open, setOpen] = useState(true);
  return (
    <Dialog open={open} onOpenChange={(o) => { setOpen(o); if (!o) onClose(); }}>
      <DialogContent className="max-h-[90vh] max-w-xl overflow-y-auto">
        <DialogHeader>
          <DialogTitle>新建 Section</DialogTitle>
        </DialogHeader>
        <div className="space-y-4">
          <div>
            <Label htmlFor="sec-name">名称</Label>
            <Input
              id="sec-name"
              value={newName}
              onChange={(e) => onName(e.target.value)}
              placeholder="如 core_constraints / writing_rules"
              className="mt-1 font-mono"
            />
          </div>
          <div>
            <Label htmlFor="sec-content">内容</Label>
            <Textarea
              id="sec-content"
              rows={8}
              value={newContent}
              onChange={(e) => onContent(e.target.value)}
              placeholder="Section 的 prompt 内容..."
              className="mt-1 font-mono text-xs"
            />
          </div>
        </div>
        <div className="mt-6 flex justify-end gap-2">
          <Button variant="outline" size="sm" onClick={onClose} disabled={creating}>取消</Button>
          <Button size="sm" onClick={onCreate} disabled={!newName.trim() || creating}>
            {creating ? <Loader2 className="mr-1 h-4 w-4 animate-spin" /> : <Plus className="mr-1 h-4 w-4" />}
            创建
          </Button>
        </div>
      </DialogContent>
    </Dialog>
  );
}

// ==================== Agent 定义 Tab ====================

interface AgentDef {
  agent_type: string;
  model: string;
  description?: string;
  temperature: number;
  top_p: number;
  max_turns: number;
  thinking: boolean;
  reasoning_effort: string;
  tools_whitelist: string[];
  visible: boolean;
}

function AgentDefinitionsTab() {
  const { showError, showSuccess } = useToast();
  const { data, loading, error, reloadSilent } = useAsync<{ agents: Record<string, AgentDef> }>(
    () => fetchJson("/api/agents"),
    [],
  );
  const agents = Object.entries(data?.agents || {}).map(([k, v]) => ({ ...v, agent_type: k }));
  const [selectedType, setSelectedType] = useState<string | null>(null);
  const [editDescription, setEditDescription] = useState("");
  const [editModel, setEditModel] = useState("");
  const [editTemp, setEditTemp] = useState(0.8);
  const [editTopP, setEditTopP] = useState(0.92);
  const [editMaxTurns, setEditMaxTurns] = useState(10);
  const [editThinking, setEditThinking] = useState(false);
  const [editReasoning, setEditReasoning] = useState("medium");
  const [editVisible, setEditVisible] = useState(true);
  const [saving, setSaving] = useState(false);
  // 创建弹窗
  const [createOpen, setCreateOpen] = useState(false);
  const [newType, setNewType] = useState("");
  const [creating, setCreating] = useState(false);

  const current = agents.find((a) => a.agent_type === selectedType) ?? null;

  useEffect(() => {
    if (current) {
      setEditDescription(current.description || "");
      setEditModel(current.model || "");
      setEditTemp(current.temperature ?? 0.8);
      setEditTopP(current.top_p ?? 0.92);
      setEditMaxTurns(current.max_turns ?? 10);
      setEditThinking(current.thinking ?? false);
      setEditReasoning(current.reasoning_effort || "medium");
      setEditVisible(current.visible ?? true);
    }
  }, [selectedType, current]);

  const handleSave = async () => {
    if (!current) return;
    setSaving(true);
    try {
      await fetchJson(`/api/agents/${encodeURIComponent(current.agent_type)}`, {
        method: "PUT",
        body: JSON.stringify({
          description: editDescription,
          model: editModel,
          temperature: editTemp,
          top_p: editTopP,
          max_turns: editMaxTurns,
          thinking: editThinking,
          reasoning_effort: editReasoning,
          visible: editVisible,
        }),
      });
      showSuccess("已保存");
      reloadSilent();
    } catch (e) {
      showError(e instanceof Error ? e.message : "保存失败");
    } finally {
      setSaving(false);
    }
  };

  const handleDelete = async (agentType: string) => {
    if (!confirm(`确定删除 Agent "${agentType}"？`)) return;
    try {
      await fetchJson(`/api/agents/${encodeURIComponent(agentType)}`, { method: "DELETE" });
      showSuccess("已删除");
      if (selectedType === agentType) setSelectedType(null);
      reloadSilent();
    } catch (e) {
      showError(e instanceof Error ? e.message : "删除失败");
    }
  };

  const handleCreate = async () => {
    if (!newType.trim()) return;
    setCreating(true);
    try {
      await fetchJson("/api/agents", {
        method: "POST",
        body: JSON.stringify({
          agent_type: newType.trim(),
          model: "",
          temperature: 0.8,
          top_p: 0.92,
          max_turns: 10,
          thinking: false,
          reasoning_effort: "medium",
          tools_whitelist: [],
          visible: true,
        }),
      });
      showSuccess("已创建");
      setCreateOpen(false);
      setNewType("");
      reloadSilent();
    } catch (e) {
      showError(e instanceof Error ? e.message : "创建失败");
    } finally {
      setCreating(false);
    }
  };

  if (loading) return <Loading text="正在加载 Agent 定义..." />;
  if (error || agents.length === 0)
    return (
      <div className="space-y-3">
        <div className="flex justify-end">
          <Button size="sm" onClick={() => setCreateOpen(true)}>
            <Plus className="h-4 w-4" />
            新建 Agent
          </Button>
        </div>
        <EmptyState icon={<Bot className="h-10 w-10 text-muted" />} title={error ? "后端 Agent 定义尚未接入" : "暂无 Agent 定义"} description={error ?? undefined} className="py-14" />
        {createOpen && (
          <AgentCreateDialog
            newType={newType}
            creating={creating}
            onType={setNewType}
            onClose={() => setCreateOpen(false)}
            onCreate={handleCreate}
          />
        )}
      </div>
    );

  return (
    <div className="flex h-full min-h-0 flex-col space-y-3">
      <div className="flex shrink-0 justify-end">
        <Button size="sm" onClick={() => setCreateOpen(true)}>
          <Plus className="h-4 w-4" />
          新建 Agent
        </Button>
      </div>
      <div className="grid min-h-0 flex-1 gap-4 lg:grid-cols-[260px_1fr]">
        {/* 左：列表（桌面独立滚动） */}
        <div className="space-y-2 lg:h-full lg:overflow-y-auto lg:pr-1">
          {agents.map((a) => (
            <div
              key={a.agent_type}
              className={cn(
                "rounded-lg border p-2.5 transition-colors",
                selectedType === a.agent_type
                  ? "border-primary bg-primary-muted"
                  : "border-border bg-surface hover:bg-surface-hover",
                !a.visible && "opacity-60",
              )}
            >
              <div className="flex items-center justify-between gap-1">
                <button
                  type="button"
                  onClick={() => setSelectedType(a.agent_type)}
                  className="min-w-0 flex-1 truncate text-left font-mono text-sm font-medium"
                >
                  {a.agent_type}
                </button>
                <button
                  type="button"
                  onClick={() => void handleDelete(a.agent_type)}
                  className="shrink-0 text-[10px] text-destructive hover:underline"
                >
                  删除
                </button>
              </div>
              {a.description && (
                <p className="mt-1 line-clamp-2 text-xs text-muted" title={a.description}>
                  {a.description}
                </p>
              )}
              <div className="mt-0.5 text-[10px] text-muted">
                {a.model || "默认模型"} · T={a.temperature}
              </div>
            </div>
          ))}
        </div>

        {/* 右：编辑器（桌面独立滚动） */}
        <Card className="space-y-4 p-4 lg:h-full lg:overflow-y-auto">
          {current ? (
            <>
              <div className="flex items-center gap-2 border-b border-border pb-3">
                <Bot className="h-4 w-4 text-primary" />
                <span className="font-mono text-sm font-semibold">{current.agent_type}</span>
              </div>
              <div>
                <Label htmlFor="ag-description" className="text-xs text-muted">中文说明（这个 Agent 是干什么的）</Label>
                <Textarea
                  id="ag-description"
                  value={editDescription}
                  onChange={(e) => setEditDescription(e.target.value)}
                  className="mt-1 font-mono text-xs"
                  rows={3}
                  placeholder="如：写手——根据章纲写出章节正文"
                />
              </div>
              <div className="grid grid-cols-2 gap-4">
                <div>
                  <Label htmlFor="ag-model" className="text-xs text-muted">模型</Label>
                  <Input id="ag-model" value={editModel} onChange={(e) => setEditModel(e.target.value)} className="mt-1 font-mono text-xs" placeholder="留空用默认" />
                </div>
                <div>
                  <Label htmlFor="ag-reasoning" className="text-xs text-muted">推理力度</Label>
                  <select
                    id="ag-reasoning"
                    value={editReasoning}
                    onChange={(e) => setEditReasoning(e.target.value)}
                    className="mt-1 w-full rounded-md border border-border bg-surface px-2 py-1.5 text-sm"
                  >
                    <option value="minimal">minimal</option>
                    <option value="low">low</option>
                    <option value="medium">medium</option>
                    <option value="high">high</option>
                  </select>
                </div>
                <div>
                  <Label htmlFor="ag-temp" className="text-xs text-muted">温度 (0-2)</Label>
                  <Input id="ag-temp" type="number" step="0.05" min="0" max="2" value={editTemp} onChange={(e) => setEditTemp(Number(e.target.value))} className="mt-1" />
                </div>
                <div>
                  <Label htmlFor="ag-topp" className="text-xs text-muted">Top P (0-1)</Label>
                  <Input id="ag-topp" type="number" step="0.01" min="0" max="1" value={editTopP} onChange={(e) => setEditTopP(Number(e.target.value))} className="mt-1" />
                </div>
                <div>
                  <Label htmlFor="ag-turns" className="text-xs text-muted">最大轮数</Label>
                  <Input id="ag-turns" type="number" min="1" value={editMaxTurns} onChange={(e) => setEditMaxTurns(Number(e.target.value))} className="mt-1" />
                </div>
                <div className="flex items-end gap-4 pb-1">
                  <div className="flex items-center gap-2">
                    <Switch id="ag-thinking" checked={editThinking} onCheckedChange={setEditThinking} />
                    <Label htmlFor="ag-thinking" className="text-xs text-muted">深度思考</Label>
                  </div>
                  <div className="flex items-center gap-2">
                    <Switch id="ag-visible" checked={editVisible} onCheckedChange={setEditVisible} />
                    <Label htmlFor="ag-visible" className="text-xs text-muted">可见</Label>
                  </div>
                </div>
              </div>
              <div className="flex justify-end border-t border-border pt-3">
                <Button size="sm" onClick={() => void handleSave()} disabled={saving}>
                  {saving ? <Loader2 className="mr-1 h-4 w-4 animate-spin" /> : <Save className="mr-1 h-4 w-4" />}
                  保存
                </Button>
              </div>
            </>
          ) : (
            <p className="py-10 text-center text-sm text-muted">选择左侧 Agent 编辑参数</p>
          )}
        </Card>
      </div>
      {createOpen && (
        <AgentCreateDialog
          newType={newType}
          creating={creating}
          onType={setNewType}
          onClose={() => setCreateOpen(false)}
          onCreate={handleCreate}
        />
      )}
    </div>
  );
}

function AgentCreateDialog({
  newType,
  creating,
  onType,
  onClose,
  onCreate,
}: {
  newType: string;
  creating: boolean;
  onType: (v: string) => void;
  onClose: () => void;
  onCreate: () => void;
}) {
  const [open, setOpen] = useState(true);
  return (
    <Dialog open={open} onOpenChange={(o) => { setOpen(o); if (!o) onClose(); }}>
      <DialogContent className="max-w-md">
        <DialogHeader>
          <DialogTitle>新建 Agent</DialogTitle>
        </DialogHeader>
        <div className="space-y-3">
          <div>
            <Label htmlFor="ag-new-type">Agent 类型</Label>
            <Input
              id="ag-new-type"
              value={newType}
              onChange={(e) => onType(e.target.value)}
              placeholder="如 custom_writer / my_agent"
              className="mt-1 font-mono"
            />
          </div>
          <p className="text-xs text-muted">创建后可在右侧编辑模型参数。默认温度 0.8、top_p 0.92、最大轮数 10。</p>
        </div>
        <div className="mt-6 flex justify-end gap-2">
          <Button variant="outline" size="sm" onClick={onClose} disabled={creating}>取消</Button>
          <Button size="sm" onClick={onCreate} disabled={!newType.trim() || creating}>
            {creating ? <Loader2 className="mr-1 h-4 w-4 animate-spin" /> : <Plus className="mr-1 h-4 w-4" />}
            创建
          </Button>
        </div>
      </DialogContent>
    </Dialog>
  );
}

// ==================== 工具列表 Tab（只读展示） ====================

function ToolsTab() {
  const { data, loading, error } = useAsync<{ agents: Record<string, AgentDef> }>(
    () => fetchJson("/api/agents"),
    [],
  );
  const tools = Object.entries(data?.agents || {}).map(([k, v]) => ({
    agent_type: k,
    visible: v.visible,
    model: v.model,
  }));

  if (loading) return <Loading text="正在加载工具列表..." />;
  if (error || tools.length === 0)
    return (
      <EmptyState
        icon={<Wrench className="h-10 w-10 text-muted" />}
        title={error ? "后端 Agent 列表尚未接入" : "暂无可用工具"}
        description={error ?? "编排端点 /api/agents 未返回数据"}
        className="py-14"
      />
    );
  return (
    <Card className="p-0">
      <div className="border-b border-border px-4 py-3">
        <span className="text-sm font-medium">可用 Agent / 工具（{tools.length}）</span>
      </div>
      <div className="divide-y divide-border">
        {tools.map((t) => (
          <div key={t.agent_type} className="flex items-center gap-3 px-4 py-2.5">
            <Wrench size={14} className="shrink-0 text-cyan-400" aria-hidden="true" />
            <div className="min-w-0 flex-1">
              <div className="truncate text-xs font-medium text-foreground">{t.agent_type}</div>
              {t.model && <div className="mt-0.5 truncate text-[10px] text-muted">{t.model}</div>}
            </div>
            <Badge variant={t.visible === false ? "default" : "success"}>
              {t.visible === false ? "隐藏" : "可用"}
            </Badge>
          </div>
        ))}
      </div>
    </Card>
  );
}

// ==================== 用户注入 Tab（可编辑） ====================

function UserInjectionTab() {
  const { showError, showSuccess } = useToast();
  const { data, loading, error } = useAsync<{
    global_prompt: string;
    project_prompts: Record<string, string>;
    inject_position: string;
  }>(() => fetchJson("/api/user-injection"), []);

  const [editGlobal, setEditGlobal] = useState("");
  const [editPosition, setEditPosition] = useState("system");
  const [editProject, setEditProject] = useState<Record<string, string>>({});
  const [saving, setSaving] = useState(false);

  useEffect(() => {
    if (data) {
      setEditGlobal(data.global_prompt || "");
      setEditPosition(data.inject_position || "system");
      setEditProject(data.project_prompts || {});
    }
  }, [data]);

  const projectEntries = Object.entries(editProject);

  const handleSave = async () => {
    setSaving(true);
    try {
      await fetchJson("/api/user-injection", {
        method: "PUT",
        body: JSON.stringify({
          global_prompt: editGlobal,
          inject_position: editPosition,
          project_prompts: editProject,
        }),
      });
      showSuccess("已保存");
    } catch (e) {
      showError(e instanceof Error ? e.message : "保存失败");
    } finally {
      setSaving(false);
    }
  };

  if (loading) return <Loading text="正在加载用户注入配置..." />;
  if (error || !data)
    return (
      <EmptyState
        icon={<UserRound className="h-10 w-10 text-muted" />}
        title={error ? "后端用户注入尚未接入" : "暂无注入消息"}
        description={error ?? undefined}
        className="py-14"
      />
    );

  return (
    <div className="space-y-3">
      <Card className="space-y-3 p-4">
        <div className="flex items-center justify-between">
          <span className="text-sm font-medium">全局注入提示词</span>
          <div className="flex items-center gap-2">
            <Label htmlFor="inj-pos" className="text-xs text-muted">注入位置</Label>
            <select
              id="inj-pos"
              value={editPosition}
              onChange={(e) => setEditPosition(e.target.value)}
              className="rounded-md border border-border bg-surface px-2 py-1 text-xs"
            >
              <option value="system">system</option>
              <option value="user">user</option>
            </select>
          </div>
        </div>
        <Textarea
          rows={6}
          value={editGlobal}
          onChange={(e) => setEditGlobal(e.target.value)}
          className="font-mono text-xs"
          placeholder="输入要注入到每次会话的提示词..."
        />
        <p className="text-xs text-muted">
          该提示词会注入到每次会话启动时的 <code className="rounded bg-secondary px-1">{editPosition}</code> prompt 中。
        </p>
      </Card>
      <Card className="space-y-2 p-4">
        <span className="text-sm font-medium">项目级注入（{projectEntries.length}）</span>
        {projectEntries.length === 0 ? (
          <p className="text-xs text-muted">暂无项目级注入配置</p>
        ) : (
          <div className="space-y-2">
            {projectEntries.map(([pid, prompt]) => (
              <div key={pid} className="rounded-md border border-border bg-surface p-2">
                <div className="mb-1 text-xs font-medium text-foreground">项目 #{pid}</div>
                <Textarea
                  rows={3}
                  value={prompt}
                  onChange={(e) => setEditProject({ ...editProject, [pid]: e.target.value })}
                  className="font-mono text-xs"
                />
              </div>
            ))}
          </div>
        )}
      </Card>
      <div className="flex justify-end">
        <Button size="sm" onClick={() => void handleSave()} disabled={saving}>
          {saving ? <Loader2 className="mr-1 h-4 w-4 animate-spin" /> : <Save className="mr-1 h-4 w-4" />}
          保存所有注入配置
        </Button>
      </div>
    </div>
  );
}

// ==================== 主页面 ====================

const TABS = [
  { key: "sections", label: "提示词 Sections", icon: FileCode },
  { key: "agents", label: "Agent 定义", icon: Bot },
  { key: "tools", label: "工具列表", icon: Wrench },
  { key: "injection", label: "用户注入", icon: UserRound },
] as const;

export default function OrchestrationPage() {
  return (
    <div className="flex h-full flex-col overflow-y-auto lg:overflow-hidden">
      <div className="mx-auto w-full max-w-6xl space-y-6 p-6 lg:pb-3">
        <div className="flex items-center gap-3">
          <div className="rounded-lg border border-border bg-primary-muted p-2 text-primary">
            <FileCode className="h-5 w-5" />
          </div>
          <div>
            <h2 className="text-lg font-semibold">Prompt 编排</h2>
            <p className="text-sm text-muted">提示词 Sections、Agent 定义、工具与用户注入的统一编排（可编辑）</p>
          </div>
        </div>
      </div>

      <div className="mx-auto flex w-full max-w-6xl min-h-0 flex-1 flex-col px-6 pb-6">
        <Tabs defaultValue="sections" className="flex min-h-0 flex-1 flex-col">
          <TabsList aria-label="编排子页面" className="shrink-0">
            {TABS.map(({ key, label, icon: Icon }) => (
              <TabsTrigger key={key} value={key} className="cursor-pointer gap-1.5">
                <Icon className="h-3.5 w-3.5" />
                {label}
              </TabsTrigger>
            ))}
          </TabsList>
          <TabsContent value="sections" className="min-h-0 flex-1"><PromptSectionsTab /></TabsContent>
          <TabsContent value="agents" className="min-h-0 flex-1"><AgentDefinitionsTab /></TabsContent>
          <TabsContent value="tools" className="min-h-0 flex-1"><ToolsTab /></TabsContent>
          <TabsContent value="injection" className="min-h-0 flex-1"><UserInjectionTab /></TabsContent>
        </Tabs>
      </div>
    </div>
  );
}
