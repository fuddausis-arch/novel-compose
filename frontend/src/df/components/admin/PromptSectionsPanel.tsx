/** Prompt Section 编排面板：列表 / 启停 / 排序 / 新建 / 编辑 / 删除
 * 供「系统提示词」与「编排」两个页面复用，对接 /api/prompts 系列端点。
 */
import { useCallback, useEffect, useState } from "react";
import { ArrowDown, ArrowUp, GripVertical, Pencil, Plus, RefreshCw, Trash2 } from "lucide-react";
import { Switch } from "@/components/ui/switch";
import { apiFetch, apiJson } from "./df-api";
import {
  DFConfirmDialog,
  DFCard,
  DFErrorToast,
  DFFormField,
  DFIconButton,
  DFInput,
  DFLoading,
  DFModal,
  DFPrimaryButton,
  DFSecondaryButton,
  DFTextarea,
} from "./df-ui";
import { useToast } from "@/hooks/useToast";

/** Prompt Section 数据结构（与后端 SectionInput 对齐） */
export interface PromptSection {
  name: string;
  content: string;
  enabled: boolean;
  order: number;
}

interface SectionFormState {
  name: string;
  content: string;
  order: number;
}

export default function PromptSectionsPanel({ agentType }: { agentType: string }) {
  const { showSuccess } = useToast();
  const [sections, setSections] = useState<PromptSection[]>([]);
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);
  const [error, setError] = useState<string | null>(null);

  // 弹窗状态：新建 / 编辑 / 删除
  const [creating, setCreating] = useState(false);
  const [editing, setEditing] = useState<PromptSection | null>(null);
  const [deleting, setDeleting] = useState<PromptSection | null>(null);
  const [form, setForm] = useState<SectionFormState>({ name: "", content: "", order: 0 });
  const [formError, setFormError] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);

  const load = useCallback(
    async (initial = false) => {
      if (initial) setLoading(true);
      else setRefreshing(true);
      try {
        const data = await apiFetch<{ sections: PromptSection[] }>(
          `/api/prompts/${encodeURIComponent(agentType)}`,
        );
        // 按 order 升序展示
        setSections([...(data.sections || [])].sort((a, b) => a.order - b.order));
      } catch (e) {
        setError(e instanceof Error ? e.message : "加载 Prompt Section 失败");
      } finally {
        setLoading(false);
        setRefreshing(false);
      }
    },
    [agentType],
  );

  useEffect(() => {
    setSections([]);
    void load(true);
  }, [load]);

  /** 启停开关：乐观更新 + 失败回滚 */
  const handleToggle = async (section: PromptSection, enabled: boolean) => {
    const snapshot = sections;
    setSections((prev) => prev.map((s) => (s.name === section.name ? { ...s, enabled } : s)));
    try {
      await apiJson(
        `/api/prompts/${encodeURIComponent(agentType)}/${encodeURIComponent(section.name)}/toggle`,
        "PUT",
        { enabled },
      );
    } catch (e) {
      setSections(snapshot);
      setError(e instanceof Error ? e.message : "切换启停状态失败");
    }
  };

  /** 上移/下移：交换相邻两项的 order 值后分别提交 */
  const handleMove = async (index: number, direction: -1 | 1) => {
    const target = index + direction;
    if (target < 0 || target >= sections.length) return;
    const a = sections[index];
    const b = sections[target];
    try {
      await apiJson(
        `/api/prompts/${encodeURIComponent(agentType)}/${encodeURIComponent(a.name)}`,
        "PUT",
        { order: b.order },
      );
      await apiJson(
        `/api/prompts/${encodeURIComponent(agentType)}/${encodeURIComponent(b.name)}`,
        "PUT",
        { order: a.order },
      );
      await load();
    } catch (e) {
      setError(e instanceof Error ? e.message : "调整排序失败");
    }
  };

  const openCreate = () => {
    const maxOrder = sections.reduce((m, s) => Math.max(m, s.order), 0);
    setForm({ name: "", content: "", order: maxOrder + 10 });
    setFormError(null);
    setCreating(true);
  };

  const openEdit = (section: PromptSection) => {
    setForm({ name: section.name, content: section.content, order: section.order });
    setFormError(null);
    setEditing(section);
  };

  /** 提交新建/编辑表单 */
  const handleSubmit = async () => {
    if (!form.name.trim()) {
      setFormError("请输入 Section 名称");
      return;
    }
    setSaving(true);
    setFormError(null);
    try {
      if (creating) {
        await apiJson(`/api/prompts/${encodeURIComponent(agentType)}`, "POST", {
          name: form.name.trim(),
          content: form.content,
          enabled: true,
          order: form.order,
        });
        showSuccess("Section 已创建");
      } else if (editing) {
        await apiJson(
          `/api/prompts/${encodeURIComponent(agentType)}/${encodeURIComponent(editing.name)}`,
          "PUT",
          { content: form.content, order: form.order },
        );
        showSuccess("Section 已保存");
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

  const handleDelete = async () => {
    if (!deleting) return;
    setSaving(true);
    try {
      await apiJson(
        `/api/prompts/${encodeURIComponent(agentType)}/${encodeURIComponent(deleting.name)}`,
        "DELETE",
      );
      showSuccess("Section 已删除");
      setDeleting(null);
      await load();
    } catch (e) {
      setError(e instanceof Error ? e.message : "删除失败");
    } finally {
      setSaving(false);
    }
  };

  if (loading) return <DFLoading text="正在加载 Prompt Section..." />;

  return (
    <div className="space-y-3">
      {/* 工具栏 */}
      <div className="flex items-center justify-between gap-2">
        <span className="text-xs text-muted tabular-nums">
          共 {sections.length} 个 Section，已启用 {sections.filter((s) => s.enabled).length} 个
        </span>
        <div className="flex items-center gap-2">
          <DFSecondaryButton onClick={() => void load()} disabled={refreshing}>
            <RefreshCw
              size={12}
              className={refreshing ? "animate-spin motion-reduce:animate-none" : ""}
              aria-hidden="true"
            />
            刷新
          </DFSecondaryButton>
          <DFPrimaryButton onClick={openCreate}>
            <Plus size={12} aria-hidden="true" />
            新建 Section
          </DFPrimaryButton>
        </div>
      </div>

      {/* Section 列表 */}
      {sections.length === 0 ? (
        <DFCard className="p-8 text-center text-sm text-muted">
          当前 Agent（{agentType}）暂无 Prompt Section，点击「新建 Section」添加
        </DFCard>
      ) : (
        <div className="space-y-2" role="list" aria-label="Prompt Section 列表">
          {sections.map((section, index) => (
            <DFCard
              key={section.name}
              className={cn_card(section.enabled)}
              role="listitem"
            >
              <div className="flex items-start gap-3 p-3">
                <GripVertical
                  size={14}
                  className="mt-1 shrink-0 text-muted"
                  aria-hidden="true"
                />
                <div className="min-w-0 flex-1">
                  <div className="flex flex-wrap items-center gap-2">
                    <span className="font-mono text-sm font-medium text-foreground">{section.name}</span>
                    <span className="rounded bg-surface-hover px-1.5 py-0.5 text-xs text-muted tabular-nums">
                      order: {section.order}
                    </span>
                    {!section.enabled && (
                      <span className="text-xs text-muted">（已停用）</span>
                    )}
                  </div>
                  <p className="mt-1 line-clamp-2 whitespace-pre-wrap text-xs text-muted">
                    {section.content || "（无内容）"}
                  </p>
                </div>
                <div className="flex shrink-0 items-center gap-1">
                  <Switch
                    checked={section.enabled}
                    onCheckedChange={(v) => void handleToggle(section, v)}
                    aria-label={`${section.enabled ? "停用" : "启用"} Section ${section.name}`}
                  />
                  <DFIconButton
                    onClick={() => void handleMove(index, -1)}
                    disabled={index === 0}
                    title="上移"
                    aria-label={`上移 ${section.name}`}
                  >
                    <ArrowUp size={14} aria-hidden="true" />
                  </DFIconButton>
                  <DFIconButton
                    onClick={() => void handleMove(index, 1)}
                    disabled={index === sections.length - 1}
                    title="下移"
                    aria-label={`下移 ${section.name}`}
                  >
                    <ArrowDown size={14} aria-hidden="true" />
                  </DFIconButton>
                  <DFIconButton
                    onClick={() => openEdit(section)}
                    title="编辑"
                    aria-label={`编辑 ${section.name}`}
                  >
                    <Pencil size={14} aria-hidden="true" />
                  </DFIconButton>
                  <DFIconButton
                    onClick={() => setDeleting(section)}
                    title="删除"
                    aria-label={`删除 ${section.name}`}
                    className="hover:text-red-400"
                  >
                    <Trash2 size={14} aria-hidden="true" />
                  </DFIconButton>
                </div>
              </div>
            </DFCard>
          ))}
        </div>
      )}

      {/* 新建 / 编辑弹窗 */}
      {(creating || editing) && (
        <DFModal
          title={creating ? "新建 Prompt Section" : `编辑 Section：${form.name}`}
          onClose={() => {
            setCreating(false);
            setEditing(null);
          }}
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
            <DFFormField label="Section 名称" required error={formError ?? undefined} htmlFor="section-name">
              <DFInput
                id="section-name"
                value={form.name}
                onChange={(e) => setForm((f) => ({ ...f, name: e.target.value }))}
                disabled={!creating}
                placeholder="如 role_definition"
              />
            </DFFormField>
            <DFFormField label="排序值（order，越小越靠前）" htmlFor="section-order">
              <DFInput
                id="section-order"
                type="number"
                value={form.order}
                onChange={(e) => setForm((f) => ({ ...f, order: Number(e.target.value) || 0 }))}
              />
            </DFFormField>
            <DFFormField label="内容" htmlFor="section-content">
              <DFTextarea
                id="section-content"
                rows={10}
                value={form.content}
                onChange={(e) => setForm((f) => ({ ...f, content: e.target.value }))}
                placeholder="该 Section 注入 system prompt 的文本内容"
                className="font-mono text-xs"
              />
            </DFFormField>
          </div>
        </DFModal>
      )}

      {/* 删除确认 */}
      {deleting && (
        <DFConfirmDialog
          title="删除 Section"
          message={`确定删除 Section「${deleting.name}」吗？此操作不可恢复。`}
          loading={saving}
          onCancel={() => setDeleting(null)}
          onConfirm={() => void handleDelete()}
        />
      )}

      <DFErrorToast message={error} onClose={() => setError(null)} />
    </div>
  );
}

/** 卡片样式：停用时降低透明度 */
function cn_card(enabled: boolean): string {
  return enabled ? "" : "opacity-60";
}
