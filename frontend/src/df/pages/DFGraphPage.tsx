// 小说内容图谱页：展示与编辑人物关系 / 势力关系 / 伏笔网络 / 章节脉络 / 世界地图等知识图谱。
// 数据走后端 /api/bible/{project_id}/graphs 系列接口，画布基于 ReactFlow。

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import ReactFlow, {
  Background,
  Controls,
  Handle,
  MarkerType,
  Position,
  ReactFlowProvider,
  addEdge,
  useEdgesState,
  useNodesState,
  useReactFlow,
  type Connection,
  type Edge,
  type Node,
  type NodeProps,
  type OnEdgesChange,
  type OnNodesChange,
} from "reactflow";
import "reactflow/dist/style.css";
import {
  AlertTriangle,
  ChevronDown,
  Database,
  Eye,
  GitBranch,
  Layers,
  LayoutGrid,
  ListTree,
  Loader2,
  MapPin,
  MapPinned,
  Menu,
  Network,
  Pencil,
  Plus,
  RefreshCw,
  Save,
  Shield,
  ShieldAlert,
  Sparkles,
  Trash2,
  Users,
  Wand2,
  X,
} from "lucide-react";
import type { LucideIcon } from "lucide-react";
import { AppLayout } from "@/components/layout/AppLayout";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { EntityCardDrawer, type EntityCardType } from "@/components/entity/EntityCardDrawer";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { ScrollArea } from "@/components/ui/scroll-area";
import { Select } from "@/components/ui/select";
import { Textarea } from "@/components/ui/textarea";
import { useCurrentProject } from "@/hooks/useCurrentProject";
import { useToast } from "@/hooks/useToast";
import { useMediaQuery } from "@/hooks/useMediaQuery";
import { cn } from "@/lib/utils";
import { DFEmptyState } from "../components/dashboard/DFEmptyState";
import { DFIconButton, DFSecondaryButton } from "../components/admin/df-ui";

// ==================== 类型定义 ====================

type GraphType = "characters" | "factions" | "foreshadows" | "chapters" | "map" | "custom";

type GraphNodeType = "dfCharacter" | "dfFaction" | "dfForeshadow" | "dfOutline" | "dfLocation";

interface CharacterNodeData {
  label: string;
  role: string;
  importance: string;
  color: string;
  description?: string;
}

interface FactionNodeData {
  label: string;
  type: string;
  power_level: string;
  color: string;
  description?: string;
}

interface ForeshadowNodeData {
  label: string;
  description: string;
  planted_chapter: number;
  resolved_chapter: number | null;
  status: string;
  color: string;
}

interface OutlineNodeData {
  label: string;
  level: string;
  level_label: string;
  order: number;
  title: string;
  summary: string;
  color: string;
}

interface LocationNodeData {
  label: string;
  type: string;
  description: string;
  parent_name: string;
  importance: string;
  tier: string;
  layer: string;
  color: string;
}

interface GraphData {
  nodes: Node[];
  edges: Edge[];
}

interface GraphMeta {
  id: number;
  project_id: number;
  name: string;
  graph_type: GraphType;
  description: string;
  graph_data: GraphData;
  is_auto: boolean;
  created_at: string;
  updated_at: string;
}

interface AutoGenerateResult {
  name: string;
  graph_type: GraphType;
  description: string;
  graph_data: GraphData;
  is_auto: true;
}

interface Location {
  id: number;
  name: string;
  type: string;
  description: string;
  parent_name: string;
  coord_x: number | null;
  coord_y: number | null;
  importance: string;
  tier: string;
  layer: string;
}

interface LocationRelationship {
  id: number;
  project_id: number;
  source_location: string;
  target_location: string;
  relation_type: string;
  distance: number | null;
  description: string;
}

// ==================== 常量映射 ====================

const GRAPH_TYPE_LABEL: Record<GraphType, string> = {
  characters: "人物关系图",
  factions: "势力关系图",
  foreshadows: "伏笔网络图",
  chapters: "章节脉络图",
  map: "世界地图",
  custom: "自定义图谱",
};

const GRAPH_TYPE_BADGE: Record<GraphType, { variant: "primary" | "warning" | "success" | "danger" | "default"; icon: LucideIcon }> = {
  characters: { variant: "primary", icon: Users },
  factions: { variant: "warning", icon: Shield },
  foreshadows: { variant: "danger", icon: GitBranch },
  chapters: { variant: "success", icon: ListTree },
  map: { variant: "primary", icon: MapPin },
  custom: { variant: "default", icon: Network },
};

const NODE_TYPE_LABEL: Record<GraphNodeType, string> = {
  dfCharacter: "人物节点",
  dfFaction: "势力节点",
  dfForeshadow: "伏笔节点",
  dfOutline: "大纲节点",
  dfLocation: "地点节点",
};

const NODE_TYPE_ICON: Record<GraphNodeType, LucideIcon> = {
  dfCharacter: Users,
  dfFaction: Shield,
  dfForeshadow: GitBranch,
  dfOutline: ListTree,
  dfLocation: MapPin,
};

const NODE_TYPE_COLOR: Record<GraphNodeType, string> = {
  dfCharacter: "#8b5cf6",
  dfFaction: "#06b6d4",
  dfForeshadow: "#f59e0b",
  dfOutline: "#22c55e",
  dfLocation: "#ef4444",
};

/** 各图谱类型可使用的节点类型（工具箱依据此渲染） */
const GRAPH_TYPE_NODES: Record<GraphType, GraphNodeType[]> = {
  characters: ["dfCharacter"],
  factions: ["dfFaction"],
  foreshadows: ["dfForeshadow"],
  chapters: ["dfOutline"],
  map: ["dfLocation"],
  custom: ["dfCharacter", "dfFaction", "dfForeshadow", "dfOutline", "dfLocation"],
};

const IMPORTANCE_OPTIONS = ["主角", "核心", "重要", "次要", "背景", "普通", "边缘"];
const LOCATION_TIER_OPTIONS = ["continent", "kingdom", "region", "city", "town", "site", "dungeon", "landmark", "other"];
const LOCATION_LAYER_OPTIONS = ["surface", "celestial", "underworld", "underwater", "realm", "other"];
const FACTION_POWER_OPTIONS = ["顶尖", "高", "中", "低"];
const FORESHADOW_STATUS_OPTIONS = ["planted", "resolved", "abandoned"];
const OUTLINE_LEVEL_OPTIONS = ["volume", "arc", "chapter"];
const OUTLINE_LEVEL_LABEL: Record<string, string> = { volume: "卷", arc: "弧", chapter: "章" };

interface FieldDef {
  key: string;
  label: string;
  type: "text" | "textarea" | "number" | "color" | "select";
  options?: string[];
  nullable?: boolean;
}

const FIELD_CONFIGS: Record<GraphNodeType, FieldDef[]> = {
  dfCharacter: [
    { key: "label", label: "名称", type: "text" },
    { key: "role", label: "角色定位", type: "text" },
    { key: "importance", label: "重要度", type: "select", options: IMPORTANCE_OPTIONS },
    { key: "color", label: "颜色", type: "color" },
  ],
  dfFaction: [
    { key: "label", label: "名称", type: "text" },
    { key: "type", label: "类型", type: "text" },
    { key: "power_level", label: "实力", type: "select", options: FACTION_POWER_OPTIONS },
    { key: "color", label: "颜色", type: "color" },
  ],
  dfForeshadow: [
    { key: "label", label: "标题", type: "text" },
    { key: "description", label: "描述", type: "textarea" },
    { key: "planted_chapter", label: "埋设章节", type: "number" },
    { key: "resolved_chapter", label: "回收章节", type: "number", nullable: true },
    { key: "status", label: "状态", type: "select", options: FORESHADOW_STATUS_OPTIONS },
    { key: "color", label: "颜色", type: "color" },
  ],
  dfOutline: [
    { key: "label", label: "标签", type: "text" },
    { key: "level", label: "层级", type: "select", options: OUTLINE_LEVEL_OPTIONS },
    { key: "level_label", label: "层级名", type: "text" },
    { key: "order", label: "序号", type: "number" },
    { key: "title", label: "标题", type: "text" },
    { key: "summary", label: "摘要", type: "textarea" },
    { key: "color", label: "颜色", type: "color" },
  ],
  dfLocation: [
    { key: "label", label: "名称", type: "text" },
    { key: "type", label: "类型", type: "text" },
    { key: "tier", label: "层级", type: "select", options: LOCATION_TIER_OPTIONS },
    { key: "layer", label: "领域", type: "select", options: LOCATION_LAYER_OPTIONS },
    { key: "description", label: "描述", type: "textarea" },
    { key: "parent_name", label: "上级地点", type: "text" },
    { key: "importance", label: "重要度", type: "select", options: IMPORTANCE_OPTIONS },
    { key: "color", label: "颜色", type: "color" },
  ],
};

// ==================== 后端接口封装 ====================

const API_BASE = "/api/bible";

function extractErrorMessage(status: number, text: string): string {
  if (!text) return `请求失败（HTTP ${status}）`;
  try {
    const parsed = JSON.parse(text);
    if (parsed.detail) return String(parsed.detail);
    if (parsed.message) return String(parsed.message);
  } catch {
    // 非 JSON，返回原文
  }
  return text;
}

async function request<T>(path: string, options: RequestInit = {}): Promise<T> {
  const isFormData = options.body instanceof FormData;
  const res = await fetch(`${API_BASE}${path}`, {
    headers: isFormData ? undefined : { "Content-Type": "application/json" },
    ...options,
  });
  if (!res.ok) {
    const text = await res.text().catch(() => "");
    throw new Error(extractErrorMessage(res.status, text));
  }
  if (res.status === 204) return undefined as T;
  return (await res.json()) as T;
}

const graphApi = {
  list: (projectId: number) => request<GraphMeta[]>(`/${projectId}/graphs`),
  get: (projectId: number, graphId: number) => request<GraphMeta>(`/${projectId}/graphs/${graphId}`),
  create: (projectId: number, body: { name: string; graph_type: GraphType; description: string; graph_data: GraphData; is_auto: boolean }) =>
    request<GraphMeta>(`/${projectId}/graphs`, { method: "POST", body: JSON.stringify(body) }),
  update: (projectId: number, graphId: number, body: { name?: string; description?: string; graph_data?: GraphData }) =>
    request<GraphMeta>(`/${projectId}/graphs/${graphId}`, { method: "PUT", body: JSON.stringify(body) }),
  remove: (projectId: number, graphId: number) =>
    request<void>(`/${projectId}/graphs/${graphId}`, { method: "DELETE" }),
  autoGenerate: (projectId: number, body: { graph_type: GraphType; name?: string }) =>
    request<AutoGenerateResult>(`/${projectId}/graphs/auto-generate`, { method: "POST", body: JSON.stringify(body) }),
  listLocations: (projectId: number) => request<Location[]>(`/${projectId}/locations`),
  createLocation: (projectId: number, body: Omit<Location, "id">) =>
    request<Location>(`/${projectId}/locations`, { method: "POST", body: JSON.stringify(body) }),
  updateLocation: (projectId: number, id: number, body: Omit<Location, "id">) =>
    request<Location>(`/${projectId}/locations/${id}`, { method: "PUT", body: JSON.stringify(body) }),
  deleteLocation: (projectId: number, id: number) =>
    request<void>(`/${projectId}/locations/${id}`, { method: "DELETE" }),
  listLocationRelationships: (projectId: number) =>
    request<LocationRelationship[]>(`/${projectId}/location-relationships`),
  createLocationRelationship: (projectId: number, body: Omit<LocationRelationship, "id" | "project_id">) =>
    request<LocationRelationship>(`/${projectId}/location-relationships`, { method: "POST", body: JSON.stringify(body) }),
  deleteLocationRelationship: (projectId: number, id: number) =>
    request<void>(`/${projectId}/location-relationships/${id}`, { method: "DELETE" }),
  autoClassifyLocations: (projectId: number) =>
    request<{ updated: number; total: number }>(`/${projectId}/locations/auto-classify`, { method: "POST", body: "{}" }),
  validateLocationHierarchy: (projectId: number) =>
    request<{ issues: { location: string; issue: string; severity: string; detail: string }[]; total: number; error_count: number; warning_count: number }>(`/${projectId}/locations/validate-hierarchy`),
};

// ==================== 工具函数 ====================

function createNode(type: GraphNodeType, position: { x: number; y: number }): Node {
  const id = `${type}_${Date.now()}_${Math.floor(Math.random() * 1000)}`;
  switch (type) {
    case "dfCharacter":
      return { id, type, position, data: { label: "新人物", role: "", importance: "次要", color: NODE_TYPE_COLOR.dfCharacter } };
    case "dfFaction":
      return { id, type, position, data: { label: "新势力", type: "", power_level: "中", color: NODE_TYPE_COLOR.dfFaction } };
    case "dfForeshadow":
      return { id, type, position, data: { label: "新伏笔", description: "", planted_chapter: 1, resolved_chapter: null, status: "planted", color: NODE_TYPE_COLOR.dfForeshadow } };
    case "dfOutline":
      return { id, type, position, data: { label: "新章节", level: "chapter", level_label: "章", order: 1, title: "", summary: "", color: NODE_TYPE_COLOR.dfOutline } };
    case "dfLocation":
      return { id, type, position, data: { label: "新地点", type: "", description: "", parent_name: "", importance: "普通", color: NODE_TYPE_COLOR.dfLocation } };
  }
}

/** 序列化画布状态为后端可接受的 graph_data（剥离 ReactFlow 运行时字段） */
function serializeGraph(nodes: Node[], edges: Edge[]): GraphData {
  return {
    nodes: nodes.map((n) => ({
      id: n.id,
      type: n.type,
      position: n.position,
      data: n.data,
    })),
    edges: edges.map((e) => ({
      id: e.id,
      source: e.source,
      target: e.target,
      label: e.label,
      type: e.type,
      style: e.style,
      markerEnd: e.markerEnd,
    })),
  };
}

function formatTime(iso: string): string {
  if (!iso) return "";
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return iso;
  const pad = (n: number) => String(n).padStart(2, "0");
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())} ${pad(d.getHours())}:${pad(d.getMinutes())}`;
}

// ==================== 自定义节点组件 ====================

function NodeShell({
  data,
  color,
  icon: Icon,
  children,
}: {
  data: { color?: string; label?: string };
  color: string;
  icon: LucideIcon;
  children?: React.ReactNode;
}) {
  const accent = data.color || color;
  return (
    <div
      className="w-[260px] rounded-xl border-2 bg-surface-elevated px-3 py-2.5 shadow-lg transition-shadow"
      style={{ borderColor: `${accent}66` }}
    >
      <Handle type="target" position={Position.Top} className="!opacity-0" />
      <div className="flex items-center gap-1.5">
        <Icon size={13} className="shrink-0" style={{ color: accent }} aria-hidden="true" />
        <span className="min-w-0 flex-1 break-words text-xs font-semibold text-foreground">{data.label || "未命名"}</span>
      </div>
      {children}
      <Handle type="source" position={Position.Bottom} className="!opacity-0" />
    </div>
  );
}

function DFCharacterNode({ data }: NodeProps<CharacterNodeData>) {
  const accent = data.color || NODE_TYPE_COLOR.dfCharacter;
  return (
    <NodeShell data={data} color={NODE_TYPE_COLOR.dfCharacter} icon={Users}>
      <div className="mt-1.5 flex items-start justify-between gap-1">
        <span
          className="min-w-0 flex-1 break-words rounded px-1 py-0.5 text-[10px] font-medium"
          style={{ backgroundColor: `${accent}1f`, color: accent }}
        >
          {data.role || "未设定"}
        </span>
        <span className="shrink-0 text-[10px] text-muted">{data.importance || ""}</span>
      </div>
    </NodeShell>
  );
}

function DFFactionNode({ data }: NodeProps<FactionNodeData>) {
  const accent = data.color || NODE_TYPE_COLOR.dfFaction;
  return (
    <NodeShell data={data} color={NODE_TYPE_COLOR.dfFaction} icon={Shield}>
      <div className="mt-1.5 flex items-start justify-between gap-1">
        <span
          className="min-w-0 flex-1 break-words rounded px-1 py-0.5 text-[10px] font-medium"
          style={{ backgroundColor: `${accent}1f`, color: accent }}
        >
          {data.type || "未分类"}
        </span>
        <span className="shrink-0 text-[10px] text-muted">实力 {data.power_level || "-"}</span>
      </div>
    </NodeShell>
  );
}

function DFForeshadowNode({ data }: NodeProps<ForeshadowNodeData>) {
  const accent = data.color || NODE_TYPE_COLOR.dfForeshadow;
  const statusLabel = data.status === "resolved" ? "已回收" : data.status === "abandoned" ? "已废弃" : "待回收";
  return (
    <NodeShell data={data} color={NODE_TYPE_COLOR.dfForeshadow} icon={GitBranch}>
      <div className="mt-1.5 flex items-center justify-between gap-1">
        <span className="shrink-0 text-[10px] text-muted">
          第{data.planted_chapter ?? "?"}章
          {data.resolved_chapter ? ` → 第${data.resolved_chapter}章` : ""}
        </span>
        <span
          className="rounded px-1 py-0.5 text-[10px] font-medium"
          style={{ backgroundColor: `${accent}1f`, color: accent }}
        >
          {statusLabel}
        </span>
      </div>
      {data.description && (
        <div
          className="mt-1 max-h-[60px] overflow-y-auto break-words text-[10px] leading-relaxed text-muted"
          title={data.description}
        >
          {data.description}
        </div>
      )}
    </NodeShell>
  );
}

function DFOutlineNode({ data }: NodeProps<OutlineNodeData>) {
  const accent = data.color || NODE_TYPE_COLOR.dfOutline;
  return (
    <NodeShell data={data} color={NODE_TYPE_COLOR.dfOutline} icon={ListTree}>
      <div className="mt-1.5 flex items-center justify-between gap-1">
        <span
          className="rounded px-1 py-0.5 text-[10px] font-medium"
          style={{ backgroundColor: `${accent}1f`, color: accent }}
        >
          {data.level_label || OUTLINE_LEVEL_LABEL[data.level] || data.level}
        </span>
        <span className="shrink-0 text-[10px] tabular-nums text-muted">#{data.order ?? 0}</span>
      </div>
      {data.title && (
        <div
          className="mt-1 max-h-[64px] overflow-y-auto break-words text-[10px] leading-relaxed text-foreground"
          title={data.title}
        >
          {data.title}
        </div>
      )}
    </NodeShell>
  );
}

function DFLocationNode({ data }: NodeProps<LocationNodeData>) {
  const accent = data.color || NODE_TYPE_COLOR.dfLocation;
  return (
    <NodeShell data={data} color={NODE_TYPE_COLOR.dfLocation} icon={MapPin}>
      <div className="mt-1.5 flex items-center justify-between gap-1">
        <span
          className="min-w-0 flex-1 truncate rounded px-1 py-0.5 text-[10px] font-medium"
          style={{ backgroundColor: `${accent}1f`, color: accent }}
        >
          {data.type || "地点"}
        </span>
        {data.parent_name && (
          <span className="min-w-0 max-w-[90px] truncate text-[10px] text-muted">↑ {data.parent_name}</span>
        )}
      </div>
    </NodeShell>
  );
}

/** 节点类型注册（模块级常量，避免每次渲染重建） */
const nodeTypes = {
  dfCharacter: DFCharacterNode,
  dfFaction: DFFactionNode,
  dfForeshadow: DFForeshadowNode,
  dfOutline: DFOutlineNode,
  dfLocation: DFLocationNode,
};

// ==================== 页面主组件 ====================

export default function DFGraphPage() {
  return (
    <AppLayout>
      <ReactFlowProvider>
        <GraphPageContent />
      </ReactFlowProvider>
    </AppLayout>
  );
}

function GraphPageContent() {
  const { projectId } = useCurrentProject();
  const { showError, showSuccess } = useToast();

  // ---- 图谱列表 ----
  const [graphs, setGraphs] = useState<GraphMeta[]>([]);
  const [listLoading, setListLoading] = useState(false);
  const [listError, setListError] = useState<string | null>(null);
  const [selectedGraphId, setSelectedGraphId] = useState<number | null>(null);

  // ---- 画布状态 ----
  const [nodes, setNodes, onNodesChange] = useNodesState([]);
  const [edges, setEdges, onEdgesChange] = useEdgesState([]);
  const [mode, setMode] = useState<"preview" | "edit">("preview");
  const [selectedNodeId, setSelectedNodeId] = useState<string | null>(null);
  const [canvasLoading, setCanvasLoading] = useState(false);
  const [canvasError, setCanvasError] = useState<string | null>(null);

  // ---- 实体卡片抽屉 ----
  const [cardDrawer, setCardDrawer] = useState<{ entityType: EntityCardType; entityId: string } | null>(null);

  // ---- 保存 ----
  const [saving, setSaving] = useState(false);
  // 未保存修改防护：记录最近一次已保存/已加载的画布快照，与当前画布对比
  const [savedSnapshot, setSavedSnapshot] = useState("");
  const [discardOpen, setDiscardOpen] = useState(false);
  const pendingDiscardRef = useRef<(() => void) | null>(null);

  // ---- 弹窗 ----
  const [autoGenDialog, setAutoGenDialog] = useState<{ open: boolean; loading: boolean; data: AutoGenerateResult | null }>({
    open: false,
    loading: false,
    data: null,
  });
  const [newGraphDialog, setNewGraphDialog] = useState(false);
  const [deleteConfirm, setDeleteConfirm] = useState(false);

  // 移动端（<768px）：图谱列表抽屉 + 底部工具栏
  const isMobile = useMediaQuery("(max-width: 767px)");
  const [graphListOpen, setGraphListOpen] = useState(false);

  // ---- 地点管理（map 图谱） ----
  const [locations, setLocations] = useState<Location[]>([]);
  const [locationRels, setLocationRels] = useState<LocationRelationship[]>([]);
  const [locationsLoading, setLocationsLoading] = useState(false);

  const selectedGraph = useMemo(
    () => graphs.find((g) => g.id === selectedGraphId) ?? null,
    [graphs, selectedGraphId],
  );

  const selectedNode = useMemo(
    () => nodes.find((n) => n.id === selectedNodeId) ?? null,
    [nodes, selectedNodeId],
  );

  // ---- 加载图谱列表 ----
  const loadGraphs = useCallback(async () => {
    if (!projectId) return;
    setListLoading(true);
    setListError(null);
    try {
      const data = await graphApi.list(projectId);
      setGraphs(data);
      // 默认选中第一个（若当前未选中）
      setSelectedGraphId((prev) => prev ?? data[0]?.id ?? null);
    } catch (e) {
      setListError(e instanceof Error ? e.message : String(e));
    } finally {
      setListLoading(false);
    }
  }, [projectId]);

  useEffect(() => {
    void loadGraphs();
  }, [loadGraphs]);

  // ---- 切换图谱：加载详情并重置画布 ----
  useEffect(() => {
    if (!selectedGraphId || !projectId) {
      setNodes([]);
      setEdges([]);
      setSelectedNodeId(null);
      setCanvasError(null);
      setSavedSnapshot("");
      return;
    }
    let cancelled = false;
    setCanvasLoading(true);
    setCanvasError(null);
    setSelectedNodeId(null);
    setMode("preview");
    graphApi
      .get(projectId, selectedGraphId)
      .then((g) => {
        if (cancelled) return;
        const loadedNodes = g.graph_data?.nodes ?? [];
        const loadedEdges = g.graph_data?.edges ?? [];
        setNodes(loadedNodes);
        setEdges(loadedEdges);
        setSavedSnapshot(JSON.stringify(serializeGraph(loadedNodes, loadedEdges)));
      })
      .catch((e) => {
        if (cancelled) return;
        setCanvasError(e instanceof Error ? e.message : String(e));
        setNodes([]);
        setEdges([]);
      })
      .finally(() => {
        if (!cancelled) setCanvasLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [projectId, selectedGraphId, setNodes, setEdges]);

  // ---- map 图谱进入编辑模式时加载地点与关系 ----
  useEffect(() => {
    if (!projectId || mode !== "edit" || selectedGraph?.graph_type !== "map") return;
    let cancelled = false;
    setLocationsLoading(true);
    Promise.all([
      graphApi.listLocations(projectId).catch(() => [] as Location[]),
      graphApi.listLocationRelationships(projectId).catch(() => [] as LocationRelationship[]),
    ])
      .then(([locs, rels]) => {
        if (cancelled) return;
        setLocations(locs);
        setLocationRels(rels);
      })
      .finally(() => {
        if (!cancelled) setLocationsLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [projectId, mode, selectedGraph?.graph_type]);

  // ---- 画布交互 ----
  const isPreview = mode === "preview";

  // 编辑模式下画布有未保存修改
  const isDirty = useMemo(
    () => !isPreview && savedSnapshot !== "" && JSON.stringify(serializeGraph(nodes, edges)) !== savedSnapshot,
    [nodes, edges, isPreview, savedSnapshot],
  );

  // 切换图谱：有未保存修改时先确认
  const handleSelectGraph = useCallback(
    (id: number) => {
      if (id === selectedGraphId) return;
      if (isDirty) {
        pendingDiscardRef.current = () => setSelectedGraphId(id);
        setDiscardOpen(true);
        return;
      }
      setSelectedGraphId(id);
    },
    [selectedGraphId, isDirty],
  );

  const handleNodesChange: OnNodesChange = useCallback(
    (changes) => {
      if (isPreview) return;
      onNodesChange(changes);
    },
    [isPreview, onNodesChange],
  );

  const handleEdgesChange: OnEdgesChange = useCallback(
    (changes) => {
      if (isPreview) return;
      onEdgesChange(changes);
    },
    [isPreview, onEdgesChange],
  );

  const handleConnect = useCallback(
    (connection: Connection) => {
      if (isPreview) return;
      setEdges((eds) =>
        addEdge(
          {
            ...connection,
            id: `edge_${Date.now()}_${Math.floor(Math.random() * 1000)}`,
            type: "smoothstep",
            style: { stroke: "#64748b", strokeWidth: 1.5 },
            markerEnd: { type: MarkerType.ArrowClosed, color: "#64748b" },
          },
          eds,
        ),
      );
    },
    [isPreview, setEdges],
  );

  const handleNodeClick = useCallback(
    (_: React.MouseEvent, node: Node) => {
      setSelectedNodeId(node.id);
      // 移动端：单击节点直接打开实体卡片（桌面保持单击选中、双击打开）
      if (isMobile) openNodeCard(node);
    },
    [isMobile],
  );

  /** 按节点类型打开实体卡片抽屉（大纲节点无实体卡，跳过） */
  const openNodeCard = useCallback((node: Node) => {
    const type = node.type as GraphNodeType;
    const label = (node.data as { label?: string } | undefined)?.label;
    if (!label) return;
    switch (type) {
      case "dfCharacter":
        setCardDrawer({ entityType: "character", entityId: label });
        break;
      case "dfFaction":
        setCardDrawer({ entityType: "faction", entityId: label });
        break;
      case "dfForeshadow":
        setCardDrawer({ entityType: "foreshadow", entityId: label });
        break;
      case "dfLocation":
        setCardDrawer({ entityType: "location", entityId: label });
        break;
      default:
        break; // dfOutline：无实体卡片
    }
  }, []);

  /** 双击节点打开对应实体卡片抽屉 */
  const handleNodeDoubleClick = useCallback((_: React.MouseEvent, node: Node) => {
    openNodeCard(node);
  }, [openNodeCard]);

  const handlePaneClick = useCallback(() => {
    setSelectedNodeId(null);
  }, []);

  // ---- 拖拽创建节点 ----
  const { screenToFlowPosition } = useReactFlow();
  const canvasWrapperRef = useRef<HTMLDivElement>(null);

  const handleDrop = useCallback(
    (event: React.DragEvent) => {
      event.preventDefault();
      if (isPreview) return;
      const type = event.dataTransfer.getData("application/reactflow") as GraphNodeType;
      if (!type || !NODE_TYPE_LABEL[type]) return;
      const position = screenToFlowPosition({ x: event.clientX, y: event.clientY });
      setNodes((nds) => nds.concat(createNode(type, position)));
    },
    [isPreview, screenToFlowPosition, setNodes],
  );

  const handleDragOver = useCallback((event: React.DragEvent) => {
    event.preventDefault();
    event.dataTransfer.dropEffect = "copy";
  }, []);

  // ---- 节点数据更新 ----
  const handleUpdateNodeData = useCallback(
    (id: string, patch: Record<string, unknown>) => {
      setNodes((nds) =>
        nds.map((n) => (n.id === id ? { ...n, data: { ...n.data, ...patch } } : n)),
      );
    },
    [setNodes],
  );

  const handleDeleteNode = useCallback(
    (id: string) => {
      setNodes((nds) => nds.filter((n) => n.id !== id));
      setEdges((eds) => eds.filter((e) => e.source !== id && e.target !== id));
      setSelectedNodeId(null);
    },
    [setNodes, setEdges],
  );

  // ---- 保存 ----
  const handleSave = useCallback(async () => {
    if (!projectId || !selectedGraphId) return;
    setSaving(true);
    try {
      await graphApi.update(projectId, selectedGraphId, {
        graph_data: serializeGraph(nodes, edges),
      });
      showSuccess("图谱已保存");
      setSavedSnapshot(JSON.stringify(serializeGraph(nodes, edges)));
      // 同步列表中对应图谱的 graph_data
      setGraphs((prev) =>
        prev.map((g) =>
          g.id === selectedGraphId
            ? { ...g, graph_data: serializeGraph(nodes, edges), updated_at: new Date().toISOString() }
            : g,
        ),
      );
    } catch (e) {
      showError("保存失败：" + (e instanceof Error ? e.message : String(e)));
    } finally {
      setSaving(false);
    }
  }, [projectId, selectedGraphId, nodes, edges, showSuccess, showError, setGraphs]);

  // ---- 删除图谱 ----
  const handleDeleteGraph = useCallback(async () => {
    if (!projectId || !selectedGraphId) return;
    try {
      await graphApi.remove(projectId, selectedGraphId);
      setDeleteConfirm(false);
      const remaining = graphs.filter((g) => g.id !== selectedGraphId);
      setGraphs(remaining);
      setSelectedGraphId(remaining[0]?.id ?? null);
      showSuccess("图谱已删除");
    } catch (e) {
      showError("删除失败：" + (e instanceof Error ? e.message : String(e)));
    }
  }, [projectId, selectedGraphId, graphs, showSuccess, showError]);

  // ---- 一键生成 ----
  const handleAutoGenerate = useCallback(
    async (type: GraphType) => {
      if (!projectId) return;
      setAutoGenDialog({ open: true, loading: true, data: null });
      try {
        const result = await graphApi.autoGenerate(projectId, { graph_type: type });
        setAutoGenDialog({ open: true, loading: false, data: result });
      } catch (e) {
        showError("生成失败：" + (e instanceof Error ? e.message : String(e)));
        setAutoGenDialog({ open: false, loading: false, data: null });
      }
    },
    [projectId, showError],
  );

  // ---- 重新布局（对已保存图谱重新生成布局，覆盖画布，需手动保存）----
  const [relayouting, setRelayouting] = useState(false);
  const handleRelayout = useCallback(async () => {
    if (!projectId || !selectedGraph) return;
    if (selectedGraph.graph_type === "custom") {
      showError("自定义空白图谱不支持自动重新布局，请手动拖动节点");
      return;
    }
    setRelayouting(true);
    try {
      const result = await graphApi.autoGenerate(projectId, { graph_type: selectedGraph.graph_type });
      setNodes(result.graph_data.nodes ?? []);
      setEdges(result.graph_data.edges ?? []);
      setSelectedNodeId(null);
      showSuccess(`已重新布局（${result.graph_data.nodes.length} 节点），记得点击「保存」固化`);
    } catch (e) {
      showError("重新布局失败：" + (e instanceof Error ? e.message : String(e)));
    } finally {
      setRelayouting(false);
    }
  }, [projectId, selectedGraph, setNodes, setEdges, showSuccess, showError]);

  const handleConfirmAutoGenSave = useCallback(async () => {
    if (!projectId || !autoGenDialog.data) return;
    try {
      const created = await graphApi.create(projectId, {
        name: autoGenDialog.data.name,
        graph_type: autoGenDialog.data.graph_type,
        description: autoGenDialog.data.description,
        graph_data: autoGenDialog.data.graph_data,
        is_auto: true,
      });
      setGraphs((prev) => [...prev, created]);
      setSelectedGraphId(created.id);
      setAutoGenDialog({ open: false, loading: false, data: null });
      showSuccess("已保存为新图谱");
    } catch (e) {
      showError("保存失败：" + (e instanceof Error ? e.message : String(e)));
    }
  }, [projectId, autoGenDialog.data, showSuccess, showError]);

  // ---- 新建空白图谱 ----
  const handleCreateBlank = useCallback(
    async (input: { name: string; graph_type: GraphType; description: string }) => {
      if (!projectId) return;
      try {
        const created = await graphApi.create(projectId, {
          name: input.name,
          graph_type: input.graph_type,
          description: input.description,
          graph_data: { nodes: [], edges: [] },
          is_auto: false,
        });
        setGraphs((prev) => [created, ...prev]);
        setSelectedGraphId(created.id);
        setNewGraphDialog(false);
        showSuccess("已创建空白图谱");
      } catch (e) {
        showError("创建失败：" + (e instanceof Error ? e.message : String(e)));
      }
    },
    [projectId, showSuccess, showError],
  );

  // ---- 地点 CRUD ----
  const handleLocationSubmit = useCallback(
    async (input: Omit<Location, "id">, id?: number) => {
      if (!projectId) return;
      try {
        if (id !== undefined) {
          const updated = await graphApi.updateLocation(projectId, id, input);
          setLocations((prev) => prev.map((l) => (l.id === id ? updated : l)));
          showSuccess("地点已更新");
        } else {
          const created = await graphApi.createLocation(projectId, input);
          setLocations((prev) => [...prev, created]);
          showSuccess("地点已添加");
        }
      } catch (e) {
        showError("保存地点失败：" + (e instanceof Error ? e.message : String(e)));
      }
    },
    [projectId, showSuccess, showError],
  );

  const handleLocationDelete = useCallback(
    async (id: number) => {
      if (!projectId) return;
      try {
        await graphApi.deleteLocation(projectId, id);
        setLocations((prev) => prev.filter((l) => l.id !== id));
        showSuccess("地点已删除");
      } catch (e) {
        showError("删除失败：" + (e instanceof Error ? e.message : String(e)));
      }
    },
    [projectId, showSuccess, showError],
  );

  const handleRelAdd = useCallback(
    async (input: Omit<LocationRelationship, "id" | "project_id">) => {
      if (!projectId) return;
      try {
        const created = await graphApi.createLocationRelationship(projectId, input);
        setLocationRels((prev) => [...prev, created]);
        showSuccess("关系已添加");
      } catch (e) {
        showError("添加关系失败：" + (e instanceof Error ? e.message : String(e)));
      }
    },
    [projectId, showSuccess, showError],
  );

  const handleRelDelete = useCallback(
    async (id: number) => {
      if (!projectId) return;
      try {
        await graphApi.deleteLocationRelationship(projectId, id);
        setLocationRels((prev) => prev.filter((r) => r.id !== id));
        showSuccess("关系已删除");
      } catch (e) {
        showError("删除失败：" + (e instanceof Error ? e.message : String(e)));
      }
    },
    [projectId, showSuccess, showError],
  );

  // ---- 地点自动分类 & 层级校验 ----
  const handleAutoClassify = useCallback(async () => {
    if (!projectId) return;
    try {
      const res = await graphApi.autoClassifyLocations(projectId);
      showSuccess(`已自动分类 ${res.updated}/${res.total} 个地点`);
      const locs = await graphApi.listLocations(projectId);
      setLocations(locs);
    } catch (e) {
      showError("自动分类失败：" + (e instanceof Error ? e.message : String(e)));
    }
  }, [projectId, showSuccess, showError]);

  const handleValidateHierarchy = useCallback(async () => {
    if (!projectId) return;
    try {
      const res = await graphApi.validateLocationHierarchy(projectId);
      showSuccess(`校验完成：${res.error_count} 错误，${res.warning_count} 警告`);
      return res;
    } catch (e) {
      showError("层级校验失败：" + (e instanceof Error ? e.message : String(e)));
      return null;
    }
  }, [projectId, showSuccess, showError]);

  // 编辑面板内容（桌面侧栏 / 移动端底部抽屉共用）
  const editPanelContent = selectedGraph ? (
    <EditPanel
      graph={selectedGraph}
      selectedNode={selectedNode}
      onUpdateNodeData={handleUpdateNodeData}
      onDeleteNode={handleDeleteNode}
      locations={locations}
      locationRels={locationRels}
      locationsLoading={locationsLoading}
      onLocationSubmit={handleLocationSubmit}
      onLocationDelete={handleLocationDelete}
      onRelAdd={handleRelAdd}
      onRelDelete={handleRelDelete}
      onAutoClassify={handleAutoClassify}
      onValidateHierarchy={handleValidateHierarchy}
    />
  ) : null;

  return (
    <div className="flex h-full flex-col">
      {/* ========== 顶部工具栏 ========== */}
      <header
        className="flex flex-wrap items-center gap-3 border-b border-border bg-surface px-4 py-2"
        role="toolbar"
        aria-label="图谱工具栏"
      >
        {isMobile ? (
          /* ===== 移动端：返回/切图 + 图谱名 + 编辑切换 ===== */
          <>
            <div className="flex min-w-0 flex-1 items-center gap-1.5">
              <DFIconButton
                type="button"
                onClick={() => setGraphListOpen(true)}
                className="inline-flex h-10 w-10 min-h-0 min-w-0 shrink-0 items-center justify-center rounded-lg text-muted transition-colors hover:bg-surface-hover hover:text-muted"
                aria-label="打开图谱列表"
              >
                <Menu size={20} aria-hidden="true" />
              </DFIconButton>
              <Network size={16} className="shrink-0 text-cyan-400" aria-hidden="true" />
              <h2 className="truncate text-sm font-semibold text-foreground">{selectedGraph?.name || "图谱"}</h2>
              {selectedGraph && (
                <DFIconButton
                  type="button"
                  onClick={() => setGraphListOpen(true)}
                  className="inline-flex h-10 w-10 min-h-0 min-w-0 shrink-0 items-center justify-center rounded-lg text-muted transition-colors hover:bg-surface-hover hover:text-muted"
                  aria-label="切换图谱"
                >
                  <ChevronDown size={14} aria-hidden="true" />
                </DFIconButton>
              )}
            </div>
            <div className="flex shrink-0 items-center gap-2">
              {!isPreview && (
                <Button variant="primary" size="sm" onClick={handleSave} disabled={!selectedGraphId || saving}>
                  {saving ? <Loader2 size={14} className="animate-spin motion-reduce:animate-none" aria-hidden="true" /> : <Save size={14} aria-hidden="true" />}
                  保存
                </Button>
              )}
              <Button
                variant={isPreview ? "primary" : "outline"}
                size="sm"
                onClick={() => {
                  if (!isPreview && isDirty) {
                    pendingDiscardRef.current = () => setMode("preview");
                    setDiscardOpen(true);
                    return;
                  }
                  setMode(isPreview ? "edit" : "preview");
                }}
                disabled={!selectedGraphId}
              >
                {isPreview ? <Pencil size={14} aria-hidden="true" /> : <Eye size={14} aria-hidden="true" />}
                {isPreview ? "编辑" : "预览"}
              </Button>
            </div>
          </>
        ) : (
          /* ===== 桌面版（保持原样） ===== */
          <>
        <div className="flex min-w-0 items-center gap-2">
          <Network size={16} className="shrink-0 text-cyan-400" aria-hidden="true" />
          <h2 className="text-sm font-semibold text-foreground">图谱</h2>
          {selectedGraph && (
            <>
              <span className="text-muted">/</span>
              <span className="truncate text-sm text-muted">{selectedGraph.name}</span>
              <span className="hidden shrink-0 rounded-md bg-surface-hover px-1.5 py-0.5 text-[10px] text-muted md:inline">
                双击节点查看实体详情
              </span>
            </>
          )}
        </div>

        <div className="ml-auto flex flex-wrap items-center gap-2">
          <AutoGenerateDropdown onPick={handleAutoGenerate} disabled={!projectId || autoGenDialog.loading} />

          <Button variant="default" size="sm" onClick={() => setNewGraphDialog(true)} disabled={!projectId}>
            <Plus size={14} aria-hidden="true" />
            新建空白图谱
          </Button>

          {selectedGraph && (
            <Button
              variant="outline"
              size="sm"
              onClick={handleRelayout}
              disabled={!selectedGraphId || relayouting || selectedGraph?.graph_type === "custom"}
              title={selectedGraph?.graph_type === "custom"
                ? "自定义空白图谱不支持自动重新布局"
                : "根据后端最新布局算法重新排列当前图谱节点（需手动保存固化）"}
            >
              {relayouting ? (
                <Loader2 size={14} className="animate-spin motion-reduce:animate-none" aria-hidden="true" />
              ) : (
                <LayoutGrid size={14} aria-hidden="true" />
              )}
              重新布局
            </Button>
          )}

          {!isPreview && (
            <Button variant="primary" size="sm" onClick={handleSave} disabled={!selectedGraphId || saving}>
              {saving ? <Loader2 size={14} className="animate-spin motion-reduce:animate-none" aria-hidden="true" /> : <Save size={14} aria-hidden="true" />}
              保存
            </Button>
          )}

          <Button
            variant={isPreview ? "primary" : "outline"}
            size="sm"
            onClick={() => {
              if (!isPreview && isDirty) {
                pendingDiscardRef.current = () => setMode("preview");
                setDiscardOpen(true);
                return;
              }
              setMode(isPreview ? "edit" : "preview");
            }}
            disabled={!selectedGraphId}
          >
            {isPreview ? <Pencil size={14} aria-hidden="true" /> : <Eye size={14} aria-hidden="true" />}
            {isPreview ? "编辑" : "预览"}
          </Button>

          <Button
            variant="danger"
            size="sm"
            onClick={() => setDeleteConfirm(true)}
            disabled={!selectedGraphId}
          >
            <Trash2 size={14} aria-hidden="true" />
            删除
          </Button>
        </div>
          </>
        )}
      </header>

      {/* ========== 主体三栏 ========== */}
      <div className="flex min-h-0 flex-1">
        {/* 左侧图谱列表（桌面/平板；移动端收进抽屉） */}
        <aside
          className={cn(
            "flex w-64 shrink-0 flex-col border-r border-border bg-surface",
            isMobile && "hidden"
          )}
          aria-label="图谱列表"
        >
          <div className="flex items-center gap-2 border-b border-border px-4 py-3">
            <Layers size={14} className="text-cyan-400" aria-hidden="true" />
            <h3 className="text-sm font-semibold text-foreground">我的图谱</h3>
            <span className="ml-auto text-xs tabular-nums text-muted">{graphs.length}</span>
            <DFIconButton
              type="button"
              onClick={() => void loadGraphs()}
              disabled={listLoading}
              aria-label="刷新图谱列表"
              className="flex min-h-[28px] min-w-[28px] cursor-pointer items-center justify-center rounded-md text-muted transition-colors hover:bg-surface-hover hover:text-foreground disabled:cursor-not-allowed disabled:opacity-50"
            >
              <RefreshCw size={12} className={listLoading ? "animate-spin motion-reduce:animate-none" : ""} aria-hidden="true" />
            </DFIconButton>
          </div>
          <ScrollArea className="flex-1">
            <GraphList
              graphs={graphs}
              loading={listLoading}
              error={listError}
              selectedId={selectedGraphId}
              onSelect={handleSelectGraph}
              onRetry={() => void loadGraphs()}
            />
          </ScrollArea>
        </aside>

        {/* 中间画布（移动端为底部工具栏预留空间） */}
        <div
          ref={canvasWrapperRef}
          className={cn("relative min-w-0 flex-1", isMobile && isPreview && "pb-[60px]")}
          onDrop={handleDrop}
          onDragOver={handleDragOver}
        >
          <GraphCanvas
            loading={canvasLoading}
            error={canvasError}
            hasSelection={!!selectedGraphId}
            hasGraphs={graphs.length > 0}
            nodes={nodes}
            edges={edges}
            isPreview={isPreview}
            onNodesChange={handleNodesChange}
            onEdgesChange={handleEdgesChange}
            onConnect={handleConnect}
            onNodeClick={handleNodeClick}
            onNodeDoubleClick={handleNodeDoubleClick}
            onPaneClick={handlePaneClick}
          />
        </div>

        {/* 右侧编辑面板（桌面/平板；移动端为底部抽屉） */}
        {!isPreview && selectedGraph && !isMobile && (
          <aside
            className="flex w-80 shrink-0 flex-col border-l border-border bg-surface"
            aria-label="编辑面板"
          >
            <div className="flex items-center gap-2 border-b border-border px-4 py-3">
              <Pencil size={14} className="text-cyan-400" aria-hidden="true" />
              <h3 className="min-w-0 flex-1 truncate text-sm font-semibold text-foreground">编辑面板</h3>
              <span className="shrink-0 text-[11px] text-muted">{selectedGraph.name}</span>
            </div>
            <ScrollArea className="flex-1">{editPanelContent}</ScrollArea>
          </aside>
        )}
      </div>

      {/* 移动端：图谱列表抽屉 */}
      {isMobile && graphListOpen && (
        <div className="fixed inset-0 z-40 md:hidden" role="dialog" aria-modal="true" aria-label="图谱列表抽屉">
          <div className="absolute inset-0 bg-black/40" onClick={() => setGraphListOpen(false)} aria-hidden="true" />
          <div className="absolute left-0 top-0 bottom-0 flex w-72 max-w-[85vw] flex-col border-r border-border bg-surface shadow-xl">
            <div className="flex h-14 shrink-0 items-center justify-between border-b border-border px-4">
              <span className="text-sm font-semibold text-foreground">我的图谱</span>
              <DFIconButton
                type="button"
                onClick={() => setGraphListOpen(false)}
                className="inline-flex h-10 w-10 min-h-0 min-w-0 items-center justify-center rounded-lg text-foreground transition-colors hover:bg-surface-hover"
                aria-label="关闭图谱列表"
              >
                <X size={20} aria-hidden="true" />
              </DFIconButton>
            </div>
            <ScrollArea className="flex-1">
              <GraphList
                graphs={graphs}
                loading={listLoading}
                error={listError}
                selectedId={selectedGraphId}
                onSelect={(id) => {
                  handleSelectGraph(id);
                  setGraphListOpen(false);
                }}
                onRetry={() => void loadGraphs()}
              />
            </ScrollArea>
            <div className="shrink-0 border-t border-border p-2">
              <Button
                variant="default"
                size="sm"
                className="w-full"
                onClick={() => {
                  setGraphListOpen(false);
                  setNewGraphDialog(true);
                }}
              >
                <Plus size={14} aria-hidden="true" /> 新建空白图谱
              </Button>
            </div>
          </div>
        </div>
      )}

      {/* 移动端：底部工具栏（预览模式） */}
      {isMobile && isPreview && selectedGraphId && !canvasLoading && (
        <div
          className="fixed bottom-0 inset-x-0 z-20 flex items-center justify-around border-t border-border bg-surface-elevated px-2"
          style={{ paddingBottom: "calc(env(safe-area-inset-bottom, 0px) + 4px)" }}
          role="toolbar"
          aria-label="图谱底部工具栏"
        >
          <DFIconButton
            type="button"
            onClick={() => setNewGraphDialog(true)}
            className="flex min-h-[48px] min-w-0 flex-1 flex-col items-center justify-center gap-0.5 rounded-lg text-muted transition-colors hover:bg-surface-hover hover:text-muted"
            aria-label="新建空白图谱"
          >
            <Plus size={18} aria-hidden="true" />
            <span className="text-[10px]">新建</span>
          </DFIconButton>
          <DFIconButton
            type="button"
            onClick={handleRelayout}
            disabled={!selectedGraphId || relayouting || selectedGraph?.graph_type === "custom"}
            className="flex min-h-[48px] min-w-0 flex-1 flex-col items-center justify-center gap-0.5 rounded-lg text-muted transition-colors hover:bg-surface-hover hover:text-muted disabled:opacity-40"
            aria-label="重新布局"
          >
            {relayouting ? (
              <Loader2 size={18} className="animate-spin motion-reduce:animate-none" aria-hidden="true" />
            ) : (
              <LayoutGrid size={18} aria-hidden="true" />
            )}
            <span className="text-[10px]">布局</span>
          </DFIconButton>
          <DFIconButton
            type="button"
            onClick={() => setDeleteConfirm(true)}
            disabled={!selectedGraphId}
            className="flex min-h-[48px] min-w-0 flex-1 flex-col items-center justify-center gap-0.5 rounded-lg text-danger transition-colors hover:bg-danger/10 hover:text-danger disabled:opacity-40"
            aria-label="删除图谱"
          >
            <Trash2 size={18} aria-hidden="true" />
            <span className="text-[10px]">删除</span>
          </DFIconButton>
        </div>
      )}

      {/* 移动端：编辑面板（编辑模式，底部抽屉） */}
      {isMobile && !isPreview && selectedGraph && (
        <div
          className="fixed bottom-0 inset-x-0 z-30 flex max-h-[60vh] flex-col border-t border-border bg-surface shadow-[0_-8px_24px_rgba(0,0,0,0.12)]"
          style={{ paddingBottom: "env(safe-area-inset-bottom, 0px)" }}
        >
          <div className="flex h-12 shrink-0 items-center justify-between border-b border-border px-4">
            <span className="text-sm font-semibold text-foreground">编辑面板</span>
            <DFIconButton
              type="button"
              onClick={() => setMode("preview")}
              className="inline-flex h-10 min-h-0 items-center justify-start gap-1 rounded-lg px-3 text-sm text-muted transition-colors hover:bg-surface-hover hover:text-muted"
              aria-label="收起编辑面板"
            >
              <Eye size={16} aria-hidden="true" /> 收起
            </DFIconButton>
          </div>
          <div className="min-h-0 flex-1 overflow-y-auto">{editPanelContent}</div>
        </div>
      )}

      {/* ========== 弹窗 ========== */}
      <AutoGenPreviewDialog
        state={autoGenDialog}
        onClose={() => setAutoGenDialog({ open: false, loading: false, data: null })}
        onConfirm={handleConfirmAutoGenSave}
      />

      <NewGraphDialog open={newGraphDialog} onClose={() => setNewGraphDialog(false)} onSubmit={handleCreateBlank} />

      <DeleteConfirmDialog
        open={deleteConfirm}
        graphName={selectedGraph?.name ?? ""}
        onClose={() => setDeleteConfirm(false)}
        onConfirm={handleDeleteGraph}
      />

      {/* 放弃未保存修改确认 */}
      <Dialog open={discardOpen} onOpenChange={setDiscardOpen}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>放弃未保存的修改？</DialogTitle>
          </DialogHeader>
          <p className="text-sm text-muted">当前图谱有未保存的修改，切换后将丢失。确定继续吗？</p>
          <div className="flex justify-end gap-2">
            <Button variant="ghost" size="sm" onClick={() => setDiscardOpen(false)}>取消</Button>
            <Button
              variant="danger"
              size="sm"
              onClick={() => {
                setDiscardOpen(false);
                pendingDiscardRef.current?.();
                pendingDiscardRef.current = null;
              }}
            >
              放弃修改
            </Button>
          </div>
        </DialogContent>
      </Dialog>

      {/* ========== 实体卡片抽屉（双击节点打开） ========== */}
      {cardDrawer && projectId && (
        <EntityCardDrawer
          open={cardDrawer !== null}
          onClose={() => setCardDrawer(null)}
          projectId={projectId}
          entityType={cardDrawer.entityType}
          entityId={cardDrawer.entityId}
        />
      )}
    </div>
  );
}

// ==================== 子组件 ====================

/** 一键生成下拉按钮 */
function AutoGenerateDropdown({
  onPick,
  disabled,
}: {
  onPick: (type: GraphType) => void;
  disabled?: boolean;
}) {
  const [open, setOpen] = useState(false);
  const ref = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!open) return;
    const onDoc = (e: MouseEvent) => {
      // 用 composedPath 避免 reactflow Node 类型与 DOM Node 同名冲突
      if (ref.current && !e.composedPath().includes(ref.current)) setOpen(false);
    };
    document.addEventListener("mousedown", onDoc);
    return () => document.removeEventListener("mousedown", onDoc);
  }, [open]);

  const options: { type: GraphType; label: string; icon: LucideIcon }[] = [
    { type: "characters", label: "人物关系图", icon: Users },
    { type: "factions", label: "势力关系图", icon: Shield },
    { type: "foreshadows", label: "伏笔网络图", icon: GitBranch },
    { type: "chapters", label: "章节脉络图", icon: ListTree },
    { type: "map", label: "世界地图", icon: MapPin },
  ];

  return (
    <div className="relative" ref={ref}>
      <Button variant="primary" size="sm" onClick={() => setOpen((o) => !o)} disabled={disabled}>
        <Sparkles size={14} aria-hidden="true" />
        一键生成
        <ChevronDown size={12} aria-hidden="true" />
      </Button>
      {open && (
        <div
          role="menu"
          className="absolute right-0 top-full z-30 mt-1 w-44 rounded-lg border border-border bg-surface-elevated py-1 shadow-xl"
        >
          {options.map((o) => (
            <DFIconButton
              key={o.type}
              type="button"
              role="menuitem"
              onClick={() => {
                setOpen(false);
                onPick(o.type);
              }}
              className="flex w-full min-h-0 items-center justify-start gap-2 px-3 py-2 text-left text-xs text-foreground transition-colors hover:bg-surface-hover"
            >
              <o.icon size={14} className="text-muted" aria-hidden="true" />
              {o.label}
            </DFIconButton>
          ))}
        </div>
      )}
    </div>
  );
}

/** 左侧图谱列表 */
function GraphList({
  graphs,
  loading,
  error,
  selectedId,
  onSelect,
  onRetry,
}: {
  graphs: GraphMeta[];
  loading: boolean;
  error: string | null;
  selectedId: number | null;
  onSelect: (id: number) => void;
  onRetry: () => void;
}) {
  if (loading && graphs.length === 0) {
    return <ListStatus icon="spinner" text="加载图谱列表..." />;
  }
  if (error) {
    return (
      <div className="flex flex-col items-center gap-2 px-4 py-10 text-center" role="alert">
        <p className="text-xs text-danger">{error}</p>
        <DFSecondaryButton
          type="button"
          accent="cyan"
          onClick={onRetry}
          className="flex min-h-[36px] cursor-pointer items-center justify-start gap-1.5 rounded-lg border border-cyan-500/30 bg-cyan-500/10 px-3 text-xs font-normal text-cyan-300 transition-colors hover:bg-cyan-500/20"
        >
          <RefreshCw size={12} aria-hidden="true" />
          重试
        </DFSecondaryButton>
      </div>
    );
  }
  if (graphs.length === 0) {
    return <ListStatus text="暂无图谱" />;
  }
  return (
    <ul className="p-2" aria-label="图谱列表">
      {graphs.map((g) => {
        const active = g.id === selectedId;
        const badge = GRAPH_TYPE_BADGE[g.graph_type] ?? GRAPH_TYPE_BADGE.custom;
        const TypeIcon = badge.icon;
        return (
          <li key={g.id}>
            <DFIconButton
              type="button"
              onClick={() => onSelect(g.id)}
              aria-current={active}
              className={`mb-1 flex min-h-[44px] w-full cursor-pointer flex-col items-stretch justify-start gap-1 rounded-lg border px-3 py-2 text-left transition-colors ${
                active
                  ? "border-cyan-500/30 bg-cyan-500/10 hover:bg-cyan-500/10 hover:text-cyan-300"
                  : "border-transparent hover:bg-surface-hover"
              }`}
            >
              <div className="flex items-center gap-1.5">
                <TypeIcon size={12} className={active ? "text-cyan-300" : "text-muted"} aria-hidden="true" />
                <span className={`min-w-0 flex-1 truncate text-sm ${active ? "text-cyan-300" : "text-foreground"}`}>
                  {g.name}
                </span>
                {g.is_auto && (
                  <span className="shrink-0 rounded bg-amber-500/15 px-1 py-0.5 text-[9px] font-medium text-amber-300">
                    自动
                  </span>
                )}
              </div>
              <div className="flex items-center gap-2 text-[10px] text-muted">
                <span className="truncate">{GRAPH_TYPE_LABEL[g.graph_type]}</span>
                <span className="ml-auto shrink-0 tabular-nums">{formatTime(g.updated_at)}</span>
              </div>
            </DFIconButton>
          </li>
        );
      })}
    </ul>
  );
}

/** 列表加载/空态行 */
function ListStatus({ icon, text }: { icon?: "spinner"; text: string }) {
  return (
    <div
      className="flex items-center justify-center gap-2 px-4 py-10 text-xs text-muted"
      role="status"
    >
      {icon === "spinner" && (
        <Loader2 size={14} className="animate-spin text-cyan-400 motion-reduce:animate-none" aria-hidden="true" />
      )}
      {text}
    </div>
  );
}

/** 画布区（含各状态分支） */
function GraphCanvas({
  loading,
  error,
  hasSelection,
  hasGraphs,
  nodes,
  edges,
  isPreview,
  onNodesChange,
  onEdgesChange,
  onConnect,
  onNodeClick,
  onNodeDoubleClick,
  onPaneClick,
}: {
  loading: boolean;
  error: string | null;
  hasSelection: boolean;
  hasGraphs: boolean;
  nodes: Node[];
  edges: Edge[];
  isPreview: boolean;
  onNodesChange: OnNodesChange;
  onEdgesChange: OnEdgesChange;
  onConnect: (connection: Connection) => void;
  onNodeClick: (event: React.MouseEvent, node: Node) => void;
  onNodeDoubleClick: (event: React.MouseEvent, node: Node) => void;
  onPaneClick: (event: React.MouseEvent) => void;
}) {
  if (loading) {
    return (
      <div className="flex h-full flex-col items-center justify-center gap-2 text-muted" role="status">
        <Loader2 size={20} className="animate-spin text-cyan-400 motion-reduce:animate-none" aria-hidden="true" />
        <span className="text-sm">加载图谱数据...</span>
      </div>
    );
  }
  if (error) {
    return (
      <DFEmptyState
        title="图谱加载失败"
        description={error}
      />
    );
  }
  if (!hasGraphs || !hasSelection) {
    return (
      <DFEmptyState
        title="未选择图谱"
        description="从左侧选择图谱，或点击右上角「新建空白图谱」开始创作"
      />
    );
  }
  const isEmpty = nodes.length === 0 && edges.length === 0;
  return (
    <div className="relative h-full">
      <ReactFlow
        nodes={nodes}
        edges={edges}
        onNodesChange={onNodesChange}
        onEdgesChange={onEdgesChange}
        onConnect={onConnect}
        onNodeClick={onNodeClick}
        onNodeDoubleClick={onNodeDoubleClick}
        onPaneClick={onPaneClick}
        nodeTypes={nodeTypes}
        nodesDraggable={!isPreview}
        nodesConnectable={!isPreview}
        elementsSelectable
        deleteKeyCode={!isPreview ? ["Backspace", "Delete"] : []}
        fitView
        fitViewOptions={{ padding: 0.2, minZoom: 0.55, maxZoom: 1.0 }}
        minZoom={0.1}
        maxZoom={2.5}
        className="bg-background"
        aria-label="小说内容图谱画布"
      >
        <Background color="var(--border)" gap={24} />
        <Controls className="!rounded-lg !border-border-strong !bg-surface-elevated [&_button]:!border-border-strong [&_button]:!bg-surface-elevated [&_button:hover]:!bg-secondary [&_svg]:!fill-muted" />
      </ReactFlow>
      {/* 空画布引导：新建空白图谱后提示下一步操作（不拦截画布点击） */}
      {isEmpty && (
        <div className="pointer-events-none absolute inset-0 z-10 flex items-center justify-center">
          <div className="max-w-md rounded-xl border border-dashed border-border bg-surface-elevated/80 p-6 text-center shadow-sm">
            <div className="mb-2 text-2xl" aria-hidden="true">🗺️</div>
            <p className="text-sm font-semibold text-foreground">当前图谱还是空的</p>
            <p className="mt-2 text-xs leading-relaxed text-muted">
              {isPreview
                ? "点击右上角「编辑」进入编辑模式，再从右侧编辑面板把节点类型拖到画布上；也可以使用「一键生成」自动创建图谱。"
                : "从右侧编辑面板的节点类型列表拖拽节点到画布上，或用「一键生成」自动创建图谱。"}
            </p>
          </div>
        </div>
      )}
    </div>
  );
}

/** 右侧编辑面板 */
function EditPanel({
  graph,
  selectedNode,
  onUpdateNodeData,
  onDeleteNode,
  locations,
  locationRels,
  locationsLoading,
  onLocationSubmit,
  onLocationDelete,
  onRelAdd,
  onRelDelete,
  onAutoClassify,
  onValidateHierarchy,
}: {
  graph: GraphMeta;
  selectedNode: Node | null;
  onUpdateNodeData: (id: string, patch: Record<string, unknown>) => void;
  onDeleteNode: (id: string) => void;
  locations: Location[];
  locationRels: LocationRelationship[];
  locationsLoading: boolean;
  onLocationSubmit: (input: Omit<Location, "id">, id?: number) => void;
  onLocationDelete: (id: number) => void;
  onRelAdd: (input: Omit<LocationRelationship, "id" | "project_id">) => void;
  onRelDelete: (id: number) => void;
  onAutoClassify: () => Promise<void>;
  onValidateHierarchy: () => Promise<any>;
}) {
  const allowedNodes = GRAPH_TYPE_NODES[graph.graph_type] ?? GRAPH_TYPE_NODES.custom;
  const isMap = graph.graph_type === "map";

  return (
    <div className="space-y-4 p-3">
      {/* 节点工具箱 */}
      <section>
        <h4 className="mb-2 flex items-center gap-1.5 text-xs font-semibold uppercase tracking-wide text-muted">
          <Plus size={12} aria-hidden="true" />
          节点工具箱
        </h4>
        <p className="mb-2 text-[11px] text-muted">拖拽以下卡片到画布以创建节点</p>
        <div className="space-y-1.5">
          {allowedNodes.map((nt) => {
            const Icon = NODE_TYPE_ICON[nt];
            const color = NODE_TYPE_COLOR[nt];
            return (
              <div
                key={nt}
                draggable
                onDragStart={(e) => {
                  e.dataTransfer.setData("application/reactflow", nt);
                  e.dataTransfer.effectAllowed = "move";
                }}
                className="flex cursor-grab items-center gap-2 rounded-lg border border-border bg-surface-elevated px-3 py-2 text-xs text-foreground transition-colors hover:bg-surface-hover active:cursor-grabbing"
              >
                <Icon size={14} style={{ color }} aria-hidden="true" />
                <span className="flex-1">{NODE_TYPE_LABEL[nt]}</span>
                <span className="text-[10px] text-muted">拖拽</span>
              </div>
            );
          })}
        </div>
      </section>

      {/* 选中节点详情编辑 */}
      {selectedNode && (
        <NodeDetailEditor
          node={selectedNode}
          onUpdate={(patch) => onUpdateNodeData(selectedNode.id, patch)}
          onDelete={() => onDeleteNode(selectedNode.id)}
        />
      )}

      {/* 地点管理（仅 map 图谱） */}
      {isMap && (
        <LocationPanel
          locations={locations}
          locationRels={locationRels}
          loading={locationsLoading}
          onLocationSubmit={onLocationSubmit}
          onLocationDelete={onLocationDelete}
          onRelAdd={onRelAdd}
          onRelDelete={onRelDelete}
          onAutoClassify={onAutoClassify}
          onValidate={onValidateHierarchy}
        />
      )}
    </div>
  );
}

/** 节点详情编辑器 */
function NodeDetailEditor({
  node,
  onUpdate,
  onDelete,
}: {
  node: Node;
  onUpdate: (patch: Record<string, unknown>) => void;
  onDelete: () => void;
}) {
  const nodeType = node.type as GraphNodeType;
  const fields = FIELD_CONFIGS[nodeType] ?? [];
  const data = (node.data ?? {}) as Record<string, unknown>;
  const Icon = NODE_TYPE_ICON[nodeType] ?? Network;

  return (
    <section className="rounded-lg border border-border bg-surface-elevated p-3">
      <div className="mb-3 flex items-center gap-2">
        <Icon size={14} className="text-cyan-400" aria-hidden="true" />
        <h4 className="min-w-0 flex-1 truncate text-xs font-semibold text-foreground">
          {NODE_TYPE_LABEL[nodeType]}
        </h4>
        <DFIconButton
          type="button"
          onClick={onDelete}
          aria-label="删除节点"
          className="flex min-h-[28px] min-w-[28px] cursor-pointer items-center justify-center rounded-md text-danger transition-colors hover:bg-danger/10 hover:text-danger"
        >
          <Trash2 size={13} aria-hidden="true" />
        </DFIconButton>
      </div>

      <div className="space-y-2.5">
        {fields.map((f) => {
          const value = data[f.key];
          const fieldId = `node-field-${f.key}`;
          if (f.type === "textarea") {
            return (
              <div key={f.key} className="space-y-1">
                <Label htmlFor={fieldId} className="text-[11px] text-muted">{f.label}</Label>
                <Textarea
                  id={fieldId}
                  value={typeof value === "string" ? value : ""}
                  onChange={(e) => onUpdate({ [f.key]: e.target.value })}
                  className="min-h-[60px] text-xs"
                />
              </div>
            );
          }
          if (f.type === "number") {
            const numVal = typeof value === "number" ? value : value === null || value === undefined || value === "" ? "" : Number(value);
            return (
              <div key={f.key} className="space-y-1">
                <Label htmlFor={fieldId} className="text-[11px] text-muted">
                  {f.label}{f.nullable && <span className="ml-1 text-[10px]">（可空）</span>}
                </Label>
                <Input
                  id={fieldId}
                  type="number"
                  value={numVal}
                  onChange={(e) => {
                    const raw = e.target.value;
                    if (raw === "") {
                      onUpdate({ [f.key]: f.nullable ? null : 0 });
                    } else {
                      const n = Number(raw);
                      onUpdate({ [f.key]: Number.isNaN(n) ? (f.nullable ? null : 0) : n });
                    }
                  }}
                  className="text-xs"
                />
              </div>
            );
          }
          if (f.type === "color") {
            const colorVal = typeof value === "string" ? value : "#8b5cf6";
            return (
              <div key={f.key} className="flex items-center justify-between gap-2">
                <Label htmlFor={fieldId} className="text-[11px] text-muted">{f.label}</Label>
                <div className="flex items-center gap-2">
                  <input
                    id={fieldId}
                    type="color"
                    value={colorVal}
                    onChange={(e) => onUpdate({ [f.key]: e.target.value })}
                    className="h-7 w-10 cursor-pointer rounded border border-border-strong bg-transparent"
                    aria-label={f.label}
                  />
                  <span className="font-mono text-[10px] text-muted">{colorVal}</span>
                </div>
              </div>
            );
          }
          if (f.type === "select" && f.options) {
            const strVal = typeof value === "string" ? value : "";
            return (
              <div key={f.key} className="space-y-1">
                <Label htmlFor={fieldId} className="text-[11px] text-muted">{f.label}</Label>
                <Select value={strVal} onChange={(e) => onUpdate({ [f.key]: e.target.value })} className="h-8 text-xs">
                  {strVal === "" && <option value="">未选择</option>}
                  {f.options.map((opt) => (
                    <option key={opt} value={opt}>{opt}</option>
                  ))}
                </Select>
              </div>
            );
          }
          // text
          return (
            <div key={f.key} className="space-y-1">
              <Label htmlFor={fieldId} className="text-[11px] text-muted">{f.label}</Label>
              <Input
                id={fieldId}
                value={typeof value === "string" ? value : ""}
                onChange={(e) => onUpdate({ [f.key]: e.target.value })}
                className="text-xs"
              />
            </div>
          );
        })}
      </div>
    </section>
  );
}

/** 地点管理面板（map 图谱专用） */
function LocationPanel({
  locations,
  locationRels,
  loading,
  onLocationSubmit,
  onLocationDelete,
  onRelAdd,
  onRelDelete,
  onAutoClassify,
  onValidate,
}: {
  locations: Location[];
  locationRels: LocationRelationship[];
  loading: boolean;
  onLocationSubmit: (input: Omit<Location, "id">, id?: number) => void;
  onLocationDelete: (id: number) => void;
  onRelAdd: (input: Omit<LocationRelationship, "id" | "project_id">) => void;
  onRelDelete: (id: number) => void;
  onAutoClassify: () => Promise<void>;
  onValidate: () => Promise<any>;
}) {
  // 地点表单
  const emptyLoc: Omit<Location, "id"> = {
    name: "",
    type: "",
    description: "",
    parent_name: "",
    coord_x: null,
    coord_y: null,
    importance: "普通",
    tier: "",
    layer: "surface",
  };
  const [locForm, setLocForm] = useState<Omit<Location, "id">>(emptyLoc);
  const [editingLocId, setEditingLocId] = useState<number | null>(null);

  // 层级校验结果
  const [validateResult, setValidateResult] = useState<{ issues: { location: string; issue: string; severity: string; detail: string }[]; total: number; error_count: number; warning_count: number } | null>(null);
  const [validating, setValidating] = useState(false);

  // 关系表单
  const emptyRel: Omit<LocationRelationship, "id" | "project_id"> = {
    source_location: "",
    target_location: "",
    relation_type: "相邻",
    distance: null,
    description: "",
  };
  const [relForm, setRelForm] = useState(emptyRel);

  const startEdit = (l: Location) => {
    setEditingLocId(l.id);
    setLocForm({
      name: l.name,
      type: l.type,
      description: l.description,
      parent_name: l.parent_name,
      coord_x: l.coord_x,
      coord_y: l.coord_y,
      importance: l.importance,
      tier: l.tier ?? "",
      layer: l.layer ?? "surface",
    });
  };

  const submitLoc = () => {
    if (!locForm.name.trim()) return;
    onLocationSubmit(locForm, editingLocId ?? undefined);
    setLocForm(emptyLoc);
    setEditingLocId(null);
  };

  const submitRel = () => {
    if (!relForm.source_location || !relForm.target_location || relForm.source_location === relForm.target_location) return;
    onRelAdd(relForm);
    setRelForm(emptyRel);
  };

  return (
    <section className="space-y-3">
      <h4 className="flex items-center gap-1.5 text-xs font-semibold uppercase tracking-wide text-muted">
        <MapPinned size={12} aria-hidden="true" />
        地点管理
      </h4>

      {loading && (
        <div className="flex items-center gap-2 text-[11px] text-muted">
          <Loader2 size={12} className="animate-spin motion-reduce:animate-none" aria-hidden="true" />
          加载地点数据...
        </div>
      )}

      {/* 地点表单 */}
      <div className="space-y-2 rounded-lg border border-border bg-surface-elevated p-2.5">
        <div className="flex items-center justify-between">
          <span className="text-[11px] font-medium text-foreground">{editingLocId ? "编辑地点" : "新增地点"}</span>
          {editingLocId !== null && (
            <DFIconButton
              type="button"
              onClick={() => {
                setEditingLocId(null);
                setLocForm(emptyLoc);
              }}
              className="min-h-0 min-w-0 text-[10px] text-muted hover:bg-transparent hover:text-foreground"
            >
              取消编辑
            </DFIconButton>
          )}
        </div>
        <Input
          placeholder="地点名称"
          value={locForm.name}
          onChange={(e) => setLocForm({ ...locForm, name: e.target.value })}
          className="h-8 text-xs"
        />
        <div className="grid grid-cols-2 gap-2">
          <Input
            placeholder="类型（城/山/秘境...）"
            value={locForm.type}
            onChange={(e) => setLocForm({ ...locForm, type: e.target.value })}
            className="h-8 text-xs"
          />
          <Input
            placeholder="上级地点"
            value={locForm.parent_name}
            onChange={(e) => setLocForm({ ...locForm, parent_name: e.target.value })}
            className="h-8 text-xs"
          />
        </div>
        <div className="grid grid-cols-2 gap-2">
          <Select
            value={locForm.tier}
            onChange={(e) => setLocForm({ ...locForm, tier: e.target.value })}
            className="h-8 text-xs"
          >
            <option value="">层级（自动）</option>
            {LOCATION_TIER_OPTIONS.map((o) => (
              <option key={o} value={o}>{o}</option>
            ))}
          </Select>
          <Select
            value={locForm.layer}
            onChange={(e) => setLocForm({ ...locForm, layer: e.target.value })}
            className="h-8 text-xs"
          >
            {LOCATION_LAYER_OPTIONS.map((o) => (
              <option key={o} value={o}>{o}</option>
            ))}
          </Select>
        </div>
        <Select
          value={locForm.importance}
          onChange={(e) => setLocForm({ ...locForm, importance: e.target.value })}
          className="h-8 text-xs"
        >
          {IMPORTANCE_OPTIONS.map((o) => (
            <option key={o} value={o}>{o}</option>
          ))}
        </Select>
        <Textarea
          placeholder="描述"
          value={locForm.description}
          onChange={(e) => setLocForm({ ...locForm, description: e.target.value })}
          className="min-h-[50px] text-xs"
        />
        <Button variant="primary" size="sm" onClick={submitLoc} className="w-full">
          {editingLocId ? "保存修改" : "添加地点"}
        </Button>
      </div>

      {/* 地点列表 */}
      <div className="flex items-center gap-2">
        <Button variant="outline" size="sm" onClick={onAutoClassify} className="flex-1 text-[11px]" disabled={loading}>
          <Wand2 size={11} aria-hidden="true" />
          自动分类
        </Button>
        <Button
          variant="outline"
          size="sm"
          className="flex-1 text-[11px]"
          disabled={loading || validating}
          onClick={async () => {
            setValidating(true);
            try {
              const res = await onValidate();
              setValidateResult(res);
            } finally {
              setValidating(false);
            }
          }}
        >
          <ShieldAlert size={11} aria-hidden="true" />
          {validating ? "校验中..." : "校验层级"}
        </Button>
      </div>
      {validateResult && (
        <div className="space-y-1 rounded-lg border border-border bg-surface-elevated p-2 text-[11px]">
          <div className="flex items-center justify-between text-muted">
            <span>校验结果：{validateResult.total} 个地点</span>
            <span className={validateResult.error_count > 0 ? "text-danger" : "text-muted"}>
              {validateResult.error_count} 错误 · {validateResult.warning_count} 警告
            </span>
          </div>
          {validateResult.issues.length === 0 && <div className="text-primary">✓ 层级结构正常</div>}
          {validateResult.issues.map((iss, i) => (
            <div key={i} className={iss.severity === "error" ? "text-danger" : "text-amber-400"}>
              [{iss.severity === "error" ? "错误" : "警告"}] {iss.location}：{iss.detail}
            </div>
          ))}
        </div>
      )}
      <ul className="space-y-1">
        {locations.length === 0 && !loading && (
          <li className="px-1 text-[11px] text-muted">暂无地点</li>
        )}
        {locations.map((l) => (
          <li
            key={l.id}
            className="flex items-center gap-2 rounded-md border border-border bg-surface-elevated px-2.5 py-1.5"
          >
            <MapPin size={12} className="shrink-0 text-red-400" aria-hidden="true" />
            <div className="min-w-0 flex-1">
              <div className="truncate text-xs text-foreground">{l.name}</div>
              <div className="truncate text-[10px] text-muted">
                {[l.type, l.tier, l.layer, l.parent_name, l.importance].filter(Boolean).join(" · ")}
              </div>
            </div>
            <DFIconButton
              type="button"
              onClick={() => startEdit(l)}
              aria-label={`编辑 ${l.name}`}
              className="flex min-h-[24px] min-w-[24px] cursor-pointer items-center justify-center rounded text-muted hover:bg-transparent hover:text-foreground"
            >
              <Pencil size={11} aria-hidden="true" />
            </DFIconButton>
            <DFIconButton
              type="button"
              onClick={() => onLocationDelete(l.id)}
              aria-label={`删除 ${l.name}`}
              className="flex min-h-[24px] min-w-[24px] cursor-pointer items-center justify-center rounded text-danger hover:bg-danger/10 hover:text-danger"
            >
              <Trash2 size={11} aria-hidden="true" />
            </DFIconButton>
          </li>
        ))}
      </ul>

      {/* 关系表单 */}
      <div className="space-y-2 rounded-lg border border-border bg-surface-elevated p-2.5">
        <span className="text-[11px] font-medium text-foreground">新增地点关系</span>
        <div className="grid grid-cols-2 gap-2">
          <Select
            value={relForm.source_location}
            onChange={(e) => setRelForm({ ...relForm, source_location: e.target.value })}
            className="h-8 text-xs"
          >
            <option value="">起点地点</option>
            {locations.map((l) => (
              <option key={l.id} value={l.name}>{l.name}</option>
            ))}
          </Select>
          <Select
            value={relForm.target_location}
            onChange={(e) => setRelForm({ ...relForm, target_location: e.target.value })}
            className="h-8 text-xs"
          >
            <option value="">终点地点</option>
            {locations.map((l) => (
              <option key={l.id} value={l.name}>{l.name}</option>
            ))}
          </Select>
        </div>
        <div className="grid grid-cols-2 gap-2">
          <Input
            placeholder="关系类型（相邻/包含/通道）"
            value={relForm.relation_type}
            onChange={(e) => setRelForm({ ...relForm, relation_type: e.target.value })}
            className="h-8 text-xs"
          />
          <Input
            type="number"
            placeholder="距离"
            value={relForm.distance ?? ""}
            onChange={(e) => setRelForm({ ...relForm, distance: e.target.value === "" ? null : Number(e.target.value) })}
            className="h-8 text-xs"
          />
        </div>
        <Input
          placeholder="关系描述"
          value={relForm.description}
          onChange={(e) => setRelForm({ ...relForm, description: e.target.value })}
          className="h-8 text-xs"
        />
        <Button variant="default" size="sm" onClick={submitRel} className="w-full">
          添加关系
        </Button>
      </div>

      {/* 关系列表 */}
      <ul className="space-y-1">
        {locationRels.length === 0 && (
          <li className="px-1 text-[11px] text-muted">暂无地点关系</li>
        )}
        {locationRels.map((r) => (
          <li
            key={r.id}
            className="flex items-center gap-2 rounded-md border border-border bg-surface-elevated px-2.5 py-1.5"
          >
            <Database size={12} className="shrink-0 text-cyan-400" aria-hidden="true" />
            <div className="min-w-0 flex-1 truncate text-[11px] text-foreground">
              <span className="text-cyan-300">{r.source_location}</span>
              <span className="mx-1 text-muted">—{r.relation_type}→</span>
              <span className="text-cyan-300">{r.target_location}</span>
            </div>
            <DFIconButton
              type="button"
              onClick={() => onRelDelete(r.id)}
              aria-label="删除关系"
              className="flex min-h-[24px] min-w-[24px] cursor-pointer items-center justify-center rounded text-danger hover:bg-danger/10 hover:text-danger"
            >
              <Trash2 size={11} aria-hidden="true" />
            </DFIconButton>
          </li>
        ))}
      </ul>
    </section>
  );
}

/** 一键生成预览弹窗 */
function AutoGenPreviewDialog({
  state,
  onClose,
  onConfirm,
}: {
  state: { open: boolean; loading: boolean; data: AutoGenerateResult | null };
  onClose: () => void;
  onConfirm: () => void;
}) {
  const { open, loading, data } = state;
  return (
    <Dialog open={open} onOpenChange={(o) => !o && onClose()}>
      <DialogContent>
        <DialogHeader>
          <DialogTitle className="flex items-center gap-2">
            <Sparkles size={16} className="text-cyan-400" aria-hidden="true" />
            一键生成预览
          </DialogTitle>
        </DialogHeader>

        {loading && (
          <div className="flex flex-col items-center gap-3 py-8 text-muted" role="status">
            <Loader2 size={24} className="animate-spin text-cyan-400 motion-reduce:animate-none" aria-hidden="true" />
            <span className="text-sm">正在根据设定生成图谱...</span>
          </div>
        )}

        {!loading && data && (
          <div className="space-y-4">
            <div className="space-y-2">
              <div className="flex items-center gap-2">
                <span className="text-sm font-semibold text-foreground">{data.name}</span>
                <Badge variant={GRAPH_TYPE_BADGE[data.graph_type]?.variant ?? "default"}>
                  {GRAPH_TYPE_LABEL[data.graph_type]}
                </Badge>
              </div>
              {data.description && (
                <p className="text-xs leading-relaxed text-muted">{data.description}</p>
              )}
              <div className="flex gap-4 text-xs text-muted">
                <span>节点：<span className="font-mono text-foreground">{data.graph_data.nodes.length}</span></span>
                <span>关系：<span className="font-mono text-foreground">{data.graph_data.edges.length}</span></span>
              </div>
            </div>

            <div className="flex justify-end gap-2 border-t border-border pt-3">
              <Button variant="ghost" size="sm" onClick={onClose}>
                放弃
              </Button>
              <Button variant="primary" size="sm" onClick={onConfirm}>
                <Save size={14} aria-hidden="true" />
                保存为新图谱
              </Button>
            </div>
          </div>
        )}
      </DialogContent>
    </Dialog>
  );
}

/** 新建空白图谱弹窗 */
function NewGraphDialog({
  open,
  onClose,
  onSubmit,
}: {
  open: boolean;
  onClose: () => void;
  onSubmit: (input: { name: string; graph_type: GraphType; description: string }) => void;
}) {
  const [name, setName] = useState("");
  const [graphType, setGraphType] = useState<GraphType>("characters");
  const [description, setDescription] = useState("");

  useEffect(() => {
    if (open) {
      setName("");
      setGraphType("characters");
      setDescription("");
    }
  }, [open]);

  const handleSubmit = () => {
    if (!name.trim()) return;
    onSubmit({ name: name.trim(), graph_type: graphType, description: description.trim() });
  };

  return (
    <Dialog open={open} onOpenChange={(o) => !o && onClose()}>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>新建空白图谱</DialogTitle>
        </DialogHeader>

        <div className="space-y-3">
          <div className="space-y-1">
            <Label htmlFor="new-graph-name">名称</Label>
            <Input
              id="new-graph-name"
              placeholder="如：主角阵营关系图"
              value={name}
              onChange={(e) => setName(e.target.value)}
            />
          </div>

          <div className="space-y-1">
            <Label htmlFor="new-graph-type">类型</Label>
            <Select id="new-graph-type" value={graphType} onChange={(e) => setGraphType(e.target.value as GraphType)}>
              <option value="characters">人物关系图</option>
              <option value="factions">势力关系图</option>
              <option value="foreshadows">伏笔网络图</option>
              <option value="chapters">章节脉络图</option>
              <option value="map">世界地图</option>
              <option value="custom">自定义图谱</option>
            </Select>
          </div>

          <div className="space-y-1">
            <Label htmlFor="new-graph-desc">描述（可选）</Label>
            <Textarea
              id="new-graph-desc"
              placeholder="图谱用途说明..."
              value={description}
              onChange={(e) => setDescription(e.target.value)}
              className="min-h-[70px]"
            />
          </div>

          <div className="flex justify-end gap-2 border-t border-border pt-3">
            <Button variant="ghost" size="sm" onClick={onClose}>
              取消
            </Button>
            <Button variant="primary" size="sm" onClick={handleSubmit} disabled={!name.trim()}>
              创建
            </Button>
          </div>
        </div>
      </DialogContent>
    </Dialog>
  );
}

/** 删除确认弹窗 */
function DeleteConfirmDialog({
  open,
  graphName,
  onClose,
  onConfirm,
}: {
  open: boolean;
  graphName: string;
  onClose: () => void;
  onConfirm: () => void;
}) {
  return (
    <Dialog open={open} onOpenChange={(o) => !o && onClose()}>
      <DialogContent className="max-w-md">
        <DialogHeader>
          <DialogTitle className="flex items-center gap-2 text-danger">
            <AlertTriangle size={16} aria-hidden="true" />
            删除图谱
          </DialogTitle>
        </DialogHeader>

        <div className="space-y-4">
          <p className="text-sm text-muted">
            确定删除图谱「<span className="font-medium text-foreground">{graphName}</span>」吗？此操作不可撤销。
          </p>

          <div className="flex justify-end gap-2 border-t border-border pt-3">
            <Button variant="ghost" size="sm" onClick={onClose}>
              取消
            </Button>
            <Button variant="danger" size="sm" onClick={onConfirm}>
              <Trash2 size={14} aria-hidden="true" />
              确认删除
            </Button>
          </div>
        </div>
      </DialogContent>
    </Dialog>
  );
}
