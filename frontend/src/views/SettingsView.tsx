import { useEffect, useState } from "react";
import { Check, Loader2, Save, TestTube } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Switch } from "@/components/ui/switch";
import { api } from "@/api";
import { useToast } from "@/hooks/useToast";
import type { LLMConfig } from "@/types";

const DEFAULT_CONFIG: LLMConfig = {
  base_url: "https://api.openai.com/v1",
  api_key: "",
  model: "gpt-4o-mini",
  temperature: 0.7,
  max_tokens: 4000,
  timeout: 180,
  vision_enabled: false,
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
      const r = await api.testLLMConfig(config);
      setTestResult({ ok: true, response: r.response });
      if (r.context_length) {
        setConfig((prev) => ({ ...prev, context_length: r.context_length }));
      }
      showSuccess("连接测试成功");
    } catch (e: any) {
      setTestResult({ ok: false, error: e.message });
      showError("连接测试失败：" + e.message);
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
    <Card className="flex-1 overflow-y-auto">
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
  );
}
