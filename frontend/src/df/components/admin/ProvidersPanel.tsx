/** 模型供应商管理面板：供应商 CRUD / 默认供应商 / 模型发现
 * 对接 /api/models/providers 与 /api/models/discover。
 */
import { useCallback, useEffect, useState } from "react";
import { Pencil, Plus, RefreshCw, Search, Server, Star, Trash2 } from "lucide-react";
import { Switch } from "@/components/ui/switch";
import { apiFetch, apiJson } from "./df-api";
import {
  DFConfirmDialog,
  DFCard,
  DFEmpty,
  DFErrorToast,
  DFFormField,
  DFIconButton,
  DFInput,
  DFLoading,
  DFModal,
  DFPrimaryButton,
  DFSecondaryButton,
  DFTag,
} from "./df-ui";
import { useToast } from "@/hooks/useToast";

/** 模型供应商（api_key 为后端脱敏后的值） */
interface Provider {
  name: string;
  base_url: string;
  api_key: string;
  priority: number;
  is_default: boolean;
}

/** 发现的模型 */
interface DiscoveredModel {
  id: string;
  context_length: number | null;
  owned_by: string;
}

interface ProviderFormState {
  name: string;
  base_url: string;
  api_key: string;
  priority: string;
  is_default: boolean;
}

const EMPTY_FORM: ProviderFormState = {
  name: "",
  base_url: "",
  api_key: "",
  priority: "0",
  is_default: false,
};

export default function ProvidersPanel() {
  const { showSuccess } = useToast();
  const [providers, setProviders] = useState<Provider[]>([]);
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const [creating, setCreating] = useState(false);
  const [editing, setEditing] = useState<Provider | null>(null);
  const [deleting, setDeleting] = useState<Provider | null>(null);
  const [form, setForm] = useState<ProviderFormState>(EMPTY_FORM);
  const [formError, setFormError] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);

  // 模型发现弹窗状态
  const [discovering, setDiscovering] = useState<Provider | null>(null);
  const [models, setModels] = useState<DiscoveredModel[]>([]);
  const [modelsLoading, setModelsLoading] = useState(false);
  const [modelsError, setModelsError] = useState<string | null>(null);

  const load = useCallback(async (initial = false) => {
    if (initial) setLoading(true);
    else setRefreshing(true);
    try {
      const data = await apiFetch<{ providers: Provider[] }>("/api/models/providers");
      setProviders([...(data.providers || [])].sort((a, b) => a.priority - b.priority));
    } catch (e) {
      setError(e instanceof Error ? e.message : "加载模型供应商失败");
    } finally {
      setLoading(false);
      setRefreshing(false);
    }
  }, []);

  useEffect(() => {
    void load(true);
  }, [load]);

  const openCreate = () => {
    setForm(EMPTY_FORM);
    setFormError(null);
    setCreating(true);
  };

  const openEdit = (provider: Provider) => {
    setForm({
      name: provider.name,
      base_url: provider.base_url,
      api_key: "",
      priority: String(provider.priority),
      is_default: provider.is_default,
    });
    setFormError(null);
    setEditing(provider);
  };

  const handleSubmit = async () => {
    if (!form.name.trim()) {
      setFormError("请输入供应商名称");
      return;
    }
    setSaving(true);
    setFormError(null);
    try {
      if (creating) {
        await apiJson("/api/models/providers", "POST", {
          name: form.name.trim(),
          base_url: form.base_url.trim(),
          api_key: form.api_key,
          priority: Number(form.priority) || 0,
          is_default: form.is_default,
        });
        showSuccess("供应商已创建");
      } else if (editing) {
        // api_key 留空表示不修改已保存的密钥
        const payload: Record<string, unknown> = {
          base_url: form.base_url.trim(),
          priority: Number(form.priority) || 0,
          is_default: form.is_default,
        };
        if (form.api_key) payload.api_key = form.api_key;
        await apiJson(`/api/models/providers/${encodeURIComponent(editing.name)}`, "PUT", payload);
        showSuccess("供应商已保存");
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
      await apiJson(`/api/models/providers/${encodeURIComponent(deleting.name)}`, "DELETE");
      showSuccess("供应商已删除");
      setDeleting(null);
      await load();
    } catch (e) {
      setError(e instanceof Error ? e.message : "删除失败");
    } finally {
      setSaving(false);
    }
  };

  /** 发现模型：调用供应商的 /models 端点 */
  const handleDiscover = async (provider: Provider) => {
    setDiscovering(provider);
    setModels([]);
    setModelsError(null);
    setModelsLoading(true);
    try {
      const data = await apiFetch<{ models: DiscoveredModel[] }>(
        `/api/models/discover?provider=${encodeURIComponent(provider.name)}`,
      );
      setModels(data.models || []);
    } catch (e) {
      setModelsError(e instanceof Error ? e.message : "模型发现失败");
    } finally {
      setModelsLoading(false);
    }
  };

  if (loading) return <DFLoading text="正在加载模型供应商..." />;

  return (
    <div className="space-y-3">
      {/* 工具栏 */}
      <div className="flex items-center justify-between gap-2">
        <span className="text-xs text-muted tabular-nums">共 {providers.length} 个供应商</span>
        <div className="flex items-center gap-2">
          <DFSecondaryButton onClick={() => void load()} disabled={refreshing}>
            <RefreshCw size={12} className={refreshing ? "animate-spin motion-reduce:animate-none" : ""} aria-hidden="true" />
            刷新
          </DFSecondaryButton>
          <DFPrimaryButton onClick={openCreate}>
            <Plus size={12} aria-hidden="true" />
            新建供应商
          </DFPrimaryButton>
        </div>
      </div>

      {/* 供应商列表 */}
      {providers.length === 0 ? (
        <DFEmpty title="暂无模型供应商" description="点击「新建供应商」添加 OpenAI 兼容接口" />
      ) : (
        <div className="space-y-2" role="list" aria-label="模型供应商列表">
          {providers.map((p) => (
            <DFCard key={p.name} role="listitem" className="p-4">
              <div className="flex items-start justify-between gap-3">
                <div className="min-w-0 flex-1">
                  <div className="flex flex-wrap items-center gap-2">
                    <Server size={15} className="shrink-0 text-indigo-400" aria-hidden="true" />
                    <span className="text-sm font-semibold text-foreground">{p.name}</span>
                    {p.is_default && (
                      <DFTag className="border-amber-500/30 text-amber-300">
                        <Star size={10} className="mr-1" aria-hidden="true" />
                        默认
                      </DFTag>
                    )}
                    <DFTag>优先级 {p.priority}</DFTag>
                  </div>
                  <div className="mt-2 space-y-1 text-xs text-muted">
                    <p className="truncate" title={p.base_url}>
                      Base URL：<span className="font-mono">{p.base_url || "（未配置）"}</span>
                    </p>
                    <p>
                      API Key：<span className="font-mono">{p.api_key || "（未配置）"}</span>
                    </p>
                  </div>
                </div>
                <div className="flex shrink-0 items-center gap-1">
                  <DFSecondaryButton onClick={() => void handleDiscover(p)}>
                    <Search size={12} aria-hidden="true" />
                    发现模型
                  </DFSecondaryButton>
                  <DFIconButton onClick={() => openEdit(p)} title="编辑" aria-label={`编辑供应商 ${p.name}`}>
                    <Pencil size={14} aria-hidden="true" />
                  </DFIconButton>
                  <DFIconButton
                    onClick={() => setDeleting(p)}
                    title="删除"
                    aria-label={`删除供应商 ${p.name}`}
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
          title={creating ? "新建模型供应商" : `编辑供应商：${form.name}`}
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
            <DFFormField label="供应商名称" required error={formError ?? undefined} htmlFor="provider-name">
              <DFInput
                id="provider-name"
                value={form.name}
                onChange={(e) => setForm((f) => ({ ...f, name: e.target.value }))}
                disabled={!creating}
                placeholder="如 deepseek"
              />
            </DFFormField>
            <DFFormField label="Base URL" htmlFor="provider-base-url">
              <DFInput
                id="provider-base-url"
                value={form.base_url}
                onChange={(e) => setForm((f) => ({ ...f, base_url: e.target.value }))}
                placeholder="如 https://api.deepseek.com/v1"
              />
            </DFFormField>
            <DFFormField
              label="API Key"
              htmlFor="provider-api-key"
              hint={editing ? "留空表示不修改已保存的密钥" : undefined}
            >
              <DFInput
                id="provider-api-key"
                type="password"
                value={form.api_key}
                onChange={(e) => setForm((f) => ({ ...f, api_key: e.target.value }))}
                placeholder={editing ? "（已保存，留空不修改）" : "sk-..."}
                autoComplete="new-password"
              />
            </DFFormField>
            <DFFormField label="优先级（数字越小越优先）" htmlFor="provider-priority">
              <DFInput
                id="provider-priority"
                type="number"
                value={form.priority}
                onChange={(e) => setForm((f) => ({ ...f, priority: e.target.value }))}
              />
            </DFFormField>
            <label className="flex cursor-pointer items-center gap-2 text-xs text-foreground">
              <Switch
                checked={form.is_default}
                onCheckedChange={(v) => setForm((f) => ({ ...f, is_default: v }))}
              />
              设为默认供应商
            </label>
          </div>
        </DFModal>
      )}

      {/* 删除确认 */}
      {deleting && (
        <DFConfirmDialog
          title="删除供应商"
          message={`确定删除供应商「${deleting.name}」吗？其 API Key 配置将一并移除。`}
          loading={saving}
          onCancel={() => setDeleting(null)}
          onConfirm={() => void handleDelete()}
        />
      )}

      {/* 模型发现弹窗 */}
      {discovering && (
        <DFModal
          title={`发现模型：${discovering.name}`}
          onClose={() => setDiscovering(null)}
          wide
        >
          {modelsLoading ? (
            <DFLoading text="正在向供应商请求模型列表..." />
          ) : modelsError ? (
            <p className="py-6 text-center text-sm text-red-400" role="alert">
              {modelsError}
            </p>
          ) : models.length === 0 ? (
            <p className="py-6 text-center text-sm text-muted">该供应商未返回任何模型</p>
          ) : (
            <div className="space-y-1.5" role="list" aria-label="发现的模型列表">
              {models.map((m) => (
                <div
                  key={m.id}
                  role="listitem"
                  className="flex items-center justify-between rounded-lg border border-border bg-surface px-3 py-2"
                >
                  <span className="font-mono text-xs text-foreground">{m.id}</span>
                  <span className="text-xs text-muted tabular-nums">
                    {m.context_length ? `${m.context_length.toLocaleString()} tokens` : "上下文未知"}
                  </span>
                </div>
              ))}
            </div>
          )}
        </DFModal>
      )}

      <DFErrorToast message={error} onClose={() => setError(null)} />
    </div>
  );
}
