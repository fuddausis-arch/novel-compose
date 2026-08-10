/** 用户注入配置面板：全局注入 / 按项目注入 / 注入位置
 * 对接 GET/PUT /api/user-injection。
 */
import { useCallback, useEffect, useState } from "react";
import { Plus, Save, Trash2, UserRound } from "lucide-react";
import { apiFetch, apiJson } from "./df-api";
import {
  DFCard,
  DFErrorToast,
  DFFormField,
  DFIconButton,
  DFInput,
  DFLoading,
  DFPrimaryButton,
  DFSelect,
  DFTextarea,
} from "./df-ui";
import { useToast } from "@/hooks/useToast";

/** 用户注入配置（与后端 _DEFAULT_CONFIG 对齐） */
interface InjectionConfig {
  global_prompt: string;
  project_prompts: Record<string, string>;
  inject_position: string;
}

/** 项目注入条目（编辑态用数组表示，保存时转回 dict） */
interface ProjectEntry {
  key: string;
  value: string;
}

export default function UserInjectionPanel() {
  const { showSuccess } = useToast();
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const [globalPrompt, setGlobalPrompt] = useState("");
  const [injectPosition, setInjectPosition] = useState("system");
  const [entries, setEntries] = useState<ProjectEntry[]>([]);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const data = await apiFetch<InjectionConfig>("/api/user-injection");
      setGlobalPrompt(data.global_prompt || "");
      setInjectPosition(data.inject_position || "system");
      setEntries(
        Object.entries(data.project_prompts || {}).map(([key, value]) => ({ key, value })),
      );
    } catch (e) {
      setError(e instanceof Error ? e.message : "加载用户注入配置失败");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  const handleSave = async () => {
    // 校验项目 key 非空且不重复
    const keys = entries.map((e) => e.key.trim());
    if (keys.some((k) => !k)) {
      setError("项目注入存在空的项目标识，请填写或删除");
      return;
    }
    if (new Set(keys).size !== keys.length) {
      setError("项目注入存在重复的项目标识");
      return;
    }
    setSaving(true);
    try {
      const projectPrompts: Record<string, string> = {};
      for (const e of entries) projectPrompts[e.key.trim()] = e.value;
      await apiJson("/api/user-injection", "PUT", {
        global_prompt: globalPrompt,
        inject_position: injectPosition,
        project_prompts: projectPrompts,
      });
      showSuccess("用户注入配置已保存");
    } catch (e) {
      setError(e instanceof Error ? e.message : "保存失败");
    } finally {
      setSaving(false);
    }
  };

  if (loading) return <DFLoading text="正在加载用户注入配置..." />;

  return (
    <div className="space-y-4">
      <DFCard className="space-y-4 p-4">
        <div className="flex items-center gap-2">
          <UserRound size={15} className="text-indigo-400" aria-hidden="true" />
          <h3 className="text-sm font-semibold text-foreground">全局注入</h3>
        </div>
        <DFFormField label="注入位置" htmlFor="inject-position" hint="system：拼接到 system prompt；user：注入为单独的用户消息">
          <DFSelect
            id="inject-position"
            className="w-64"
            value={injectPosition}
            onChange={(e) => setInjectPosition(e.target.value)}
          >
            <option value="system">system（注入系统提示词）</option>
            <option value="user">user（注入用户消息）</option>
          </DFSelect>
        </DFFormField>
        <DFFormField label="全局注入内容（对所有会话生效）" htmlFor="global-prompt">
          <DFTextarea
            id="global-prompt"
            rows={6}
            value={globalPrompt}
            onChange={(e) => setGlobalPrompt(e.target.value)}
            placeholder="每次会话启动时注入的自定义内容，如写作偏好、禁忌等"
          />
        </DFFormField>
      </DFCard>

      <DFCard className="space-y-3 p-4">
        <div className="flex items-center justify-between">
          <h3 className="text-sm font-semibold text-foreground">按项目注入</h3>
          <DFPrimaryButton
            onClick={() => setEntries((prev) => [...prev, { key: "", value: "" }])}
          >
            <Plus size={12} aria-hidden="true" />
            添加项目
          </DFPrimaryButton>
        </div>
        {entries.length === 0 ? (
          <p className="py-4 text-center text-xs text-muted">
            暂无项目级注入配置，添加后仅对指定项目生效
          </p>
        ) : (
          <div className="space-y-3" role="list" aria-label="项目注入列表">
            {entries.map((entry, index) => (
              <div key={index} role="listitem" className="rounded-lg border border-border bg-surface p-3">
                <div className="mb-2 flex items-center gap-2">
                  <DFInput
                    value={entry.key}
                    onChange={(e) =>
                      setEntries((prev) =>
                        prev.map((it, i) => (i === index ? { ...it, key: e.target.value } : it)),
                      )
                    }
                    placeholder="项目标识（项目 ID 或名称）"
                    aria-label={`项目 ${index + 1} 标识`}
                    className="h-8 w-64 font-mono text-xs"
                  />
                  <DFIconButton
                    onClick={() => setEntries((prev) => prev.filter((_, i) => i !== index))}
                    title="移除该项目"
                    aria-label={`移除项目 ${entry.key || index + 1}`}
                    className="min-h-[36px] min-w-[36px] hover:text-red-400"
                  >
                    <Trash2 size={14} aria-hidden="true" />
                  </DFIconButton>
                </div>
                <DFTextarea
                  rows={3}
                  value={entry.value}
                  onChange={(e) =>
                    setEntries((prev) =>
                      prev.map((it, i) => (i === index ? { ...it, value: e.target.value } : it)),
                    )
                  }
                  placeholder="该项目会话启动时注入的内容"
                  aria-label={`项目 ${entry.key || index + 1} 注入内容`}
                  className="text-xs"
                />
              </div>
            ))}
          </div>
        )}
      </DFCard>

      <div className="flex justify-end">
        <DFPrimaryButton onClick={() => void handleSave()} disabled={saving}>
          <Save size={12} aria-hidden="true" />
          {saving ? "保存中..." : "保存配置"}
        </DFPrimaryButton>
      </div>

      <DFErrorToast message={error} onClose={() => setError(null)} />
    </div>
  );
}
