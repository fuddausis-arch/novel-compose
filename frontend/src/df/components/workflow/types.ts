/** DeterminFlow 融合界面 · 工作流页共享类型（字段与后端 routes_workflows.py 对齐） */

/** GET /api/workflows 列表项中的变量摘要 */
export interface WorkflowVariableBrief {
  key: string;
  name: string;
  type: string;
  required: boolean;
}

/** GET /api/workflows 列表项 */
export interface WorkflowSummary {
  workflow_id: string;
  name: string;
  version: number;
  node_count: number;
  variables: WorkflowVariableBrief[];
  /** true=项目内自定义工作流，可编辑/删除；false/undefined=内置 */
  is_custom?: boolean;
}

/** 工作流定义中的业务节点（后端只读定义，实际字段多于此处列出的） */
export interface WorkflowNodeDef {
  id: string;
  label: string;
  node_type: string; // agent / script
  agent_type?: string;
  position?: { x: number; y: number };
}

/** 边条件（条件/循环网关出边上携带） */
export interface WorkflowEdgeCondition {
  expression?: string;
  label?: string;
  is_default?: boolean;
}

/** 工作流定义中的边 */
export interface WorkflowEdgeDef {
  id: string;
  source: string;
  target: string;
  condition?: WorkflowEdgeCondition;
}

/** 网关节点定义 */
export interface WorkflowGatewayDef {
  id: string;
  gateway_type: string; // condition / parallel / converge / loop
  label?: string;
  position?: { x: number; y: number };
}

/** 工作流变量（右侧表单渲染依据） */
export interface WorkflowVariableDef {
  key: string;
  name: string;
  type: string; // text / textarea / file / list ...
  default?: string;
  required?: boolean;
  description?: string;
  hidden?: boolean; // 内部变量（hidden=true）不在表单中展示
  source_type?: string; // input / output（output 为节点产出，不需用户填写）
}

/** GET /api/workflows/{id} 完整定义 */
export interface WorkflowDefinition {
  workflow_id: string;
  name: string;
  version: number;
  nodes: WorkflowNodeDef[];
  edges: WorkflowEdgeDef[];
  gateways?: WorkflowGatewayDef[];
  variables?: WorkflowVariableDef[];
}

/** 节点运行状态：pending 待执行 / running 执行中 / ok 完成 / failed 失败 */
export type NodeRunStatus = "pending" | "running" | "ok" | "failed";

/** 单个节点的实时运行信息（由 SSE 事件驱动） */
export interface NodeRunInfo {
  status: NodeRunStatus;
  elapsed?: number;
  error?: string;
}

/** 执行日志条目 */
export interface WorkflowLogEntry {
  id: number;
  time: string;
  kind: "start" | "done" | "failed" | "info" | "error";
  text: string;
}

/** workflow_done 事件中的节点历史记录（与后端 WorkflowRunner._record 对齐） */
export interface NodeRunRecord {
  node_id: string;
  status: string; // ok / failed
  elapsed_s: number;
  error: string;
  output_preview: string;
  ts: number;
}

// ===== 自定义工作流编辑器相关类型 =====

/** 编辑器画布节点 data：兼容只读画布的 FlowNodeData 字段，并扩展编辑器独有字段 */
export interface EditorNodeData {
  label: string;
  nodeType: "agent" | "script" | "start" | "end";
  agentType: string;
  status: NodeRunStatus; // 编辑器中固定为 pending
  // 编辑器独有字段
  firstMessage?: string;
  outputVariable?: string;
  failAutoSkip?: boolean;
  nodeParams?: Record<string, string>;
}

/** 自定义工作流 workflow_json.nodes 元素（与后端 POST/PUT body 对齐） */
export interface CustomWorkflowNode {
  id: string;
  node_type: "agent" | "script";
  agent_type?: string;
  first_message?: string;
  label?: string;
  output_variable?: string;
  fail_auto_skip?: boolean;
  node_params?: Record<string, string>;
  position?: { x: number; y: number };
}

/** 自定义工作流 workflow_json.edges 元素 */
export interface CustomWorkflowEdge {
  source: string;
  target: string;
}

/** 自定义工作流 workflow_json 顶层结构（POST/PUT body 的 workflow_json 字段） */
export interface WorkflowJson {
  name: string;
  description?: string;
  nodes: CustomWorkflowNode[];
  edges: CustomWorkflowEdge[];
  variables: WorkflowVariableDef[];
}

/** GET /api/bible/{project_id}/custom-workflows 单条记录 */
export interface CustomWorkflowRecord {
  id: number;
  project_id: number;
  workflow_id: string;
  name: string;
  description: string;
  workflow_json: WorkflowJson;
  created_at: string;
  updated_at: string;
}

/** POST /api/bible/{project_id}/custom-workflows 请求体 */
export interface CreateCustomWorkflowRequest {
  workflow_id: string;
  name: string;
  description?: string;
  workflow_json: WorkflowJson;
}

/** PUT /api/bible/{project_id}/custom-workflows/{workflow_id} 请求体 */
export interface UpdateCustomWorkflowRequest {
  name?: string;
  description?: string;
  workflow_json?: WorkflowJson;
}
