/**
 * DF 融合界面数据访问层。
 * 统一走相对路径 /api，由 Vite 开发代理或同源后端（FastAPI）提供服务。
 * 字段定义与 novel_agent/api 下各路由的返回结构一一对应。
 */

import type { Project } from "@/types";

// ---- 健康检查（GET /api/health） ----

export interface DFHealth {
  /** 整体状态：ok / degraded */
  status: string;
  /** 数据库：ok / error */
  database: string;
  /** LLM 配置：ok / error */
  llm: string;
  /** 磁盘信息（可能含 error 字段） */
  disk: { free_gb?: number; total_gb?: number; error?: string };
  /** 后端运行时长（秒） */
  uptime: number;
}

// ---- Token 账本（GET /api/telemetry/tokens） ----

export interface TokenBucket {
  total_tokens: number;
  input_tokens: number;
  output_tokens: number;
  reasoning_tokens: number;
  total_cost: number;
  call_count: number;
}

export interface TokenRecord {
  node_name: string;
  attempt: number;
  model: string;
  input_tokens: number;
  output_tokens: number;
  reasoning_tokens: number;
  cost: number;
  /** UTC ISO 时间串 */
  timestamp: string;
}

export interface TokenStats {
  total: TokenBucket;
  by_node: Record<string, TokenBucket>;
  by_model: Record<string, TokenBucket>;
  records: TokenRecord[];
}

// ---- 章节列表（GET /api/chapters/list?project_id=N） ----

export interface DFChapterItem {
  chapter: number;
  title: string;
  text_preview?: string;
}

// ---- 工作流定义（GET /api/workflows 与 /api/workflows/{id}） ----

export interface WorkflowVariable {
  key: string;
  name: string;
  type: string;
  required: boolean;
}

export interface WorkflowSummary {
  workflow_id: string;
  name: string;
  version: number;
  node_count: number;
  variables: WorkflowVariable[];
}

export interface WorkflowNodeDef {
  id: string;
  label: string;
  /** agent / script */
  node_type: string;
  agent_type: string;
  position?: { x: number; y: number };
  first_message?: string;
  output_variable?: string;
  save_output_to_file?: boolean;
  output_file_path?: string;
  node_params?: Record<string, unknown>;
  fail_auto_skip?: boolean;
}

export interface WorkflowEdgeDef {
  source: string;
  target: string;
  condition?: { expression?: string; is_default?: boolean };
}

export interface WorkflowGatewayDef {
  id: string;
  /** parallel / converge / condition / loop */
  gateway_type: string;
  label?: string;
  position?: { x: number; y: number };
  converge_gateway_id?: string | null;
}

export interface WorkflowDefinition {
  workflow_id: string;
  name: string;
  version: number;
  nodes: WorkflowNodeDef[];
  edges: WorkflowEdgeDef[];
  gateways: WorkflowGatewayDef[];
  start_position?: { x: number; y: number };
  end_position?: { x: number; y: number };
  variables?: WorkflowVariable[];
}

// ---- 请求封装 ----

async function fetchJSON<T>(path: string): Promise<T> {
  const resp = await fetch(path);
  if (!resp.ok) {
    throw new Error(`请求失败（HTTP ${resp.status}）`);
  }
  return (await resp.json()) as T;
}

/** DF 页面使用的后端端点集合 */
export const dfApi = {
  health: () => fetchJSON<DFHealth>("/api/health"),
  tokenStats: () => fetchJSON<TokenStats>("/api/telemetry/tokens"),
  listProjects: () => fetchJSON<Project[]>("/api/projects"),
  listChapters: (projectId: number) =>
    fetchJSON<DFChapterItem[]>(`/api/chapters/list?project_id=${projectId}`),
  listWorkflows: () => fetchJSON<{ workflows: WorkflowSummary[] }>("/api/workflows"),
  getWorkflow: (workflowId: string) =>
    fetchJSON<WorkflowDefinition>(`/api/workflows/${encodeURIComponent(workflowId)}`),
};
