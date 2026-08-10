/**
 * 模型选择器胶囊
 *
 * 数据来源：
 * - 当前模型：GET /api/config/llm（对话 agent 使用全局 LLM 配置）
 * - 可选模型：/api/models/providers + /api/models/discover（按供应商发现）
 *   以及 /api/models/presets（内置预设）
 * 切换：PUT /api/config/llm { model, base_url }（全局生效）
 */
import { useCallback, useEffect, useRef, useState } from "react";
import { useNavigate } from "react-router-dom";
import { Check, ChevronDown, Loader2, Settings } from "lucide-react";
import {
  discoverModels, getModelPresets, listModelProviders, updateLLMConfig,
  type LLMConfigInfo,
} from "./api";

interface Props {
  config: LLMConfigInfo | null;
  disabled?: boolean;
  onSwitched: (config: LLMConfigInfo) => void;
  onError: (message: string) => void;
}

/** 一个可选项：展示名 + 切换时要写入的 model/base_url */
interface ModelOption {
  key: string;
  model: string;
  baseUrl: string;
  group: string;
  contextLength?: number;
}

function SelectionRow({ label, value, active, onClick }: {
  label: string; value?: string; active: boolean; onClick: () => void;
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      className={`flex min-h-9 w-full items-center gap-2 rounded-lg px-2.5 text-left text-sm transition-colors cursor-pointer ${
        active
          ? "bg-indigo-500/15 text-indigo-100"
          : "text-foreground hover:bg-secondary/70 hover:text-foreground"
      }`}
    >
      <span className="min-w-0 flex-1 truncate">{label}</span>
      {value ? <span className="max-w-24 truncate text-[11px] text-muted">{value}</span> : null}
      {active ? <Check size={14} className="shrink-0 text-indigo-400" aria-hidden="true" /> : null}
    </button>
  );
}

export default function ModelSwitcher({ config, disabled = false, onSwitched, onError }: Props) {
  const rootRef = useRef<HTMLDivElement>(null);
  const navigate = useNavigate();
  const [open, setOpen] = useState(false);
  const [loading, setLoading] = useState(false);
  const [updating, setUpdating] = useState(false);
  const [options, setOptions] = useState<ModelOption[]>([]);
  const [loadError, setLoadError] = useState<string | null>(null);
  const loadedRef = useRef(false);

  // 打开时加载供应商/预设并发现模型（每个供应商独立容错）
  const loadOptions = useCallback(async () => {
    setLoading(true);
    setLoadError(null);
    try {
      const [providers, presets] = await Promise.all([
        listModelProviders().catch(() => []),
        getModelPresets().catch(() => ({})),
      ]);
      const discovered = await Promise.all(
        providers.map(async (p) => {
          try {
            const models = await discoverModels(p.name);
            return models.map<ModelOption>((m) => ({
              key: `${p.name}:${m.id}`,
              model: m.id,
              baseUrl: p.base_url,
              group: p.name,
              contextLength: m.context_length,
            }));
          } catch {
            return [] as ModelOption[]; // 单个供应商发现失败不影响其他
          }
        })
      );
      const presetOptions = Object.entries(presets).map<ModelOption>(([model, preset]) => ({
        key: `preset:${model}`,
        model,
        baseUrl: preset.base_url,
        group: "内置预设",
        contextLength: preset.context_length,
      }));
      // 去重（同一 model+baseUrl 只保留一个）
      const seen = new Set<string>();
      const merged = [...discovered.flat(), ...presetOptions].filter((o) => {
        const k = `${o.model}|${o.baseUrl}`;
        if (seen.has(k)) return false;
        seen.add(k);
        return true;
      });
      setOptions(merged);
      loadedRef.current = true;
    } catch {
      setLoadError("模型列表加载失败");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    if (!open) return;
    if (!loadedRef.current) void loadOptions();
    const closeOnOutside = (event: MouseEvent) => {
      if (!rootRef.current?.contains(event.target as Node)) setOpen(false);
    };
    const closeOnEscape = (event: KeyboardEvent) => {
      if (event.key === "Escape") setOpen(false);
    };
    document.addEventListener("mousedown", closeOnOutside);
    document.addEventListener("keydown", closeOnEscape);
    return () => {
      document.removeEventListener("mousedown", closeOnOutside);
      document.removeEventListener("keydown", closeOnEscape);
    };
  }, [open, loadOptions]);

  const currentModel = config?.model || "";
  const currentBaseUrl = config?.base_url || "";

  const handleSelect = async (option: ModelOption) => {
    if (updating || (option.model === currentModel && option.baseUrl === currentBaseUrl)) return;
    setUpdating(true);
    try {
      await updateLLMConfig({ model: option.model, base_url: option.baseUrl });
      // 本地回显新配置（config 为 null 时用空配置兜底，仅作展示）
      const base: LLMConfigInfo = config ?? {
        base_url: "", api_key: "", model: "", temperature: 0, max_tokens: 0,
        timeout: 0, vision_enabled: false, top_p: 0, frequency_penalty: 0, presence_penalty: 0,
      };
      onSwitched({
        ...base,
        model: option.model,
        base_url: option.baseUrl,
        context_length: option.contextLength ?? config?.context_length,
      });
      setOpen(false);
    } catch (e) {
      onError(e instanceof Error ? e.message : "模型切换失败");
    } finally {
      setUpdating(false);
    }
  };

  // 按分组聚合
  const groups = options.reduce<Record<string, ModelOption[]>>((acc, o) => {
    (acc[o.group] ||= []).push(o);
    return acc;
  }, {});

  return (
    <div ref={rootRef} className="relative shrink-0">
      {open && (
        <div className="absolute bottom-[calc(100%+0.65rem)] right-0 z-40 w-72 max-w-[calc(100vw-2rem)] overflow-hidden rounded-xl border border-border-strong/80 bg-surface-elevated p-1.5 shadow-2xl shadow-black/30">
          <div className="max-h-72 overflow-y-auto">
            {loading ? (
              <div className="flex min-h-20 items-center justify-center gap-2 text-sm text-muted" role="status">
                <Loader2 size={15} className="animate-spin motion-reduce:animate-none" aria-hidden="true" />
                加载模型中
              </div>
            ) : options.length === 0 ? (
              <div className="p-2">
                <p className="text-sm font-medium text-foreground">{loadError || "未发现可用模型"}</p>
                <p className="mt-1 text-xs text-muted">请先在模型设置中配置供应商</p>
              </div>
            ) : (
              Object.entries(groups).map(([group, items]) => (
                <div key={group} className="mb-1 last:mb-0">
                  <div className="px-2.5 py-1 text-[11px] font-medium text-muted">{group}</div>
                  {items.map((o) => (
                    <SelectionRow
                      key={o.key}
                      label={o.model}
                      value={o.contextLength ? `${Math.round(o.contextLength / 1024)}K` : undefined}
                      active={o.model === currentModel && o.baseUrl === currentBaseUrl}
                      onClick={() => void handleSelect(o)}
                    />
                  ))}
                </div>
              ))
            )}
          </div>
          <div className="mt-1 border-t border-border-strong pt-1">
            <button
              type="button"
              onClick={() => { setOpen(false); navigate("/settings/models"); }}
              className="flex min-h-9 w-full items-center gap-2 rounded-lg px-2.5 text-xs font-medium text-indigo-300 hover:bg-indigo-500/10 cursor-pointer"
            >
              <Settings size={14} aria-hidden="true" />
              前往模型设置
            </button>
          </div>
          {updating && (
            <div className="border-t border-border-strong px-2.5 pt-2 text-xs text-muted">正在切换模型...</div>
          )}
        </div>
      )}

      <button
        type="button"
        onClick={() => setOpen((v) => !v)}
        disabled={disabled || updating}
        aria-haspopup="menu"
        aria-expanded={open}
        aria-busy={loading || updating}
        aria-label="切换模型（全局生效）"
        title="切换模型（对全局对话配置生效）"
        className="flex h-9 max-w-52 items-center gap-2 rounded-full bg-secondary/75 px-3 text-xs text-foreground transition-colors hover:bg-secondary hover:text-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-indigo-500/40 disabled:cursor-not-allowed disabled:opacity-45 cursor-pointer"
      >
        {updating ? (
          <Loader2 size={13} className="shrink-0 animate-spin motion-reduce:animate-none" aria-hidden="true" />
        ) : null}
        <span className="truncate">{currentModel || "未配置模型"}</span>
        <ChevronDown size={13} className="shrink-0 text-muted" aria-hidden="true" />
      </button>
    </div>
  );
}
