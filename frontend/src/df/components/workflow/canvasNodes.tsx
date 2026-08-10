/** 工作流只读画布的自定义节点：业务节点 / 网关节点（菱形）/ 起止圆点 */
import { Handle, Position, type NodeProps } from "reactflow";
import { cn } from "@/lib/utils";
import type { FlowNodeData, GatewayNodeData } from "./graph";

/** 节点状态样式：pending=muted / running=indigo-400+脉冲 / ok=green-400 / failed=red-400 */
const STATUS_BORDER: Record<string, string> = {
  pending: "border-border-strong/70",
  running: "border-indigo-400 glow-border status-running",
  ok: "border-green-400/80",
  failed: "border-red-400/80",
};

const STATUS_DOT: Record<string, string> = {
  pending: "bg-border-strong",
  running: "bg-indigo-400 status-running",
  ok: "bg-green-400",
  failed: "bg-red-400",
};

/** 业务节点：agent=indigo 色系徽标 / script=cyan 色系徽标，执行时按状态高亮边框 */
export function DFBusinessNode({ data }: NodeProps<FlowNodeData>) {
  const status = data.status || "pending";
  const isScript = data.nodeType === "script";
  const badgeClass = isScript
    ? "bg-cyan-500/10 text-cyan-400"
    : "bg-indigo-500/10 text-indigo-400";
  return (
    <div
      className={cn(
        "w-[200px] rounded-lg border-2 bg-surface-elevated shadow-lg transition-colors",
        STATUS_BORDER[status] || STATUS_BORDER.pending,
      )}
      role="article"
      aria-label={`工作流节点 ${data.label}`}
    >
      <Handle
        type="target"
        position={Position.Top}
        className="!h-2 !w-2 !border-2 !border-background !bg-muted"
      />
      <div className="flex items-center justify-between gap-2 px-3 pt-2">
        <span
          className={cn(
            "max-w-[150px] truncate rounded px-1.5 py-0.5 text-[10px] font-medium uppercase tracking-wider",
            badgeClass,
          )}
        >
          {isScript ? "脚本" : data.agentType || "agent"}
        </span>
        <span
          className={cn("h-2 w-2 shrink-0 rounded-full", STATUS_DOT[status] || STATUS_DOT.pending)}
          aria-hidden="true"
        />
      </div>
      <div className="truncate px-3 py-2 text-sm font-medium text-foreground" title={data.label}>
        {data.label}
      </div>
      {typeof data.elapsed === "number" && (
        <div className="px-3 pb-2 text-[10px] text-muted">耗时 {data.elapsed}s</div>
      )}
      {status === "failed" && data.error && (
        <div className="truncate px-3 pb-2 text-[10px] text-red-400" title={data.error}>
          {data.error}
        </div>
      )}
      <Handle
        type="source"
        position={Position.Bottom}
        className="!h-2 !w-2 !border-2 !border-background !bg-muted"
      />
    </div>
  );
}

/** 网关颜色：condition=amber / parallel、converge=purple / loop=green */
const GATEWAY_COLOR: Record<string, string> = {
  condition: "#f59e0b",
  parallel: "#a855f7",
  converge: "#a855f7",
  loop: "#22c55e",
};

/** 网关节点（菱形），运行中叠加脉冲与辉光 */
export function DFGatewayNode({ data }: NodeProps<GatewayNodeData>) {
  const color = GATEWAY_COLOR[data.gatewayType] || "#a855f7";
  const status = data.status || "pending";
  const running = status === "running";
  // 完成/失败时菱形边框切换为状态色，否则用网关类型色
  const borderColor = status === "ok" ? "#4ade80" : status === "failed" ? "#f87171" : color;
  return (
    <div
      className={cn(
        "relative flex h-14 w-14 rotate-45 items-center justify-center rounded-md border-2 bg-background shadow-lg transition-colors",
        running && "glow-border status-running",
      )}
      style={{ borderColor, boxShadow: running ? undefined : `0 0 8px ${color}30` }}
      role="img"
      aria-label={`网关节点 ${data.label}`}
    >
      <Handle
        type="target"
        position={Position.Top}
        className="!h-1.5 !w-1.5 !border !border-background !bg-muted"
      />
      <span className="-rotate-45 text-[10px] font-bold" style={{ color: borderColor }}>
        {data.label}
      </span>
      <Handle
        type="source"
        position={Position.Bottom}
        className="!h-1.5 !w-1.5 !border !border-background !bg-muted"
      />
    </div>
  );
}

/** 开始圆点（仅出边） */
export function DFStartNode() {
  return (
    <div className="flex flex-col items-center gap-1" role="img" aria-label="开始节点">
      <div className="h-3.5 w-3.5 rounded-full bg-green-400 shadow-[0_0_8px_rgba(34,197,94,0.5)]" />
      <span className="text-[10px] text-muted">开始</span>
      <Handle
        type="source"
        position={Position.Bottom}
        className="!h-2 !w-2 !border-0 !bg-transparent"
      />
    </div>
  );
}

/** 结束圆点（仅入边） */
export function DFEndNode() {
  return (
    <div className="flex flex-col items-center gap-1" role="img" aria-label="结束节点">
      <Handle
        type="target"
        position={Position.Top}
        className="!h-2 !w-2 !border-0 !bg-transparent"
      />
      <div className="h-3.5 w-3.5 rounded-full bg-red-400 shadow-[0_0_8px_rgba(239,68,68,0.5)]" />
      <span className="text-[10px] text-muted">结束</span>
    </div>
  );
}
