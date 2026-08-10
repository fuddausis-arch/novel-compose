/** Prompt 预览面板：展示拼接后的 system prompt 与 token 估算
 * 对接 GET /api/prompts/{agent_type}/preview。
 */
import { useCallback, useEffect, useState } from "react";
import { Eye, RefreshCw } from "lucide-react";
import { ScrollArea } from "@/components/ui/scroll-area";
import { apiFetch } from "./df-api";
import { DFCard, DFIconButton, DFLoading } from "./df-ui";

interface PreviewData {
  agent_type: string;
  prompt: string;
  estimated_tokens: number;
  section_count: number;
  enabled_count: number;
}

export default function PromptPreviewPanel({ agentType }: { agentType: string }) {
  const [data, setData] = useState<PreviewData | null>(null);
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(
    async (initial = false) => {
      if (initial) setLoading(true);
      else setRefreshing(true);
      setError(null);
      try {
        const res = await apiFetch<PreviewData>(
          `/api/prompts/${encodeURIComponent(agentType)}/preview`,
        );
        setData(res);
      } catch (e) {
        setError(e instanceof Error ? e.message : "加载预览失败");
        setData(null);
      } finally {
        setLoading(false);
        setRefreshing(false);
      }
    },
    [agentType],
  );

  useEffect(() => {
    void load(true);
  }, [load]);

  return (
    <DFCard className="flex min-h-0 flex-col overflow-hidden">
      {/* 头部：标题 + 统计 + 刷新 */}
      <div className="flex items-center justify-between gap-2 border-b border-border px-4 py-3">
        <div className="flex items-center gap-2">
          <Eye size={15} className="text-teal-400" aria-hidden="true" />
          <span className="text-sm font-semibold text-foreground">拼接预览</span>
          {data && (
            <span className="text-xs text-muted tabular-nums">
              约 {data.estimated_tokens.toLocaleString()} tokens · {data.enabled_count}/{data.section_count} 段启用
            </span>
          )}
        </div>
        <DFIconButton
          onClick={() => void load()}
          disabled={refreshing}
          title="刷新预览"
          aria-label="刷新预览"
          className="min-h-[36px] min-w-[36px]"
        >
          <RefreshCw
            size={14}
            className={refreshing ? "animate-spin motion-reduce:animate-none" : ""}
            aria-hidden="true"
          />
        </DFIconButton>
      </div>

      {/* 内容区 */}
      {loading ? (
        <DFLoading text="正在生成预览..." />
      ) : error ? (
        <div className="p-6 text-center text-sm text-red-400" role="alert">
          {error}
        </div>
      ) : data && data.prompt ? (
        <ScrollArea className="h-[520px]">
          <pre
            className="whitespace-pre-wrap p-4 font-mono text-xs leading-relaxed text-foreground"
            role="textbox"
            aria-readonly="true"
            aria-label="拼接后的 system prompt"
            tabIndex={0}
          >
            {data.prompt}
          </pre>
        </ScrollArea>
      ) : (
        <div className="p-6 text-center text-sm text-muted">
          当前 Agent 没有已启用的 Section，预览为空
        </div>
      )}
    </DFCard>
  );
}
