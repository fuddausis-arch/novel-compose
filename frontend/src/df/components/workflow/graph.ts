/** 工作流定义 JSON → ReactFlow 图数据（BFS 简单分层布局，无需 dagre） */
import { MarkerType, type Edge, type Node } from "reactflow";
import type { NodeRunStatus, WorkflowDefinition } from "./types";

/** 业务节点画布 data（agent / script） */
export interface FlowNodeData {
  label: string;
  nodeType: string;
  agentType: string;
  status: NodeRunStatus;
  elapsed?: number;
  error?: string;
}

/** 网关节点画布 data */
export interface GatewayNodeData {
  label: string;
  gatewayType: string;
  status: NodeRunStatus;
}

const START_NODE_ID = "__start__";
const END_NODE_ID = "__end__";

const LAYER_X_GAP = 260; // 同层节点水平间距
const LAYER_Y_GAP = 150; // 层间垂直间距

const GATEWAY_LABELS: Record<string, string> = {
  condition: "条件",
  parallel: "并行",
  converge: "汇聚",
  loop: "循环",
};

/**
 * BFS 分层：从 __start__ 出发，节点层级 = 首次到达时的父层级 + 1。
 * 循环网关的回边指向已访问节点会被自动跳过（不会成环死循环）；
 * 未连通节点追加在最后，保证全部可见。
 */
function computeLayers(
  nodeIds: string[],
  edges: { source: string; target: string }[],
): Map<string, number> {
  const adjacency = new Map<string, string[]>();
  for (const e of edges) {
    const list = adjacency.get(e.source) || [];
    list.push(e.target);
    adjacency.set(e.source, list);
  }

  const level = new Map<string, number>();
  const queue: string[] = [];
  const root = nodeIds.includes(START_NODE_ID) ? START_NODE_ID : nodeIds[0];
  if (root) {
    level.set(root, 0);
    queue.push(root);
  }
  while (queue.length > 0) {
    const cur = queue.shift()!;
    const curLevel = level.get(cur) ?? 0;
    for (const next of adjacency.get(cur) || []) {
      if (!level.has(next)) {
        level.set(next, curLevel + 1);
        queue.push(next);
      }
    }
  }
  // 兜底：未从起点连通到的节点依次追加层级
  let maxLevel = level.size > 0 ? Math.max(...level.values()) : 0;
  for (const id of nodeIds) {
    if (!level.has(id)) {
      maxLevel += 1;
      level.set(id, maxLevel);
    }
  }
  return level;
}

/** 将后端工作流定义转换为 ReactFlow nodes/edges（只读画布用） */
export function buildFlowGraph(def: WorkflowDefinition): { nodes: Node[]; edges: Edge[] } {
  const businessNodes = def.nodes || [];
  const gateways = def.gateways || [];
  const edgeDefs = def.edges || [];

  // 画布上的全部节点：起止圆点 + 业务节点 + 网关节点
  const allIds = [
    START_NODE_ID,
    ...businessNodes.map((n) => n.id),
    ...gateways.map((g) => g.id),
    END_NODE_ID,
  ];
  const level = computeLayers(allIds, edgeDefs);

  // 按层分组，同层节点 x 方向居中均分
  const byLevel = new Map<number, string[]>();
  for (const id of allIds) {
    const lv = level.get(id) ?? 0;
    const row = byLevel.get(lv) || [];
    row.push(id);
    byLevel.set(lv, row);
  }
  const positionOf = (id: string): { x: number; y: number } => {
    const lv = level.get(id) ?? 0;
    const row = byLevel.get(lv) || [id];
    const idx = row.indexOf(id);
    return {
      x: (idx - (row.length - 1) / 2) * LAYER_X_GAP,
      y: lv * LAYER_Y_GAP,
    };
  };

  const nodes: Node[] = [
    { id: START_NODE_ID, type: "dfStart", position: positionOf(START_NODE_ID), data: {} },
  ];
  for (const n of businessNodes) {
    nodes.push({
      id: n.id,
      type: "dfNode",
      position: positionOf(n.id),
      data: {
        label: n.label || n.id,
        nodeType: n.node_type || "agent",
        agentType: n.agent_type || "",
        status: "pending",
      } satisfies FlowNodeData,
    });
  }
  for (const g of gateways) {
    nodes.push({
      id: g.id,
      type: "dfGateway",
      position: positionOf(g.id),
      data: {
        label: g.label || GATEWAY_LABELS[g.gateway_type] || g.gateway_type,
        gatewayType: g.gateway_type,
        status: "pending",
      } satisfies GatewayNodeData,
    });
  }
  nodes.push({ id: END_NODE_ID, type: "dfEnd", position: positionOf(END_NODE_ID), data: {} });

  const edges: Edge[] = edgeDefs.map((e) => {
    const cond = e.condition;
    const condLabel = cond ? cond.label || cond.expression || "" : "";
    const isDefault = Boolean(cond?.is_default);
    // 条件边 amber 高亮 + 文本标签；默认分支灰色虚线；普通边 slate
    const stroke = cond ? (isDefault ? "#64748b" : "#f59e0b") : "#475569";
    return {
      id: e.id || `${e.source}->${e.target}`,
      source: e.source,
      target: e.target,
      label: condLabel || undefined,
      labelStyle: condLabel ? { fontSize: 11, fill: isDefault ? "#94a3b8" : "#fbbf24" } : undefined,
      labelBgStyle: condLabel ? { fill: "#0f172a", fillOpacity: 0.85 } : undefined,
      style: { stroke, strokeWidth: 1.5, ...(isDefault ? { strokeDasharray: "5 4" } : {}) },
      markerEnd: { type: MarkerType.ArrowClosed, color: stroke, width: 18, height: 18 },
    };
  });

  return { nodes, edges };
}
