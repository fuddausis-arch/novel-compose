import { useCallback, useEffect, useState } from "react";
import { Check, ChevronDown, Loader2, RotateCcw, Save, TestTube } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Select } from "@/components/ui/select";
import { Switch } from "@/components/ui/switch";
import { Badge } from "@/components/ui/badge";
import { api } from "@/api";
import { useToast } from "@/hooks/useToast";
import type { AgentLLMConfig, EmbeddingConfig, LLMConfig } from "@/types";

const DEFAULT_CONFIG: LLMConfig = {
  base_url: "https://api.openai.com/v1",
  api_key: "",
  model: "gpt-4o-mini",
  temperature: 0.7,
  max_tokens: 4000,
  timeout: 180,
  vision_enabled: false,
  top_p: 1,
  frequency_penalty: 0,
  presence_penalty: 0,
};

const MODEL_CONTEXT_LENGTHS: Record<string, number> = {
  "gpt-4o": 128000,
  "gpt-4o-mini": 128000,
  "gpt-4-turbo": 128000,
  "gpt-4": 8192,
  "gpt-3.5-turbo": 16385,
  "claude-3-opus": 200000,
  "claude-3-sonnet": 200000,
  "claude-3-haiku": 200000,
  "deepseek-chat": 65536,
  "deepseek-coder": 65536,
  "qwen-turbo": 8000,
  "qwen-plus": 32000,
  "qwen-max": 32000,
  "kimi": 200000,
  "moonshot-v1": 128000,
  "glm-4": 128000,
  "glm-3-turbo": 128000,
};

function getModelContextLength(model: string): number {
  const name = model.toLowerCase().trim();
  for (const key of Object.keys(MODEL_CONTEXT_LENGTHS)) {
    if (name.includes(key)) return MODEL_CONTEXT_LENGTHS[key];
  }
  return 4096;
}

const DEFAULT_EMBEDDING_CONFIG: EmbeddingConfig = {
  api_key: "",
  base_url: "https://ark.cn-beijing.volces.com/api/coding/v3",
  model: "doubao-embedding-vision",
};

const AGENT_ROLES = ["planner", "architect", "outliner", "writer", "auditor", "debater", "polisher", "summarizer"] as const;

const AGENT_LABELS: Record<string, string> = {
  planner: "规划师",
  architect: "设定师",
  outliner: "大纲师",
  writer: "写手",
  auditor: "审校员",
  debater: "辩论员",
  polisher: "润色员",
  summarizer: "校验员",
};

const MODEL_OPTIONS = [
  "doubao-seed-2.0-pro",
  "doubao-seed-2.0-lite",
  "doubao-seed-2.0-code",
  "doubao-seed-code",
  "glm-5.2",
  "kimi-k2.7-code",
  "kimi-k2.6",
  "deepseek-v4-pro",
  "deepseek-v4-flash",
  "minimax-m3",
  "minimax-m2.7",
];

function AgentLLMConfigPanel() {
  const { showSuccess, showError } = useToast();
  const [configs, setConfigs] = useState<Record<string, AgentLLMConfig>>({});
  const [loading, setLoading] = useState(true);
  const [expanded, setExpanded] = useState<string | null>(null);
  const [savingRole, setSavingRole] = useState<string | null>(null);
  const [resettingRole, setResettingRole] = useState<string | null>(null);

  const load = useCallback(() => {
    setLoading(true);
    api.listAgentLLMConfigs()
      .then(setConfigs)
      .catch((e: any) => showError("加载 Agent 配置失败：" + e.message))
      .finally(() => setLoading(false));
  }, [showError]);

  useEffect(() => {
    load();
  }, [load]);

  const updateField = (role: string, field: keyof AgentLLMConfig, value: string | number) => {
    setConfigs((prev) => ({
      ...prev,
      [role]: { ...prev[role], [field]: value },
    }));
  };

  const handleSave = async (role: string) => {
    const c = configs[role];
    if (!c) return;
    setSavingRole(role);
    try {
      const r = await api.updateAgentLLMConfig(role, { model: c.model, temperature: c.temperature });
      setConfigs((prev) => ({
        ...prev,
        [role]: {
          ...prev[role],
          enabled: true,
          context_length: r.context_length ?? prev[role].context_length,
        },
      }));
      showSuccess(`${AGENT_LABELS[role]} 配置已保存`);
    } catch (e: any) {
      showError("保存失败：" + e.message);
    } finally {
      setSavingRole(null);
    }
  };

  const handleReset = async (role: string) => {
    setResettingRole(role);
    try {
      await api.resetAgentLLMConfig(role);
      showSuccess(`${AGENT_LABELS[role]} 已重置为默认模型`);
      const fresh = await api.listAgentLLMConfigs();
      setConfigs(fresh);
    } catch (e: any) {
      showError("重置失败：" + e.message);
    } finally {
      setResettingRole(null);
    }
  };

  if (loading) {
    return (
      <div className="flex items-center justify-center py-8">
        <Loader2 className="h-5 w-5 animate-spin text-muted" />
      </div>
    );
  }

  return (
    <div className="space-y-2">
      {AGENT_ROLES.map((role) => {
        const cfg = configs[role];
        const isOpen = expanded === role;
        const busy = savingRole === role || resettingRole === role;
        return (
          <div key={role} className="rounded-xl border border-border-strong bg-surface overflow-hidden">
            <button
              type="button"
              onClick={() => setExpanded(isOpen ? null : role)}
              className="flex w-full items-center justify-between gap-3 px-4 py-3 text-left hover:bg-foreground/5 transition-colors"
            >
              <div className="flex items-center gap-3 min-w-0">
                <ChevronDown className={`h-4 w-4 shrink-0 text-muted transition-transform ${isOpen ? "" : "-rotate-90"}`} />
                <span className="text-sm font-medium text-foreground shrink-0">{AGENT_LABELS[role]}</span>
                <span className="text-xs text-muted truncate">{cfg?.model || "—"}</span>
              </div>
              <Badge variant={cfg?.enabled ? "success" : "default"}>
                {cfg?.enabled ? "已自定义" : "默认"}
              </Badge>
            </button>

            {isOpen && cfg && (
              <div className="px-4 pb-4 pt-1 space-y-3 border-t border-border">
                <div className="space-y-2">
                  <label className="text-sm font-medium text-foreground">模型</label>
                  <Select
                    value={cfg.model}
                    onChange={(e) => updateField(role, "model", e.target.value)}
                  >
                    {!MODEL_OPTIONS.includes(cfg.model) && cfg.model ? (
                      <option value={cfg.model}>{cfg.model}</option>
                    ) : null}
                    {MODEL_OPTIONS.map((m) => (
                      <option key={m} value={m}>{m}</option>
                    ))}
                  </Select>
                </div>

                <div className="space-y-2">
                  <label className="text-sm font-medium text-foreground">Temperature</label>
                  <Input
                    type="number"
                    step={0.1}
                    min={0}
                    max={2}
                    value={cfg.temperature}
                    onChange={(e) => updateField(role, "temperature", parseFloat(e.target.value) || 0)}
                  />
                  {role === "writer" && (
                    <p className="text-xs text-muted">写手会根据章节叙事功能自动调整 temperature，此处为基准值</p>
                  )}
                </div>

                <div className="flex items-center gap-2 pt-1">
                  <Button variant="primary" size="sm" onClick={() => handleSave(role)} disabled={busy}>
                    <Save className="h-3.5 w-3.5 mr-1" />
                    {savingRole === role ? "保存中…" : "保存"}
                  </Button>
                  <Button variant="outline" size="sm" onClick={() => handleReset(role)} disabled={busy || !cfg.enabled}>
                    <RotateCcw className="h-3.5 w-3.5 mr-1" />
                    {resettingRole === role ? "重置中…" : "重置"}
                  </Button>
                </div>
              </div>
            )}
          </div>
        );
      })}
    </div>
  );
}

function EmbeddingConfigPanel() {
  const { showSuccess, showError } = useToast();
  const [config, setConfig] = useState<EmbeddingConfig>(DEFAULT_EMBEDDING_CONFIG);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [testing, setTesting] = useState(false);
  const [testResult, setTestResult] = useState<{ ok: boolean; dimensions?: number; error?: string } | null>(null);

  useEffect(() => {
    setLoading(true);
    api.getEmbeddingConfig()
      .then((c) => setConfig({ ...DEFAULT_EMBEDDING_CONFIG, ...c }))
      .catch((e: any) => showError("加载 Embedding 配置失败：" + e.message))
      .finally(() => setLoading(false));
  }, [showError]);

  const updateField = <K extends keyof EmbeddingConfig>(key: K, value: EmbeddingConfig[K]) => {
    setConfig((prev) => ({ ...prev, [key]: value }));
  };

  const handleSave = async () => {
    setSaving(true);
    try {
      await api.updateEmbeddingConfig(config);
      showSuccess("Embedding 配置已保存");
    } catch (e: any) {
      showError("保存失败：" + e.message);
    } finally {
      setSaving(false);
    }
  };

  const handleTest = async () => {
    setTesting(true);
    setTestResult(null);
    try {
      const r = await api.testEmbeddingConfig();
      setTestResult({ ok: true, dimensions: r.dimensions });
      showSuccess("Embedding 连接测试成功");
    } catch (e: any) {
      setTestResult({ ok: false, error: e.message });
      showError("连接测试失败（请先保存配置）：" + e.message);
    } finally {
      setTesting(false);
    }
  };

  if (loading) {
    return (
      <div className="flex items-center justify-center py-8">
        <Loader2 className="h-5 w-5 animate-spin text-muted" />
      </div>
    );
  }

  return (
    <div className="space-y-4 max-w-2xl">
      <div className="space-y-2">
        <label className="text-sm font-medium">Base URL</label>
        <Input
          placeholder="https://ark.cn-beijing.volces.com/api/coding/v3"
          value={config.base_url}
          onChange={(e) => updateField("base_url", e.target.value)}
        />
        <p className="text-xs text-muted">留空则继承主 LLM 的 Base URL</p>
      </div>

      <div className="space-y-2">
        <label className="text-sm font-medium">API Key</label>
        <Input
          type="password"
          placeholder="ark-..."
          value={config.api_key}
          onChange={(e) => updateField("api_key", e.target.value)}
        />
        <p className="text-xs text-muted">留空则回退到本地中文 embedding 模型（BAAI/bge-small-zh-v1.5）</p>
      </div>

      <div className="space-y-2">
        <label className="text-sm font-medium">模型</label>
        <Input
          placeholder="doubao-embedding-vision"
          value={config.model}
          onChange={(e) => updateField("model", e.target.value)}
        />
      </div>

      <div className="flex flex-wrap items-center gap-3 pt-2">
        <Button variant="primary" onClick={handleSave} disabled={saving}>
          <Save className="h-4 w-4 mr-1" />
          {saving ? "保存中…" : "保存配置"}
        </Button>
        <Button variant="outline" onClick={handleTest} disabled={testing}>
          <TestTube className="h-4 w-4 mr-1" />
          {testing ? "测试中…" : "测试连接"}
        </Button>
      </div>

      {testResult && (
        <div className={`text-sm p-3 rounded-xl border ${testResult.ok ? "border-success/30 bg-success/10 text-success" : "border-danger/30 bg-danger/10 text-danger"}`}>
          {testResult.ok ? (
            <div className="flex items-start gap-2">
              <Check className="h-4 w-4 mt-0.5" />
              <div>
                <div className="font-medium">连接成功</div>
                <div className="text-xs opacity-80 mt-1">向量维度：{testResult.dimensions}</div>
              </div>
            </div>
          ) : (
            <div>
              <div className="font-medium">连接失败</div>
              <div className="text-xs opacity-80 mt-1">{testResult.error}</div>
            </div>
          )}
        </div>
      )}
    </div>
  );
}

export function SettingsView() {
  const { showSuccess, showError } = useToast();
  const [config, setConfig] = useState<LLMConfig>(DEFAULT_CONFIG);
  const [loading, setLoading] = useState(false);
  const [saving, setSaving] = useState(false);
  const [testing, setTesting] = useState(false);
  const [testResult, setTestResult] = useState<{ ok: boolean; response?: string; error?: string } | null>(null);

  useEffect(() => {
    setLoading(true);
    api.getLLMConfig()
      .then((c) => setConfig({ ...DEFAULT_CONFIG, ...c }))
      .catch((e: any) => showError("加载配置失败：" + e.message))
      .finally(() => setLoading(false));
  }, [showError]);

  const updateField = <K extends keyof LLMConfig>(key: K, value: LLMConfig[K]) => {
    setConfig((prev) => {
      const next = { ...prev, [key]: value };
      if (key === "model" && typeof value === "string") {
        next.context_length = getModelContextLength(value);
      }
      return next;
    });
  };

  const handleSave = async () => {
    setSaving(true);
    try {
      const r = await api.updateLLMConfig(config);
      if (r.context_length) {
        setConfig((prev) => ({ ...prev, context_length: r.context_length }));
      }
      showSuccess("LLM 配置已保存");
    } catch (e: any) {
      showError("保存失败：" + e.message);
    } finally {
      setSaving(false);
    }
  };

  const handleTest = async () => {
    setTesting(true);
    setTestResult(null);
    try {
      const r = await api.testLLMConfig();
      setTestResult({ ok: true, response: r.response });
      if (r.context_length) {
        setConfig((prev) => ({ ...prev, context_length: r.context_length }));
      }
      showSuccess("连接测试成功（基于已保存的配置）");
    } catch (e: any) {
      setTestResult({ ok: false, error: e.message });
      showError("连接测试失败（请先保存配置）：" + e.message);
    } finally {
      setTesting(false);
    }
  };

  if (loading) {
    return (
      <Card className="flex-1 flex items-center justify-center">
        <Loader2 className="h-5 w-5 animate-spin text-muted" />
      </Card>
    );
  }

  return (
    <div className="flex-1 overflow-y-auto space-y-4">
    <Card>
      <CardHeader>
        <CardTitle>AI 接口设置</CardTitle>
      </CardHeader>
      <CardContent className="space-y-4 max-w-2xl">
        <div className="space-y-2">
          <label className="text-sm font-medium">Base URL</label>
          <Input
            placeholder="https://api.openai.com/v1"
            value={config.base_url}
            onChange={(e) => updateField("base_url", e.target.value)}
          />
          <p className="text-xs text-muted">OpenAI 兼容接口地址，支持 one-api / ollama / 自定义中转等</p>
        </div>

        <div className="space-y-2">
          <label className="text-sm font-medium">API Key</label>
          <Input
            type="password"
            placeholder="sk-..."
            value={config.api_key}
            onChange={(e) => updateField("api_key", e.target.value)}
          />
        </div>

        <div className="space-y-2">
          <label className="text-sm font-medium">模型</label>
          <Input
            placeholder="gpt-4o-mini"
            value={config.model}
            onChange={(e) => updateField("model", e.target.value)}
          />
          <p className="text-xs text-muted">
            识别到最大上下文：{(config.context_length ?? getModelContextLength(config.model)).toLocaleString()} tokens
          </p>
        </div>

        <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
          <div className="space-y-2">
            <label className="text-sm font-medium">Temperature</label>
            <Input
              type="number"
              step={0.1}
              min={0}
              max={2}
              value={config.temperature}
              onChange={(e) => updateField("temperature", parseFloat(e.target.value) || 0)}
            />
          </div>
          <div className="space-y-2">
            <label className="text-sm font-medium">Max Tokens</label>
            <Input
              type="number"
              min={1}
              value={config.max_tokens}
              onChange={(e) => updateField("max_tokens", parseInt(e.target.value, 10) || 1)}
            />
          </div>
          <div className="space-y-2">
            <label className="text-sm font-medium">Timeout (秒)</label>
            <Input
              type="number"
              min={1}
              value={config.timeout}
              onChange={(e) => updateField("timeout", parseFloat(e.target.value) || 1)}
            />
          </div>
          <div className="space-y-2 flex flex-col justify-end">
            <label className="text-sm font-medium flex items-center gap-2">
              <Switch checked={config.vision_enabled} onCheckedChange={(v) => updateField("vision_enabled", v)} />
              启用视觉
            </label>
          </div>
        </div>

        <div className="flex flex-wrap items-center gap-3 pt-2">
          <Button variant="primary" onClick={handleSave} disabled={saving}>
            <Save className="h-4 w-4 mr-1" />
            {saving ? "保存中…" : "保存配置"}
          </Button>
          <Button variant="outline" onClick={handleTest} disabled={testing}>
            <TestTube className="h-4 w-4 mr-1" />
            {testing ? "测试中…" : "测试连接"}
          </Button>
        </div>

        {testResult && (
          <div className={`text-sm p-3 rounded-xl border ${testResult.ok ? "border-success/30 bg-success/10 text-success" : "border-danger/30 bg-danger/10 text-danger"}`}>
            {testResult.ok ? (
              <div className="flex items-start gap-2">
                <Check className="h-4 w-4 mt-0.5" />
                <div>
                  <div className="font-medium">连接成功</div>
                  <div className="text-xs opacity-80 mt-1">模型回复：{testResult.response}</div>
                </div>
              </div>
            ) : (
              <div>
                <div className="font-medium">连接失败</div>
                <div className="text-xs opacity-80 mt-1">{testResult.error}</div>
              </div>
            )}
          </div>
        )}
      </CardContent>
    </Card>

    <Card>
      <CardHeader>
        <CardTitle>Embedding 配置</CardTitle>
      </CardHeader>
      <CardContent>
        <p className="text-xs text-muted mb-3">配置记忆增强使用的 Embedding 模型；留空则回退到本地模型。</p>
        <EmbeddingConfigPanel />
      </CardContent>
    </Card>

    <Card>
      <CardHeader>
        <CardTitle>多 Agent 模型配置</CardTitle>
      </CardHeader>
      <CardContent className="max-w-2xl">
        <p className="text-xs text-muted mb-3">为不同 Agent 指定独立模型，未自定义时继承主配置（base_url、api_key 共用主配置）。审校（auditor/审校员）模型也可在此面板配置。</p>
        <AgentLLMConfigPanel />
      </CardContent>
    </Card>
    </div>
  );
}
