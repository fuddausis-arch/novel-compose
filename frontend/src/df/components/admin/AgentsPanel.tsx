/** Agent 定义管理面板：列表 / 新建 / 编辑 / 可见性开关 / 删除 / 内置播种
 * 对接 /api/agents 系列端点（含 DELETE /api/agents/{agent_type}）。
 */
import { useCallback, useEffect, useMemo, useState } from "react";
import { Bot, Pencil, Plus, RefreshCw, Sparkles, Trash2 } from "lucide-react";
import { Switch } from "@/components/ui/switch";
import { apiFetch, apiJson, parseListInput } from "./df-api";
import {
  DFCard,
  DFEmpty,
  DFErrorToast,
  DFFormField,
  DFIconButton,
  DFInput,
  DFLoading,
  DFModal,
  DFPrimaryButton,
  DFSearchInput,
  DFSecondaryButton,
  DFSelect,
  DFTag,
} from "./df-ui";
import { useToast } from "@/hooks/useToast";
import { useConfirmDialog } from "@/hooks/useConfirmDialog";
import ModelPicker from "./ModelPicker";

/** Agent 定义（与后端 AgentDef 对齐） */
export interface AgentDef {
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

const REASONING_EFFORTS = ["low", "medium", "high"];

interface AgentFormState {
  agent_type: string;
  model: string;
  description: string;
  temperature: string;
  top_p: string;
  max_turns: string;
  thinking: boolean;
  reasoning_effort: string;
  tools_whitelist: string;
  visible: boolean;
}

const EMPTY_FORM: AgentFormState = {
  agent_type: "",
  model: "",
  description: "",
  temperature: "0.8",
  top_p: "0.92",
  max_turns: "10",
  thinking: false,
  reasoning_effort: "medium",
  tools_whitelist: "",
  visible: true,
};

export default function AgentsPanel({
  selectedAgentType,
  onSelectAgent,
}: {
  selectedAgentType?: string;
  onSelectAgent?: (agentType: string) => void;
}) {
  const { showSuccess } = useToast();
  const { confirm: confirmDelete, dialog: deleteDialog } = useConfirmDialog();
  const [agents, setAgents] = useState<Record<string, AgentDef>>({});
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);
  const [search, setSearch] = useState("");
  const [error, setError] = useState<string | null>(null);

  const [creating, setCreating] = useState(false);
  const [editing, setEditing] = useState<AgentDef | null>(null);
  const [form, setForm] = useState<AgentFormState>(EMPTY_FORM);
  const [formError, setFormError] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);
  const [seeding, setSeeding] = useState(false);
  const [deletingId, setDeletingId] = useState<string | null>(null);

  const load = useCallback(async (initial = false) => {
    if (initial) setLoading(true);
    else setRefreshing(true);
    try {
      const data = await apiFetch<{ agents: Record<string, AgentDef> }>("/api/agents");
      setAgents(data.agents || {});
    } catch (e) {
      setError(e instanceof Error ? e.message : "加载 Agent 定义失败");
    } finally {
      setLoading(false);
      setRefreshing(false);
    }
  }, []);

  useEffect(() => {
    void load(true);
  }, [load]);

  const list = useMemo(() => {
    const keyword = search.trim().toLowerCase();
    return Object.values(agents)
      .filter((a) => !keyword || a.agent_type.toLowerCase().includes(keyword) || a.model.toLowerCase().includes(keyword))
      .sort((a, b) => a.agent_type.localeCompare(b.agent_type));
  }, [agents, search]);

  /** 可见性开关：乐观更新 + 失败回滚 */
  const handleToggleVisible = async (agent: AgentDef, visible: boolean) => {
    const snapshot = agents;
    setAgents((prev) => ({ ...prev, [agent.agent_type]: { ...agent, visible } }));
    try {
      await apiJson(`/api/agents/${encodeURIComponent(agent.agent_type)}`, "PUT", { visible });
    } catch (e) {
      setAgents(snapshot);
      setError(e instanceof Error ? e.message : "切换可见性失败");
    }
  };

  const openEdit = (agent: AgentDef) => {
    setForm({
      agent_type: agent.agent_type,
      model: agent.model,
      description: agent.description || "",
      temperature: String(agent.temperature),
      top_p: String(agent.top_p),
      max_turns: String(agent.max_turns),
      thinking: agent.thinking,
      reasoning_effort: agent.reasoning_effort || "medium",
      tools_whitelist: (agent.tools_whitelist || []).join(", "),
      visible: agent.visible,
    });
    setFormError(null);
    setEditing(agent);
  };

  const openCreate = () => {
    setForm(EMPTY_FORM);
    setFormError(null);
    setCreating(true);
  };

  const handleSubmit = async () => {
    if (!form.agent_type.trim()) {
      setFormError("请输入 Agent 类型标识");
      return;
    }
    setSaving(true);
    setFormError(null);
    const payload = {
      model: form.model.trim(),
      description: form.description.trim(),
      temperature: Number(form.temperature) || 0.8,
      top_p: Number(form.top_p) || 0.92,
      max_turns: Number(form.max_turns) || 10,
      thinking: form.thinking,
      reasoning_effort: form.reasoning_effort,
      tools_whitelist: parseListInput(form.tools_whitelist),
      visible: form.visible,
    };
    try {
      if (creating) {
        await apiJson("/api/agents", "POST", { agent_type: form.agent_type.trim(), ...payload });
        showSuccess("Agent 已创建");
      } else if (editing) {
        await apiJson(`/api/agents/${encodeURIComponent(editing.agent_type)}`, "PUT", payload);
        showSuccess("Agent 已保存");
      }
      setCreating(false);
      setEditing(null);
      await load();
    } catch (e) {
      setFormError(e instanceof Error ? e.message : "保存失败");
    } finally {
      setSaving(false);
    }
  };

  /** 播种 bishu-novel 内置 Agent 定义 */
  const handleSeed = async () => {
    setSeeding(true);
    try {
      await apiJson("/api/agents/seed-bishu", "POST");
      showSuccess("内置 Agent 定义已播种");
      await load();
    } catch (e) {
      setError(e instanceof Error ? e.message : "播种失败");
    } finally {
      setSeeding(false);
    }
  };

  /** 删除 Agent 定义（DELETE /api/agents/{agent_type}） */
  const handleDelete = async (agent: AgentDef) => {
    const ok = await confirmDelete({
      title: "删除 Agent",
      description: `确定删除 Agent「${agent.agent_type}」吗？此操作不可恢复。`,
      confirmText: "删除",
      cancelText: "取消",
      variant: "danger",
    });
    if (!ok) return;
    setDeletingId(agent.agent_type);
    try {
      await apiJson(`/api/agents/${encodeURIComponent(agent.agent_type)}`, "DELETE");
      showSuccess(`Agent「${agent.agent_type}」已删除`);
      await load();
    } catch (e) {
      setError(e instanceof Error ? e.message : "删除失败");
    } finally {
      setDeletingId(null);
    }
  };

  if (loading) return <DFLoading text="正在加载 Agent 定义..." />;

  return (
    <div className="space-y-3">
      {/* 工具栏 */}
      <div className="flex flex-wrap items-center gap-2">
        <DFSearchInput
          className="w-56"
          placeholder="搜索 Agent 类型 / 模型..."
          value={search}
          onChange={(e) => setSearch(e.target.value)}
          aria-label="搜索 Agent"
        />
        <div className="ml-auto flex items-center gap-2">
          <DFSecondaryButton onClick={() => void handleSeed()} disabled={seeding} title="导入 bishu-novel 内置 Agent 定义">
            <Sparkles size={12} aria-hidden="true" />
            {seeding ? "播种中..." : "播种内置定义"}
          </DFSecondaryButton>
          <DFSecondaryButton onClick={() => void load()} disabled={refreshing}>
            <RefreshCw size={12} className={refreshing ? "animate-spin motion-reduce:animate-none" : ""} aria-hidden="true" />
            刷新
          </DFSecondaryButton>
          <DFPrimaryButton onClick={openCreate}>
            <Plus size={12} aria-hidden="true" />
            新建 Agent
          </DFPrimaryButton>
        </div>
      </div>

      {/* Agent 卡片列表 */}
      {list.length === 0 ? (
        <DFEmpty
          title={search ? "未找到匹配的 Agent" : "暂无 Agent 定义"}
          description={search ? "换个关键词试试" : "点击「新建 Agent」或「播种内置定义」开始使用"}
        />
      ) : (
        <div className="grid gap-3 md:grid-cols-2" role="list" aria-label="Agent 定义列表">
          {list.map((agent) => (
            <DFCard
              key={agent.agent_type}
              role="listitem"
              className={
                selectedAgentType === agent.agent_type
                  ? "border-amber-500/40 bg-amber-500/5"
                  : ""
              }
            >
              <div className="p-4">
                <div className="flex items-start justify-between gap-2">
                  <div className="flex min-w-0 items-center gap-2">
                    <Bot size={16} className="shrink-0 text-indigo-400" aria-hidden="true" />
                    <button
                      type="button"
                      onClick={() => onSelectAgent?.(agent.agent_type)}
                      className="min-w-0 cursor-pointer truncate font-mono text-sm font-semibold text-foreground hover:text-indigo-300"
                      title={onSelectAgent ? "在编排中查看该 Agent" : agent.agent_type}
                    >
                      {agent.agent_type}
                    </button>
                    {!agent.visible && <DFTag>已隐藏</DFTag>}
                  </div>
                  <div className="flex shrink-0 items-center gap-1">
                    <Switch
                      checked={agent.visible}
                      onCheckedChange={(v) => void handleToggleVisible(agent, v)}
                      aria-label={`${agent.visible ? "隐藏" : "显示"} Agent ${agent.agent_type}`}
                    />
                    <DFIconButton
                      onClick={() => openEdit(agent)}
                      title="编辑"
                      aria-label={`编辑 Agent ${agent.agent_type}`}
                      className="min-h-[36px] min-w-[36px]"
                    >
                      <Pencil size={14} aria-hidden="true" />
                    </DFIconButton>
                    <DFIconButton
                      onClick={() => void handleDelete(agent)}
                      disabled={deletingId === agent.agent_type}
                      title="删除"
                      aria-label={`删除 Agent ${agent.agent_type}`}
                      className="min-h-[36px] min-w-[36px] text-red-400 hover:text-red-300"
                    >
                      <Trash2 size={14} aria-hidden="true" />
                    </DFIconButton>
                  </div>
                </div>
                {agent.description && (
                  <p className="mt-2 line-clamp-2 text-xs leading-relaxed text-muted" title={agent.description}>
                    {agent.description}
                  </p>
                )}
                <div className="mt-3 flex flex-wrap gap-1.5">
                  <DFTag>{agent.model || "默认模型"}</DFTag>
                  <DFTag>temp {agent.temperature}</DFTag>
                  <DFTag>top_p {agent.top_p}</DFTag>
                  <DFTag>{agent.max_turns} 轮</DFTag>
                  {agent.thinking && <DFTag className="border-purple-500/30 text-purple-300">thinking</DFTag>}
                  <DFTag>effort {agent.reasoning_effort || "medium"}</DFTag>
                </div>
                {(agent.tools_whitelist || []).length > 0 && (
                  <p className="mt-2 truncate text-xs text-muted" title={agent.tools_whitelist.join(", ")}>
                    工具白名单：{agent.tools_whitelist.join(", ")}
                  </p>
                )}
              </div>
            </DFCard>
          ))}
        </div>
      )}

      {/* 新建 / 编辑弹窗 */}
      {(creating || editing) && (
        <DFModal
          title={creating ? "新建 Agent 定义" : `编辑 Agent：${form.agent_type}`}
          onClose={() => {
            setCreating(false);
            setEditing(null);
          }}
          wide
          footer={
            <>
              <DFSecondaryButton
                onClick={() => {
                  setCreating(false);
                  setEditing(null);
                }}
                disabled={saving}
              >
                取消
              </DFSecondaryButton>
              <DFPrimaryButton onClick={() => void handleSubmit()} disabled={saving}>
                {saving ? "保存中..." : "保存"}
              </DFPrimaryButton>
            </>
          }
        >
          <div className="space-y-4">
            <DFFormField label="Agent 类型标识" required error={formError ?? undefined} htmlFor="agent-type">
              <DFInput
                id="agent-type"
                value={form.agent_type}
                onChange={(e) => setForm((f) => ({ ...f, agent_type: e.target.value }))}
                disabled={!creating}
                placeholder="如 writer / auditor"
              />
            </DFFormField>
            <DFFormField label="中文说明（这个 Agent 是干什么的）" htmlFor="agent-description">
              <DFInput
                id="agent-description"
                value={form.description}
                onChange={(e) => setForm((f) => ({ ...f, description: e.target.value }))}
                placeholder="如：写手——根据章纲写出章节正文"
              />
            </DFFormField>
            <DFFormField label="模型（从模型管理的供应商里点选，留空使用全局默认模型）" htmlFor="mp-provider">
              <ModelPicker
                value={form.model}
                onChange={(v) => setForm((f) => ({ ...f, model: v }))}
              />
            </DFFormField>
            <div className="grid grid-cols-3 gap-3">
              <DFFormField label="Temperature" htmlFor="agent-temp">
                <DFInput
                  id="agent-temp"
                  type="number"
                  step="0.1"
                  min="0"
                  max="2"
                  value={form.temperature}
                  onChange={(e) => setForm((f) => ({ ...f, temperature: e.target.value }))}
                />
              </DFFormField>
              <DFFormField label="Top P" htmlFor="agent-top-p">
                <DFInput
                  id="agent-top-p"
                  type="number"
                  step="0.01"
                  min="0"
                  max="1"
                  value={form.top_p}
                  onChange={(e) => setForm((f) => ({ ...f, top_p: e.target.value }))}
                />
              </DFFormField>
              <DFFormField label="最大轮次" htmlFor="agent-max-turns">
                <DFInput
                  id="agent-max-turns"
                  type="number"
                  min="1"
                  value={form.max_turns}
                  onChange={(e) => setForm((f) => ({ ...f, max_turns: e.target.value }))}
                />
              </DFFormField>
            </div>
            <DFFormField label="推理强度（reasoning_effort）" htmlFor="agent-effort">
              <DFSelect
                id="agent-effort"
                value={form.reasoning_effort}
                onChange={(e) => setForm((f) => ({ ...f, reasoning_effort: e.target.value }))}
              >
                {REASONING_EFFORTS.map((r) => (
                  <option key={r} value={r}>
                    {r}
                  </option>
                ))}
              </DFSelect>
            </DFFormField>
            <DFFormField label="工具白名单（逗号分隔，留空表示全部可用）" htmlFor="agent-tools">
              <DFInput
                id="agent-tools"
                value={form.tools_whitelist}
                onChange={(e) => setForm((f) => ({ ...f, tools_whitelist: e.target.value }))}
                placeholder="如 read_file, write_file"
              />
            </DFFormField>
            <div className="flex items-center gap-6">
              <label className="flex cursor-pointer items-center gap-2 text-xs text-foreground">
                <Switch
                  checked={form.thinking}
                  onCheckedChange={(v) => setForm((f) => ({ ...f, thinking: v }))}
                />
                开启 Thinking
              </label>
              <label className="flex cursor-pointer items-center gap-2 text-xs text-foreground">
                <Switch
                  checked={form.visible}
                  onCheckedChange={(v) => setForm((f) => ({ ...f, visible: v }))}
                />
                对前端可见
              </label>
            </div>
          </div>
        </DFModal>
      )}

      {deleteDialog}
      <DFErrorToast message={error} onClose={() => setError(null)} />
    </div>
  );
}
