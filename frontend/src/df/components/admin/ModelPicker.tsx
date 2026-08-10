/** 模型两级选择器：供应商 -> 模型 点选。
 * 数据源为「模型管理」页（/api/models/providers + /api/models/discover），
 * 与模型管理页展示同一套供应商与模型。
 * discover 是实时网络调用（可能失败/慢），失败时降级为手动输入。
 */
import { useEffect, useState } from "react";
import { Loader2, Pencil, RotateCw } from "lucide-react";
import { DFFormField, DFInput, DFSelect } from "./df-ui";
import { discoverModels, listModelProviders } from "@/df/components/chat/api";
import type { DiscoveredModel, ModelProvider } from "@/df/components/chat/api";

export default function ModelPicker({
  value,
  onChange,
}: {
  value: string;
  onChange: (v: string) => void;
}) {
  const [providers, setProviders] = useState<ModelProvider[]>([]);
  const [provider, setProvider] = useState("");
  const [models, setModels] = useState<DiscoveredModel[]>([]);
  const [loadingModels, setLoadingModels] = useState(false);
  const [manual, setManual] = useState(false);

  useEffect(() => {
    let alive = true;
    listModelProviders()
      .then((list) => {
        if (alive) setProviders(list || []);
      })
      .catch(() => {
        if (alive) setProviders([]);
      });
    return () => {
      alive = false;
    };
  }, []);

  /** 选择供应商 -> 拉取该供应商的模型列表 */
  const handleProviderChange = async (p: string) => {
    setProvider(p);
    setModels([]);
    if (!p) return;
    setLoadingModels(true);
    try {
      const list = await discoverModels(p);
      setModels(list || []);
    } catch {
      setModels([]); // discover 失败：留空，走手动输入兜底
    } finally {
      setLoadingModels(false);
    }
  };

  const inList = models.some((m) => m.id === value);

  return (
    <div className="space-y-2">
      {!manual ? (
        <>
          <div className="grid grid-cols-2 gap-3">
            <DFFormField label="模型供应商" htmlFor="mp-provider">
              <DFSelect
                id="mp-provider"
                value={provider}
                onChange={(e) => void handleProviderChange(e.target.value)}
              >
                <option value="">未指定（手动选择模型）</option>
                {providers.map((p) => (
                  <option key={p.name} value={p.name}>
                    {p.name}
                    {p.is_default ? "（默认）" : ""}
                  </option>
                ))}
              </DFSelect>
            </DFFormField>
            <DFFormField label="供应商模型" htmlFor="mp-model">
              <DFSelect
                id="mp-model"
                value={inList ? value : ""}
                onChange={(e) => onChange(e.target.value)}
                disabled={!provider || loadingModels}
              >
                {loadingModels ? (
                  <option value="">加载模型中...</option>
                ) : (
                  <>
                    <option value="">{provider ? "请选择模型" : "先选择供应商"}</option>
                    {!inList && value && (
                      <option value={value}>{value}（当前值）</option>
                    )}
                    {models.map((m) => (
                      <option key={m.id} value={m.id}>
                        {m.id}
                      </option>
                    ))}
                  </>
                )}
              </DFSelect>
            </DFFormField>
          </div>
          <div className="flex items-center gap-2 text-xs text-muted">
            {loadingModels && (
              <span className="inline-flex items-center gap-1">
                <Loader2 size={12} className="animate-spin motion-reduce:animate-none" aria-hidden="true" />
                正在获取该供应商的模型...
              </span>
            )}
            <button
              type="button"
              onClick={() => setManual(true)}
              className="inline-flex cursor-pointer items-center gap-1 text-foreground/70 hover:text-foreground"
              title="手动输入模型名"
            >
              <Pencil size={11} aria-hidden="true" />
              手动输入
            </button>
            {value && !provider && (
              <span>当前：{value}</span>
            )}
          </div>
        </>
      ) : (
        <div className="flex items-start gap-2">
          <div className="flex-1">
            <DFFormField label="模型名称" htmlFor="mp-manual">
              <DFInput
                id="mp-manual"
                value={value}
                onChange={(e) => onChange(e.target.value)}
                placeholder="如 deepseek-chat"
              />
            </DFFormField>
          </div>
          <button
            type="button"
            onClick={() => setManual(false)}
            className="mt-7 inline-flex cursor-pointer items-center gap-1 text-xs text-foreground/70 hover:text-foreground"
            title="从供应商选择模型"
          >
            <RotateCw size={11} aria-hidden="true" />
            从供应商选择
          </button>
        </div>
      )}
    </div>
  );
}
