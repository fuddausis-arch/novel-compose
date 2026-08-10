/** Agent 类型选项 hook：合并后端 agents.json 与内置默认列表 */
import { useEffect, useState } from "react";
import { apiFetch } from "./df-api";

/** sections.json 内置的默认 agent 类型（与后端 PromptManager 默认配置对齐） */
export const DEFAULT_AGENT_TYPES = [
  "writer",
  "auditor",
  "world_engine",
  "context_trimmer",
  "post_hoc_observer",
  "post_hoc_arbiter",
];

/** 拉取 /api/agents 的 agent_type 列表，与默认列表合并去重 */
export function useAgentTypes(): string[] {
  const [types, setTypes] = useState<string[]>(DEFAULT_AGENT_TYPES);
  useEffect(() => {
    let cancelled = false;
    apiFetch<{ agents: Record<string, unknown> }>("/api/agents")
      .then((data) => {
        if (cancelled) return;
        const keys = Object.keys(data.agents || {});
        if (keys.length === 0) return;
        setTypes((prev) => Array.from(new Set([...keys, ...prev])).sort());
      })
      .catch(() => {
        /* 获取失败时沿用默认列表 */
      });
    return () => {
      cancelled = true;
    };
  }, []);
  return types;
}
