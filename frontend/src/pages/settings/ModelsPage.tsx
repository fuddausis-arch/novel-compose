/** 全局设置 · 模型管理页：供应商卡片列表，支持新增 / 编辑 / 删除 + 模型发现 */
import { useCallback, useEffect, useState, type ReactNode } from "react";
import { Cpu, Loader2, Pencil, Plus, RefreshCw, Search, Trash2, X } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Select } from "@/components/ui/select";
import { Switch } from "@/components/ui/switch";
import { EmptyState } from "@/components/ui/empty-state";
import { Dialog, DialogContent, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { useToast } from "@/hooks/useToast";

interface Provider {
  name: string;
  base_url: string;
  api_key?: string;
  models?: string[];
  priority: number;
  is_default?: boolean;
  /** 思考模式：null=跟随默认（DeepSeek 开/火山自动关）；true=强制开；false=强制关 */
  enable_thinking?: boolean | null;
}

interface ProviderForm {
  name: string;
  base_url: string;
  api_key: string;
  models: string;
  priority: string;
  is_default: boolean;
  /** auto=跟随默认；on=强制开启；off=强制关闭 */
  enable_thinking: "auto" | "on" | "off";
}

const EMPTY_FORM: ProviderForm = {
  name: "",
  base_url: "",
  api_key: "",
  models: "",
  priority: "0",
  is_default: false,
  enable_thinking: "auto",
};

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

export default function ModelsPage() {
  const { showError, showSuccess } = useToast();
  const [providers, setProviders] = useState<Provider[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [reloading, setReloading] = useState(false);
  // 弹窗状态
  const [editorOpen, setEditorOpen] = useState(false);
  const [editingName, setEditingName] = useState<string | null>(null); // null=创建, 有值=编辑
  const [form, setForm] = useState<ProviderForm>(EMPTY_FORM);
  const [saving, setSaving] = useState(false);
  const [deleteTarget, setDeleteTarget] = useState<string | null>(null);
  const [deleting, setDeleting] = useState(false);
  // 模型发现
  const [discovering, setDiscovering] = useState<string | null>(null);

  const load = useCallback(async (silent = false) => {
    // silent=true：静默刷新（保存/删除/发现后用），不切 loading 保持滚动容器常驻不跳顶
    if (!silent) setLoading(true);
    setError(null);
    try {
      const data = await fetchJson<{ providers: Provider[] }>("/api/models/providers");
      setProviders(data.providers || []);
    } catch (e) {
      setError(e instanceof Error ? e.message : "加载失败");
      setProviders([]);
    } finally {
      if (!silent) setLoading(false);
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

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
    setForm(EMPTY_FORM);
    setEditingName(null);
    setEditorOpen(true);
  };

  const openEdit = (p: Provider) => {
    setForm({
      name: p.name,
      base_url: p.base_url || "",
      api_key: "", // 脱敏的 key 不回填，留空表示不修改
      models: (p.models ?? []).join(", "),
      priority: String(p.priority ?? 0),
      is_default: !!p.is_default,
      enable_thinking: p.enable_thinking === false ? "off" : p.enable_thinking === true ? "on" : "auto",
    });
    setEditingName(p.name);
    setEditorOpen(true);
  };

  const handleSave = async () => {
    if (!form.name.trim()) {
      showError("请输入供应商名称");
      return;
    }
    setSaving(true);
    try {
      const models = form.models.split(",").map((m) => m.trim()).filter(Boolean);
      const isEdit = !!editingName;
      const body: Record<string, unknown> = {
        base_url: form.base_url.trim(),
        models,
        priority: Number(form.priority) || 0,
        is_default: form.is_default,
        // 思考模式：auto → null（跟随默认）；on/off → true/false
        enable_thinking: form.enable_thinking === "auto" ? null : form.enable_thinking === "on",
      };
      // api_key 留空时不传（编辑时不修改 key）
      if (form.api_key.trim()) {
        body.api_key = form.api_key.trim();
      }
      if (isEdit) {
        await fetchJson(`/api/models/providers/${encodeURIComponent(editingName!)}`, {
          method: "PUT",
          body: JSON.stringify(body),
        });
        showSuccess("已保存");
      } else {
        body.name = form.name.trim();
        body.api_key = form.api_key.trim();
        await fetchJson("/api/models/providers", {
          method: "POST",
          body: JSON.stringify(body),
        });
        showSuccess("已创建");
      }
      setEditorOpen(false);
      await load(true);
    } catch (e) {
      showError(e instanceof Error ? e.message : "保存失败");
    } finally {
      setSaving(false);
    }
  };

  // ---- 删除 ----
  const openDelete = (name: string) => {
    setDeleteTarget(name);
    // 注意：不要 setDeleting(true)，否则确认按钮被永久禁用
  };
  const handleDelete = async () => {
    if (!deleteTarget) return;
    setDeleting(true);
    try {
      await fetchJson(`/api/models/providers/${encodeURIComponent(deleteTarget)}`, { method: "DELETE" });
      showSuccess(`已删除 ${deleteTarget}`);
      setDeleteTarget(null);
      await load(true);
    } catch (e) {
      showError(e instanceof Error ? e.message : "删除失败");
    } finally {
      setDeleting(false);
    }
  };

  // ---- 模型发现 ----
  const handleDiscover = async (providerName: string) => {
    setDiscovering(providerName);
    try {
      const data = await fetchJson<{ models: Array<{ id: string; context_length?: number }> }>(
        `/api/models/discover?provider=${encodeURIComponent(providerName)}`,
      );
      const models = data.models.map((m) => m.id);
      if (models.length === 0) {
        showError("未发现可用模型");
        return;
      }
      // 更新该供应商的 models 字段
      await fetchJson(`/api/models/providers/${encodeURIComponent(providerName)}`, {
        method: "PUT",
        body: JSON.stringify({ models }),
      });
      showSuccess(`发现 ${models.length} 个模型`);
      await load(true);
    } catch (e) {
      showError(e instanceof Error ? e.message : "发现失败");
    } finally {
      setDiscovering(null);
    }
  };

  // ---- 手动添加/删除单个模型 ----
  const [addModelTarget, setAddModelTarget] = useState<string | null>(null);
  const [newModelName, setNewModelName] = useState("");
  const [addingModel, setAddingModel] = useState(false);

  const handleAddModel = async (providerName: string) => {
    if (!newModelName.trim()) return;
    setAddingModel(true);
    try {
      const p = providers.find((x) => x.name === providerName);
      const existing = p?.models ?? [];
      // 去重
      if (existing.includes(newModelName.trim())) {
        showError("模型已存在");
        return;
      }
      const models = [...existing, newModelName.trim()];
      await fetchJson(`/api/models/providers/${encodeURIComponent(providerName)}`, {
        method: "PUT",
        body: JSON.stringify({ models }),
      });
      showSuccess(`已添加模型 ${newModelName.trim()}`);
      setNewModelName("");
      setAddModelTarget(null);
      await load(true);
    } catch (e) {
      showError(e instanceof Error ? e.message : "添加失败");
    } finally {
      setAddingModel(false);
    }
  };

  const handleRemoveModel = async (providerName: string, modelName: string) => {
    const p = providers.find((x) => x.name === providerName);
    if (!p) return;
    const models = (p.models ?? []).filter((m) => m !== modelName);
    try {
      await fetchJson(`/api/models/providers/${encodeURIComponent(providerName)}`, {
        method: "PUT",
        body: JSON.stringify({ models }),
      });
      showSuccess(`已移除模型 ${modelName}`);
      await load(true);
    } catch (e) {
      showError(e instanceof Error ? e.message : "移除失败");
    }
  };

  const header = (
    <div className="flex flex-col gap-4 sm:flex-row sm:items-center sm:justify-between">
      <div className="flex items-center gap-3">
        <div className="rounded-lg border border-border bg-primary-muted p-2 text-primary">
          <Cpu className="h-5 w-5" />
        </div>
        <div>
          <h2 className="text-lg font-semibold">模型管理</h2>
          <p className="text-sm text-muted">配置 LLM 供应商、API 地址、模型列表与优先级</p>
        </div>
      </div>
      <div className="flex gap-2">
        <Button variant="primary" size="sm" onClick={openCreate}>
          <Plus className="h-4 w-4" />
          添加供应商
        </Button>
        <Button variant="outline" size="sm" onClick={() => void handleReload()} disabled={reloading}>
          <RefreshCw className={`h-4 w-4 ${reloading ? "animate-spin" : ""}`} />
          重新加载
        </Button>
      </div>
    </div>
  );

  let body: ReactNode;
  if (loading) {
    body = (
      <div className="flex items-center justify-center py-20">
        <Loader2 className="mr-2 h-5 w-5 animate-spin text-muted" />
        <span className="text-sm text-muted">正在加载供应商...</span>
      </div>
    );
  } else if (error || providers.length === 0) {
    body = (
      <EmptyState
        icon={<Cpu className="h-10 w-10 text-muted" />}
        title={error ? "后端模型供应商尚未接入" : "暂无供应商"}
        description={error ?? "点击「添加供应商」配置第一个 LLM 供应商"}
      />
    );
  } else {
    body = (
      <div className="grid gap-4 md:grid-cols-2">
        {providers.map((p) => (
          <Card key={p.name} className="space-y-3 p-4">
            <div className="flex items-start justify-between gap-2">
              <div className="min-w-0 flex-1">
                <div className="flex flex-wrap items-center gap-2">
                  <span className="truncate text-sm font-semibold">{p.name}</span>
                  <Badge variant="primary">P{p.priority}</Badge>
                  {p.is_default && <Badge variant="success">默认</Badge>}
                </div>
                <p className="mt-0.5 truncate font-mono text-xs text-muted" title={p.base_url}>
                  {p.base_url || "—"}
                </p>
                {p.api_key && (
                  <p className="mt-0.5 truncate font-mono text-[10px] text-muted">
                    Key: {p.api_key}
                  </p>
                )}
              </div>
              <div className="flex shrink-0 gap-1">
                <Button variant="ghost" size="sm" onClick={() => openEdit(p)} aria-label="编辑">
                  <Pencil className="h-4 w-4" />
                </Button>
                <Button
                  variant="ghost"
                  size="sm"
                  onClick={() => openDelete(p.name)}
                  disabled={deleting && deleteTarget === p.name}
                  className="text-danger hover:text-danger"
                  aria-label="删除"
                >
                  <Trash2 className="h-4 w-4" />
                </Button>
              </div>
            </div>
            <div>
              <div className="mb-1.5 flex items-center justify-between">
                <span className="text-xs font-medium text-muted">
                  模型 {(p.models ?? []).length > 0 && `(${(p.models ?? []).length})`}
                </span>
                <div className="flex items-center gap-3">
                  <button
                    type="button"
                    onClick={() => void handleDiscover(p.name)}
                    disabled={discovering === p.name}
                    className="flex items-center gap-1 text-[10px] text-primary hover:underline disabled:opacity-50"
                  >
                    {discovering === p.name ? (
                      <Loader2 className="h-3 w-3 animate-spin" />
                    ) : (
                      <Search className="h-3 w-3" />
                    )}
                    发现模型
                  </button>
                  <button
                    type="button"
                    onClick={() => {
                      setAddModelTarget(addModelTarget === p.name ? null : p.name);
                      setNewModelName("");
                    }}
                    className="flex items-center gap-1 text-[10px] text-success hover:underline"
                  >
                    <Plus className="h-3 w-3" />
                    添加模型
                  </button>
                </div>
              </div>
              {(p.models ?? []).length === 0 ? (
                <span className="text-xs text-muted">
                  未配置模型（点「发现模型」自动拉取，或「添加模型」手动填写）
                </span>
              ) : (
                <div className="flex flex-wrap gap-1.5">
                  {(p.models ?? []).map((m) => (
                    <span
                      key={m}
                      className="inline-flex items-center gap-1 rounded-md border border-border bg-secondary px-1.5 py-0.5 font-mono text-[10px]"
                    >
                      {m}
                      <button
                        type="button"
                        onClick={() => void handleRemoveModel(p.name, m)}
                        className="text-muted hover:text-danger"
                        aria-label={`移除模型 ${m}`}
                      >
                        <X className="h-2.5 w-2.5" />
                      </button>
                    </span>
                  ))}
                </div>
              )}
              {/* 添加模型输入框 */}
              {addModelTarget === p.name && (
                <div className="mt-2 flex gap-1.5">
                  <Input
                    value={newModelName}
                    onChange={(e) => setNewModelName(e.target.value)}
                    onKeyDown={(e) => {
                      if (e.key === "Enter") void handleAddModel(p.name);
                      if (e.key === "Escape") setAddModelTarget(null);
                    }}
                    placeholder="输入模型名，如 gpt-4o"
                    className="h-7 flex-1 font-mono text-xs"
                    autoFocus
                  />
                  <Button
                    variant="primary"
                    size="sm"
                    onClick={() => void handleAddModel(p.name)}
                    disabled={addingModel || !newModelName.trim()}
                    className="h-7 px-2"
                  >
                    {addingModel ? <Loader2 className="h-3 w-3 animate-spin" /> : "添加"}
                  </Button>
                  <Button
                    variant="ghost"
                    size="sm"
                    onClick={() => {
                      setAddModelTarget(null);
                      setNewModelName("");
                    }}
                    className="h-7 px-2"
                  >
                    取消
                  </Button>
                </div>
              )}
            </div>
          </Card>
        ))}
      </div>
    );
  }

  return (
    <div className="h-full overflow-y-auto">
      <div className="mx-auto max-w-6xl space-y-6 p-6">
        {header}
        {body}
      </div>

      {/* 创建/编辑弹窗 */}
      <Dialog open={editorOpen} onOpenChange={(o) => !o && !saving && setEditorOpen(false)}>
        <DialogContent className="max-h-[90vh] max-w-lg overflow-y-auto">
          <DialogHeader>
            <DialogTitle>{editingName ? "编辑供应商" : "添加供应商"}</DialogTitle>
          </DialogHeader>
          <div className="space-y-3">
              <div>
                <Label htmlFor="p-name">名称</Label>
                <Input
                  id="p-name"
                  value={form.name}
                  onChange={(e) => setForm((f) => ({ ...f, name: e.target.value }))}
                  disabled={!!editingName}
                  placeholder="如 DeepSeek / VolcanoArk"
                  className="mt-1"
                />
                {editingName && (
                  <p className="mt-1 text-xs text-muted">名称创建后不可修改</p>
                )}
              </div>
              <div>
                <Label htmlFor="p-url">Base URL</Label>
                <Input
                  id="p-url"
                  value={form.base_url}
                  onChange={(e) => setForm((f) => ({ ...f, base_url: e.target.value }))}
                  placeholder="https://api.deepseek.com"
                  className="mt-1 font-mono text-xs"
                />
              </div>
              <div>
                <Label htmlFor="p-key">
                  API Key{editingName && "（留空不修改）"}
                </Label>
                <Input
                  id="p-key"
                  type="password"
                  value={form.api_key}
                  onChange={(e) => setForm((f) => ({ ...f, api_key: e.target.value }))}
                  placeholder={editingName ? "留空保持不变" : "sk-xxxx 或 ark-xxxx"}
                  className="mt-1 font-mono text-xs"
                />
              </div>
              <div>
                <Label htmlFor="p-models">模型列表（逗号分隔）</Label>
                <Input
                  id="p-models"
                  value={form.models}
                  onChange={(e) => setForm((f) => ({ ...f, models: e.target.value }))}
                  placeholder="deepseek-v4-flash, deepseek-reasoner"
                  className="mt-1 font-mono text-xs"
                />
                <p className="mt-1 text-xs text-muted">保存后也可点卡片上的「发现模型」自动拉取</p>
              </div>
              <div className="grid grid-cols-2 gap-3">
                <div>
                  <Label htmlFor="p-priority">优先级（数字越大越优先）</Label>
                  <Input
                    id="p-priority"
                    type="number"
                    value={form.priority}
                    onChange={(e) => setForm((f) => ({ ...f, priority: e.target.value }))}
                    className="mt-1"
                  />
                </div>
                <div className="flex items-end gap-2 pb-1">
                  <Switch
                    id="p-default"
                    checked={form.is_default}
                    onCheckedChange={(v) => setForm((f) => ({ ...f, is_default: v }))}
                  />
                  <Label htmlFor="p-default" className="text-xs text-muted">设为默认</Label>
                </div>
              </div>
              <div>
                <Label htmlFor="p-thinking">思考模式</Label>
                <Select
                  id="p-thinking"
                  className="mt-1"
                  value={form.enable_thinking}
                  onChange={(e) => setForm((f) => ({ ...f, enable_thinking: e.target.value as ProviderForm["enable_thinking"] }))}
                >
                  <option value="auto">跟随默认（DeepSeek 开启，火山自动关闭）</option>
                  <option value="on">强制开启（分析更深入，更耗 token）</option>
                  <option value="off">强制关闭（省钱）</option>
                </Select>
                <p className="mt-1 text-xs text-muted">
                  蒸馏、聊天、交互创作等默认继承此设置；火山 coding 网关不支持思考参数，会强制关闭
                </p>
              </div>
            </div>
            <div className="mt-5 flex justify-end gap-2">
              <Button variant="ghost" size="sm" onClick={() => setEditorOpen(false)} disabled={saving}>
                取消
              </Button>
              <Button variant="primary" size="sm" onClick={() => void handleSave()} disabled={saving}>
                {saving ? <Loader2 className="mr-1 h-4 w-4 animate-spin" /> : null}
                {saving ? "保存中..." : editingName ? "保存" : "创建"}
              </Button>
            </div>
        </DialogContent>
      </Dialog>

      {/* 删除确认弹窗 */}
      <Dialog open={deleteTarget !== null} onOpenChange={(o) => !o && !deleting && setDeleteTarget(null)}>
        <DialogContent className="max-w-md">
          <DialogHeader>
            <DialogTitle className="text-danger">删除供应商</DialogTitle>
          </DialogHeader>
          <p className="text-sm text-muted">
            确定删除供应商 <code className="rounded bg-secondary px-1 font-mono">{deleteTarget}</code> 吗？此操作不可撤销。
          </p>
          <div className="mt-6 flex justify-end gap-2">
            <Button variant="outline" size="sm" onClick={() => setDeleteTarget(null)} disabled={deleting}>
              取消
            </Button>
            <Button variant="danger" size="sm" onClick={() => void handleDelete()} disabled={deleting}>
              {deleting ? <Loader2 className="mr-1 h-4 w-4 animate-spin" /> : <Trash2 className="mr-1 h-4 w-4" />}
              确认删除
            </Button>
          </div>
        </DialogContent>
      </Dialog>
    </div>
  );
}
