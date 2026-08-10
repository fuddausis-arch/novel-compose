/** 自定义工作流编辑器：可编辑 ReactFlow 画布 + 节点工具箱 + 节点编辑表单 + 变量编辑器
 *
 * 由 DFWorkflowPage 在「编辑模式」下渲染（替代 WorkflowCanvas + WorkflowRunPanel）。
 * 内部用 ReactFlowProvider 包裹，子组件通过 useReactFlow().screenToFlowPosition
 * 将工具箱拖拽的屏幕坐标转换为画布坐标，落地为新节点。
 */
import { useCallback, useEffect, useMemo, useState } from "react";
import ReactFlow, {
  Background,
  BackgroundVariant,
  Controls,
  MarkerType,
  ReactFlowProvider,
  addEdge,
  applyEdgeChanges,
  applyNodeChanges,
  useReactFlow,
  type Connection,
  type Edge,
  type EdgeChange,
  type Node,
  type NodeChange,
  type NodeTypes,
} from "reactflow";
import "reactflow/dist/style.css";
import {
  Bot,
  FileCode,
  Plus,
  Save,
  Settings2,
  Trash2,
  X,
  Loader2,
  CircleDot,
  PlayCircle,
  Square as SquareIcon,
} from "lucide-react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Textarea } from "@/components/ui/textarea";
import { Separator } from "@/components/ui/separator";
import { ScrollArea } from "@/components/ui/scroll-area";
import { Badge } from "@/components/ui/badge";
import { Switch } from "@/components/ui/switch";
import { useMediaQuery } from "@/hooks/useMediaQuery";
import { DFBusinessNode, DFEndNode, DFStartNode } from "./canvasNodes";
import { buildFlowGraph } from "./graph";
import type {
  CustomWorkflowEdge,
  CustomWorkflowNode,
  EditorNodeData,
  WorkflowJson,
  WorkflowVariableDef,
} from "./types";

const START_NODE_ID = "__start__";
const END_NODE_ID = "__end__";

// nodeTypes 必须定义在组件外，避免每次渲染重建导致 ReactFlow 警告
const nodeTypes: NodeTypes = {
  dfNode: DFBusinessNode,
  dfStart: DFStartNode,
  dfEnd: DFEndNode,
};

/** agent_type 可选值（对齐后端 config.ROLE_PARAMS 的角色光谱） */
const AGENT_TYPES = [
  "writer",
  "planner",
  "outliner",
  "architect",
  "polisher",
  "auditor",
  "world_engine",
  "summarizer",
  "debater",
  "context_trimmer",
  "post_hoc",
];

/** 变量类型可选项 */
const VARIABLE_TYPES = ["text", "textarea", "file", "list"];

/** 编辑器中新建节点的默认画布坐标（拖拽时由 screenToFlowPosition 覆盖） */
const DEFAULT_NEW_NODE_POSITION = { x: 80, y: 80 };

/** 普通边的默认样式（编辑器中所有用户连接的边一致） */
function makeDefaultEdge(id: string, source: string, target: string): Edge {
  return {
    id,
    source,
    target,
    style: { stroke: "#475569", strokeWidth: 1.5 },
    markerEnd: { type: MarkerType.ArrowClosed, color: "#475569", width: 18, height: 18 },
  };
}

/** WorkflowJson → ReactFlow nodes/edges（保留 workflow_json 中的节点位置；缺失时回退到 BFS 布局） */
function workflowJsonToFlow(json: WorkflowJson): { nodes: Node<EditorNodeData>[]; edges: Edge[] } {
  // 用 buildFlowGraph 计算 BFS 分层布局作为位置兜底（仅当节点没有自带 position 时使用）
  const fallbackGraph = buildFlowGraph({
    workflow_id: "",
    name: json.name,
    version: 1,
    nodes: json.nodes.map((n) => ({
      id: n.id,
      label: n.label || n.id,
      node_type: n.node_type,
      agent_type: n.agent_type,
    })),
    edges: json.edges.map((e) => ({ id: `${e.source}->${e.target}`, source: e.source, target: e.target })),
  });
  const fallbackPos = new Map(fallbackGraph.nodes.map((n) => [n.id, n.position]));

  const nodes: Node<EditorNodeData>[] = [
    {
      id: START_NODE_ID,
      type: "dfStart",
      position: fallbackPos.get(START_NODE_ID) ?? { x: 0, y: 0 },
      data: { label: "开始", nodeType: "start", agentType: "", status: "pending" },
      draggable: false,
      deletable: false,
      connectable: true,
    },
  ];

  for (const n of json.nodes || []) {
    nodes.push({
      id: n.id,
      type: "dfNode",
      position: n.position ?? fallbackPos.get(n.id) ?? DEFAULT_NEW_NODE_POSITION,
      data: {
        label: n.label || n.id,
        nodeType: n.node_type as "agent" | "script",
        agentType: n.agent_type || "",
        status: "pending",
        firstMessage: n.first_message,
        outputVariable: n.output_variable,
        failAutoSkip: n.fail_auto_skip,
        nodeParams: n.node_params,
      },
    });
  }

  nodes.push({
    id: END_NODE_ID,
    type: "dfEnd",
    position: fallbackPos.get(END_NODE_ID) ?? { x: 0, y: 400 },
    data: { label: "结束", nodeType: "end", agentType: "", status: "pending" },
    draggable: false,
    deletable: false,
    connectable: true,
  });

  const edges: Edge[] = (json.edges || []).map((e, i) =>
    makeDefaultEdge(`e${i}-${e.source}-${e.target}`, e.source, e.target),
  );

  return { nodes, edges };
}

/** ReactFlow nodes/edges → WorkflowJson（保存时序列化为后端期望的结构） */
function flowToWorkflowJson(
  nodes: Node<EditorNodeData>[],
  edges: Edge[],
  variables: WorkflowVariableDef[],
  name: string,
  description: string,
): WorkflowJson {
  const wfNodes: CustomWorkflowNode[] = [];
  for (const n of nodes) {
    // 起止节点不在 workflow_json.nodes 中（隐式由 edges 的 __start__/__end__ 引用）
    if (n.id === START_NODE_ID || n.id === END_NODE_ID) continue;
    const d = n.data;
    const isScript = d.nodeType === "script";
    const node: CustomWorkflowNode = {
      id: n.id,
      node_type: d.nodeType === "script" ? "script" : "agent",
      label: d.label,
      position: n.position,
    };
    if (!isScript) {
      node.agent_type = d.agentType || "writer";
      if (d.firstMessage) node.first_message = d.firstMessage;
    } else {
      node.node_params = d.nodeParams || {};
    }
    if (d.outputVariable) node.output_variable = d.outputVariable;
    if (d.failAutoSkip) node.fail_auto_skip = true;
    wfNodes.push(node);
  }

  const wfEdges: CustomWorkflowEdge[] = edges.map((e) => ({
    source: e.source,
    target: e.target,
  }));

  return {
    name,
    description: description || undefined,
    nodes: wfNodes,
    edges: wfEdges,
    variables,
  };
}

interface WorkflowEditorProps {
  workflowId: string;
  initialJson: WorkflowJson;
  saving: boolean;
  onSave: (json: WorkflowJson) => void;
  onCancel: () => void;
}

function WorkflowEditorInner({
  workflowId,
  initialJson,
  saving,
  onSave,
  onCancel,
}: WorkflowEditorProps) {
  const { screenToFlowPosition } = useReactFlow<EditorNodeData>();

  // initialJson → ReactFlow nodes/edges（只在 initialJson 变化时重算）
  const initial = useMemo(() => workflowJsonToFlow(initialJson), [initialJson]);

  const [nodes, setNodes] = useState<Node<EditorNodeData>[]>(initial.nodes);
  const [edges, setEdges] = useState<Edge[]>(initial.edges);
  const [variables, setVariables] = useState<WorkflowVariableDef[]>(initialJson.variables || []);
  const [name, setName] = useState(initialJson.name);
  const [description, setDescription] = useState(initialJson.description || "");
  const [selectedNodeId, setSelectedNodeId] = useState<string | null>(null);

  // 移动端（<768px）：右侧编辑面板收进底部抽屉，避免固定宽侧栏挤压画布
  const isMobile = useMediaQuery("(max-width: 767px)");
  const [panelOpen, setPanelOpen] = useState(true);

  // 当 initialJson 引用变化（切换工作流/重新加载）时同步内部 state
  useEffect(() => {
    setNodes(initial.nodes);
    setEdges(initial.edges);
    setVariables(initialJson.variables || []);
    setName(initialJson.name);
    setDescription(initialJson.description || "");
    setSelectedNodeId(null);
  }, [initial, initialJson]);

  const onNodesChange = useCallback(
    (changes: NodeChange[]) => {
      // 起止节点不可删除/不可拖动：过滤掉针对它们的 remove 与 position 变更
      const safe = changes.filter((c) => {
        if (c.type === "remove" && (c.id === START_NODE_ID || c.id === END_NODE_ID)) return false;
        return true;
      });
      setNodes((nds) => applyNodeChanges(safe, nds));
    },
    [],
  );

  const onEdgesChange = useCallback((changes: EdgeChange[]) => {
    setEdges((eds) => applyEdgeChanges(changes, eds));
  }, []);

  const onConnect = useCallback((params: Connection) => {
    // Connection.source/target 类型为 string | null，提取到局部 const 后 TypeScript 才能在闭包中保留窄化
    const src = params.source;
    const tgt = params.target;
    if (!src || !tgt) return;
    setEdges((eds) =>
      addEdge(
        makeDefaultEdge(`e${Date.now()}-${src}-${tgt}`, src, tgt),
        eds,
      ),
    );
  }, []);

  const onNodeClick = useCallback((_: React.MouseEvent, node: Node) => {
    setSelectedNodeId(node.id);
  }, []);

  const onPaneClick = useCallback(() => {
    setSelectedNodeId(null);
  }, []);

  // 工具箱拖拽：HTML5 drag → drop 到画布上时按屏幕坐标落地新节点
  const onDrop = useCallback(
    (e: React.DragEvent) => {
      e.preventDefault();
      const kind = e.dataTransfer.getData("application/reactflow");
      if (kind !== "agent" && kind !== "script") return;
      const position = screenToFlowPosition({ x: e.clientX, y: e.clientY });
      const newNode: Node<EditorNodeData> = {
        id: `n${Date.now()}`,
        type: "dfNode",
        position,
        data: {
          label: kind === "agent" ? "新 Agent 节点" : "新脚本节点",
          nodeType: kind,
          agentType: kind === "agent" ? "writer" : "",
          status: "pending",
          ...(kind === "script" ? { nodeParams: { script_name: "", script_args: "" } } : {}),
        },
      };
      setNodes((nds) => [...nds, newNode]);
      setSelectedNodeId(newNode.id);
    },
    [screenToFlowPosition],
  );

  const onDragOver = useCallback((e: React.DragEvent) => {
    e.preventDefault();
    e.dataTransfer.dropEffect = "move";
  }, []);

  const selectedNode = useMemo(
    () => nodes.find((n) => n.id === selectedNodeId) || null,
    [nodes, selectedNodeId],
  );

  const updateSelectedNodeData = useCallback(
    (patch: Partial<EditorNodeData>) => {
      if (!selectedNodeId) return;
      setNodes((nds) =>
        nds.map((n) =>
          n.id === selectedNodeId ? { ...n, data: { ...n.data, ...patch } } : n,
        ),
      );
    },
    [selectedNodeId],
  );

  const deleteSelectedNode = useCallback(() => {
    if (!selectedNodeId) return;
    if (selectedNodeId === START_NODE_ID || selectedNodeId === END_NODE_ID) return;
    setNodes((nds) => nds.filter((n) => n.id !== selectedNodeId));
    setEdges((eds) =>
      eds.filter((e) => e.source !== selectedNodeId && e.target !== selectedNodeId),
    );
    setSelectedNodeId(null);
  }, [selectedNodeId]);

  // 变量编辑器
  const addVariable = useCallback(() => {
    setVariables((vs) => [
      ...vs,
      {
        key: `var_${vs.length + 1}_${Math.random().toString(36).slice(2, 6)}`,
        name: "",
        type: "text",
        required: false,
        default: "",
      },
    ]);
  }, []);

  const updateVariable = useCallback(
    (index: number, patch: Partial<WorkflowVariableDef>) => {
      setVariables((vs) => vs.map((v, i) => (i === index ? { ...v, ...patch } : v)));
    },
    [],
  );

  const deleteVariable = useCallback((index: number) => {
    setVariables((vs) => vs.filter((_, i) => i !== index));
  }, []);

  const handleSave = useCallback(() => {
    const json = flowToWorkflowJson(nodes, edges, variables, name, description);
    onSave(json);
  }, [nodes, edges, variables, name, description, onSave]);

  // 编辑面板内容（桌面侧栏 / 移动端底部抽屉共用）
  const editorPanelContent = (
    <ScrollArea className="min-h-0 flex-1">
      <div className="space-y-4 p-3">
        <NodeToolbox />

        <Separator className="bg-secondary" />

        <NodeEditForm
          node={selectedNode}
          onUpdate={updateSelectedNodeData}
          onDelete={deleteSelectedNode}
        />

        <Separator className="bg-secondary" />

        <VariablesEditor
          variables={variables}
          onAdd={addVariable}
          onUpdate={updateVariable}
          onDelete={deleteVariable}
        />

        <Separator className="bg-secondary" />

        <WorkflowMetaForm
          name={name}
          description={description}
          onNameChange={setName}
          onDescriptionChange={setDescription}
        />
      </div>
    </ScrollArea>
  );

  return (
    <>
      <div className="flex h-full min-h-0 flex-1">
      {/* 中间：可编辑画布 */}
      <section className="flex min-w-0 flex-1 flex-col" aria-label="工作流编辑画布">
        {/* 编辑器顶部工具栏 */}
        <div className="flex h-11 shrink-0 items-center gap-2 border-b border-border bg-surface px-3">
          <Badge variant="primary">编辑模式</Badge>
          <span className="min-w-0 truncate text-sm font-medium text-foreground">{name}</span>
          <span className="hidden shrink-0 font-mono text-[10px] text-muted sm:inline">{workflowId}</span>
          <div className="ml-auto flex items-center gap-1.5">
            {isMobile && (
              <Button size="sm" variant="outline" onClick={() => setPanelOpen((v) => !v)}>
                <Settings2 size={13} aria-hidden="true" />
                {panelOpen ? "收起面板" : "编辑面板"}
              </Button>
            )}
            <Button size="sm" variant="ghost" onClick={onCancel} disabled={saving}>
              <X size={13} aria-hidden="true" />
              取消
            </Button>
            <Button size="sm" variant="primary" onClick={handleSave} disabled={saving}>
              {saving ? (
                <Loader2 size={13} className="animate-spin motion-reduce:animate-none" aria-hidden="true" />
              ) : (
                <Save size={13} aria-hidden="true" />
              )}
              保存
            </Button>
          </div>
        </div>

        <div className="min-h-0 flex-1" onDrop={onDrop} onDragOver={onDragOver}>
          <ReactFlow
            nodes={nodes}
            edges={edges}
            nodeTypes={nodeTypes}
            onNodesChange={onNodesChange}
            onEdgesChange={onEdgesChange}
            onConnect={onConnect}
            onNodeClick={onNodeClick}
            onPaneClick={onPaneClick}
            nodesDraggable
            nodesConnectable
            elementsSelectable
            fitView
            fitViewOptions={{ padding: 0.2, maxZoom: 1 }}
            zoomOnScroll
            panOnDrag
            deleteKeyCode={["Backspace", "Delete"]}
            className="h-full bg-background"
            aria-label="工作流编辑画布"
          >
            <Background variant={BackgroundVariant.Dots} gap={18} size={1} color="var(--border-strong)" />
            <Controls
              showInteractive={false}
              className="!border-border !bg-surface-elevated [&_button]:!border-border [&_button]:!bg-surface-elevated [&_button]:!fill-muted"
            />
          </ReactFlow>
        </div>
      </section>

      {/* 右侧：节点编辑面板（桌面/平板；移动端收进底部抽屉） */}
      {!isMobile && (
        <aside
          className="flex w-80 shrink-0 flex-col border-l border-border bg-surface"
          aria-label="工作流节点编辑面板"
        >
          <div className="flex h-11 shrink-0 items-center gap-2 border-b border-border px-4">
            <h2 className="text-sm font-semibold text-foreground">编辑面板</h2>
            <span className="ml-auto text-[10px] text-muted">拖拽工具箱到画布</span>
          </div>
          {editorPanelContent}
        </aside>
      )}
      </div>

      {/* 移动端：编辑面板底部抽屉 */}
      {isMobile && panelOpen && (
        <div
          className="fixed bottom-0 inset-x-0 z-30 flex max-h-[60vh] flex-col border-t border-border bg-surface shadow-[0_-8px_24px_rgba(0,0,0,0.12)]"
          style={{ paddingBottom: "env(safe-area-inset-bottom, 0px)" }}
        >
          <div className="flex h-12 shrink-0 items-center justify-between border-b border-border px-4">
            <span className="text-sm font-semibold text-foreground">编辑面板</span>
            <button
              type="button"
              onClick={() => setPanelOpen(false)}
              className="inline-flex h-10 items-center gap-1 rounded-lg px-3 text-sm text-muted transition-colors hover:bg-surface-hover"
              aria-label="收起编辑面板"
            >
              <X size={16} aria-hidden="true" /> 收起
            </button>
          </div>
          <div className="min-h-0 flex-1 overflow-y-auto">{editorPanelContent}</div>
        </div>
      )}
    </>
  );
}

/** 节点工具箱：可拖拽创建 Agent/Script 节点；Start/End 固定有（仅展示说明） */
function NodeToolbox() {
  const onDragStart = (e: React.DragEvent, kind: "agent" | "script") => {
    e.dataTransfer.setData("application/reactflow", kind);
    e.dataTransfer.effectAllowed = "move";
  };

  return (
    <section aria-label="节点工具箱">
      <h3 className="mb-2 text-xs font-semibold text-foreground">节点工具箱</h3>
      <div className="grid grid-cols-2 gap-2">
        <button
          type="button"
          draggable
          onDragStart={(e) => onDragStart(e, "agent")}
          className="flex cursor-grab flex-col items-center gap-1 rounded-lg border border-indigo-500/30 bg-indigo-500/10 px-2 py-2.5 text-center transition-colors hover:border-indigo-500/60 active:cursor-grabbing"
          title="拖拽到画布创建 Agent 节点"
        >
          <Bot size={18} className="text-indigo-400" aria-hidden="true" />
          <span className="text-[11px] font-medium text-indigo-300">Agent</span>
        </button>
        <button
          type="button"
          draggable
          onDragStart={(e) => onDragStart(e, "script")}
          className="flex cursor-grab flex-col items-center gap-1 rounded-lg border border-cyan-500/30 bg-cyan-500/10 px-2 py-2.5 text-center transition-colors hover:border-cyan-500/60 active:cursor-grabbing"
          title="拖拽到画布创建脚本节点"
        >
          <FileCode size={18} className="text-cyan-400" aria-hidden="true" />
          <span className="text-[11px] font-medium text-cyan-300">Script</span>
        </button>
      </div>
      <div className="mt-2 flex items-center justify-between gap-2 rounded-lg border border-border bg-surface-elevated px-2.5 py-1.5">
        <span className="flex items-center gap-1.5 text-[10px] text-muted">
          <CircleDot size={12} className="text-green-400" aria-hidden="true" />
          起始（固定）
        </span>
        <span className="flex items-center gap-1.5 text-[10px] text-muted">
          <SquareIcon size={11} className="text-red-400" aria-hidden="true" />
          结束（固定）
        </span>
        <span className="flex items-center gap-1 text-[10px] text-muted">
          <PlayCircle size={12} aria-hidden="true" />
          拖拽创建
        </span>
      </div>
    </section>
  );
}

/** 节点编辑表单：未选中节点时显示提示；选中后按 agent/script 显示对应字段 */
interface NodeEditFormProps {
  node: Node<EditorNodeData> | null;
  onUpdate: (patch: Partial<EditorNodeData>) => void;
  onDelete: () => void;
}

function NodeEditForm({ node, onUpdate, onDelete }: NodeEditFormProps) {
  if (!node) {
    return (
      <section aria-label="节点编辑表单">
        <h3 className="mb-2 text-xs font-semibold text-foreground">节点属性</h3>
        <p className="rounded-lg border border-dashed border-border px-3 py-4 text-center text-[11px] text-muted">
          点击画布上的节点以编辑属性
        </p>
      </section>
    );
  }

  // 起止节点只读
  const isTerminal = node.id === START_NODE_ID || node.id === END_NODE_ID;
  const d = node.data;
  const isScript = d.nodeType === "script";

  return (
    <section aria-label="节点编辑表单">
      <div className="mb-2 flex items-center gap-2">
        <h3 className="text-xs font-semibold text-foreground">节点属性</h3>
        {isTerminal && <Badge variant="default">固定节点</Badge>}
        {!isTerminal && (
          <Badge variant={isScript ? "primary" : "warning"}>
            {isScript ? "Script" : "Agent"}
          </Badge>
        )}
      </div>

      <div className="space-y-2.5">
        {/* ID（只读） */}
        <div className="space-y-1">
          <Label className="text-[11px] text-muted">节点 ID</Label>
          <Input value={node.id} readOnly className="h-8 bg-surface-elevated font-mono text-[11px]" />
        </div>

        {/* Label */}
        <div className="space-y-1">
          <Label htmlFor="wf-node-label" className="text-[11px]">
            显示名称
          </Label>
          <Input
            id="wf-node-label"
            value={d.label}
            onChange={(e) => onUpdate({ label: e.target.value })}
            disabled={isTerminal}
            className="h-8 text-xs"
          />
        </div>

        {/* Agent 专属字段 */}
        {!isScript && !isTerminal && (
          <>
            <div className="space-y-1">
              <Label htmlFor="wf-node-agent-type" className="text-[11px]">
                agent_type
              </Label>
              <select
                id="wf-node-agent-type"
                value={d.agentType || "writer"}
                onChange={(e) => onUpdate({ agentType: e.target.value })}
                className="h-8 w-full rounded-lg border border-border-strong/60 bg-surface px-2 text-xs text-foreground focus-visible:outline-none"
              >
                {AGENT_TYPES.map((t) => (
                  <option key={t} value={t}>
                    {t}
                  </option>
                ))}
              </select>
            </div>

            <div className="space-y-1">
              <Label htmlFor="wf-node-first-message" className="text-[11px]">
                first_message（prompt）
              </Label>
              <Textarea
                id="wf-node-first-message"
                value={d.firstMessage || ""}
                onChange={(e) => onUpdate({ firstMessage: e.target.value })}
                rows={4}
                placeholder="节点的提示词模板，可用 {{变量名}} 引用工作流变量"
                className="text-xs"
              />
            </div>
          </>
        )}

        {/* Script 专属字段 */}
        {isScript && !isTerminal && (
          <>
            <div className="space-y-1">
              <Label htmlFor="wf-script-name" className="text-[11px]">
                script_name
              </Label>
              <Input
                id="wf-script-name"
                value={d.nodeParams?.script_name || ""}
                onChange={(e) =>
                  onUpdate({
                    nodeParams: { ...(d.nodeParams || {}), script_name: e.target.value },
                  })
                }
                placeholder="如 json_to_md"
                className="h-8 font-mono text-xs"
              />
            </div>

            <div className="space-y-1">
              <Label htmlFor="wf-script-args" className="text-[11px]">
                script_args
              </Label>
              <Input
                id="wf-script-args"
                value={d.nodeParams?.script_args || ""}
                onChange={(e) =>
                  onUpdate({
                    nodeParams: { ...(d.nodeParams || {}), script_args: e.target.value },
                  })
                }
                placeholder="--input {{file}}"
                className="h-8 font-mono text-xs"
              />
            </div>
          </>
        )}

        {/* 通用：output_variable */}
        {!isTerminal && (
          <div className="space-y-1">
            <Label htmlFor="wf-node-output" className="text-[11px]">
              output_variable（可选）
            </Label>
            <Input
              id="wf-node-output"
              value={d.outputVariable || ""}
              onChange={(e) => onUpdate({ outputVariable: e.target.value })}
              placeholder="如 output1"
              className="h-8 font-mono text-xs"
            />
          </div>
        )}

        {/* 通用：fail_auto_skip */}
        {!isTerminal && (
          <div className="flex items-center justify-between rounded-lg border border-border bg-surface-elevated px-2.5 py-1.5">
            <div className="flex flex-col">
              <Label className="text-[11px] text-foreground">fail_auto_skip</Label>
              <span className="text-[10px] text-muted">节点失败时自动跳过</span>
            </div>
            <Switch
              checked={Boolean(d.failAutoSkip)}
              onCheckedChange={(c) => onUpdate({ failAutoSkip: c })}
              aria-label="失败自动跳过"
            />
          </div>
        )}

        {/* 删除按钮 */}
        {!isTerminal && (
          <Button
            size="sm"
            variant="danger"
            onClick={onDelete}
            className="w-full"
            title="删除该节点（及其相关连线）"
          >
            <Trash2 size={13} aria-hidden="true" />
            删除节点
          </Button>
        )}
      </div>
    </section>
  );
}

/** 变量编辑器：增删改 variables 列表 */
interface VariablesEditorProps {
  variables: WorkflowVariableDef[];
  onAdd: () => void;
  onUpdate: (index: number, patch: Partial<WorkflowVariableDef>) => void;
  onDelete: (index: number) => void;
}

function VariablesEditor({ variables, onAdd, onUpdate, onDelete }: VariablesEditorProps) {
  return (
    <section aria-label="变量编辑器">
      <div className="mb-2 flex items-center gap-2">
        <h3 className="text-xs font-semibold text-foreground">工作流变量</h3>
        <span className="text-[10px] text-muted">{variables.length}</span>
        <Button size="sm" variant="ghost" onClick={onAdd} className="ml-auto h-6 px-2 text-[11px]">
          <Plus size={11} aria-hidden="true" />
          新增
        </Button>
      </div>

      {variables.length === 0 ? (
        <p className="rounded-lg border border-dashed border-border px-3 py-3 text-center text-[11px] text-muted">
          暂无变量，点击「新增」添加
        </p>
      ) : (
        <div className="space-y-2.5">
          {variables.map((v, i) => (
            <div
              key={`${v.key}-${i}`}
              className="space-y-1.5 rounded-lg border border-border bg-surface-elevated p-2"
            >
              <div className="flex items-center gap-1.5">
                <Input
                  value={v.key}
                  onChange={(e) => onUpdate(i, { key: e.target.value })}
                  placeholder="key"
                  className="h-7 flex-1 font-mono text-[11px]"
                  aria-label="变量 key"
                />
                <Button
                  size="sm"
                  variant="ghost"
                  onClick={() => onDelete(i)}
                  className="h-7 w-7 shrink-0 p-0 text-muted hover:text-red-400"
                  aria-label="删除变量"
                >
                  <Trash2 size={12} aria-hidden="true" />
                </Button>
              </div>
              <Input
                value={v.name}
                onChange={(e) => onUpdate(i, { name: e.target.value })}
                placeholder="显示名称"
                className="h-7 text-[11px]"
                aria-label="变量名称"
              />
              <div className="flex items-center gap-1.5">
                <select
                  value={v.type}
                  onChange={(e) => onUpdate(i, { type: e.target.value })}
                  className="h-7 flex-1 rounded-lg border border-border-strong/60 bg-surface px-1.5 text-[11px] text-foreground focus-visible:outline-none"
                  aria-label="变量类型"
                >
                  {VARIABLE_TYPES.map((t) => (
                    <option key={t} value={t}>
                      {t}
                    </option>
                  ))}
                </select>
                <label className="flex shrink-0 items-center gap-1 text-[10px] text-muted">
                  <input
                    type="checkbox"
                    checked={Boolean(v.required)}
                    onChange={(e) => onUpdate(i, { required: e.target.checked })}
                    className="h-3 w-3"
                  />
                  必填
                </label>
              </div>
              <Input
                value={v.default || ""}
                onChange={(e) => onUpdate(i, { default: e.target.value })}
                placeholder="默认值（可选）"
                className="h-7 text-[11px]"
                aria-label="变量默认值"
              />
            </div>
          ))}
        </div>
      )}
    </section>
  );
}

/** 工作流元信息表单：name / description */
interface WorkflowMetaFormProps {
  name: string;
  description: string;
  onNameChange: (v: string) => void;
  onDescriptionChange: (v: string) => void;
}

function WorkflowMetaForm({ name, description, onNameChange, onDescriptionChange }: WorkflowMetaFormProps) {
  return (
    <section aria-label="工作流元信息">
      <h3 className="mb-2 text-xs font-semibold text-foreground">工作流信息</h3>
      <div className="space-y-2.5">
        <div className="space-y-1">
          <Label htmlFor="wf-meta-name" className="text-[11px]">
            名称
          </Label>
          <Input
            id="wf-meta-name"
            value={name}
            onChange={(e) => onNameChange(e.target.value)}
            className="h-8 text-xs"
          />
        </div>
        <div className="space-y-1">
          <Label htmlFor="wf-meta-desc" className="text-[11px]">
            描述
          </Label>
          <Textarea
            id="wf-meta-desc"
            value={description}
            onChange={(e) => onDescriptionChange(e.target.value)}
            rows={2}
            placeholder="工作流用途说明"
            className="text-xs"
          />
        </div>
      </div>
    </section>
  );
}

/** 默认导出：用 ReactFlowProvider 包裹，使内部组件可调用 useReactFlow */
export default function WorkflowEditor(props: WorkflowEditorProps) {
  return (
    <ReactFlowProvider>
      <WorkflowEditorInner {...props} />
    </ReactFlowProvider>
  );
}
