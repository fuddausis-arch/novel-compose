/** 工作流只读画布：definition → ReactFlow，执行时按 SSE 状态实时高亮节点 */
import { useMemo } from "react";
import ReactFlow, {
  Background,
  BackgroundVariant,
  Controls,
  type NodeTypes,
} from "reactflow";
import "reactflow/dist/style.css";
import { buildFlowGraph } from "./graph";
import { DFBusinessNode, DFEndNode, DFGatewayNode, DFStartNode } from "./canvasNodes";
import type { NodeRunInfo, WorkflowDefinition } from "./types";

// nodeTypes 必须定义在组件外，避免每次渲染重建导致 ReactFlow 警告
const nodeTypes: NodeTypes = {
  dfNode: DFBusinessNode,
  dfGateway: DFGatewayNode,
  dfStart: DFStartNode,
  dfEnd: DFEndNode,
};

interface WorkflowCanvasProps {
  definition: WorkflowDefinition;
  /** 节点运行状态表（SSE 事件驱动，key 为节点 id） */
  nodeStatuses: Record<string, NodeRunInfo>;
}

export default function WorkflowCanvas({ definition, nodeStatuses }: WorkflowCanvasProps) {
  // 定义变化时重建图结构（BFS 分层布局）
  const graph = useMemo(() => buildFlowGraph(definition), [definition]);

  // 将运行状态叠加到节点 data（不改图结构，仅更新状态字段）
  const nodes = useMemo(
    () =>
      graph.nodes.map((n) => {
        const info = nodeStatuses[n.id];
        if (!info) return n;
        return {
          ...n,
          data: { ...n.data, status: info.status, elapsed: info.elapsed, error: info.error },
        };
      }),
    [graph.nodes, nodeStatuses],
  );

  // 有节点运行时全部边启用流动动画
  const hasRunning = Object.values(nodeStatuses).some((s) => s.status === "running");
  const edges = useMemo(
    () => graph.edges.map((e) => ({ ...e, animated: hasRunning })),
    [graph.edges, hasRunning],
  );

  return (
    <ReactFlow
      nodes={nodes}
      edges={edges}
      nodeTypes={nodeTypes}
      fitView
      fitViewOptions={{ padding: 0.2, maxZoom: 1 }}
      nodesDraggable={false}
      nodesConnectable={false}
      elementsSelectable={false}
      zoomOnScroll
      panOnDrag
      className="bg-background"
      aria-label="工作流只读画布"
    >
      <Background variant={BackgroundVariant.Dots} gap={18} size={1} color="var(--border-strong)" />
      <Controls
        showInteractive={false}
        className="!border-border !bg-surface-elevated [&_button]:!border-border [&_button]:!bg-surface-elevated [&_button]:!fill-muted"
      />
    </ReactFlow>
  );
}
