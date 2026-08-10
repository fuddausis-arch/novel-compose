/** 右侧执行面板：变量表单 + agent_role 选择 + 运行/停止 + 执行日志 + 节点历史 */
import { useEffect, useMemo, useRef, useState } from "react";
import { CircleStop, Play } from "lucide-react";
import { Badge } from "@/components/ui/badge";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Separator } from "@/components/ui/separator";
import { Textarea } from "@/components/ui/textarea";
import { cn } from "@/lib/utils";
import type {
  NodeRunRecord,
  WorkflowDefinition,
  WorkflowLogEntry,
} from "./types";

/**
 * agent_role 可选项（对齐后端 config.ROLE_PARAMS 的温度光谱角色，
 * writer 为后端 RunRequest 的默认值）。
 */
const AGENT_ROLES = [
  { value: "writer", label: "writer（创作 · 默认）" },
  { value: "planner", label: "planner（规划）" },
  { value: "outliner", label: "outliner（大纲）" },
  { value: "architect", label: "architect（架构）" },
  { value: "polisher", label: "polisher（润色）" },
  { value: "auditor", label: "auditor（审核）" },
  { value: "world_engine", label: "world_engine（世界观）" },
  { value: "summarizer", label: "summarizer（摘要）" },
  { value: "debater", label: "debater（辩论）" },
  { value: "context_trimmer", label: "context_trimmer（上下文裁剪）" },
  { value: "post_hoc", label: "post_hoc（事后校验）" },
];

/** 日志条目类型对应的左侧标记颜色 */
const LOG_KIND_CLASS: Record<WorkflowLogEntry["kind"], string> = {
  start: "text-indigo-400",
  done: "text-green-400",
  failed: "text-red-400",
  info: "text-muted",
  error: "text-red-400",
};

const LOG_KIND_LABEL: Record<WorkflowLogEntry["kind"], string> = {
  start: "开始",
  done: "完成",
  failed: "失败",
  info: "信息",
  error: "错误",
};

interface WorkflowRunPanelProps {
  definition: WorkflowDefinition;
  running: boolean;
  logs: WorkflowLogEntry[];
  /** 工作流终态：completed / failed / aborted，null=未结束 */
  workflowStatus: string | null;
  nodeRuns: NodeRunRecord[] | null;
  /** 当前项目名，null 表示尚未在小说创作界面选择项目 */
  projectName: string | null;
  onRun: (inputs: Record<string, string>, agentRole: string) => void;
  onStop: () => void;
}

export default function WorkflowRunPanel({
  definition,
  running,
  logs,
  workflowStatus,
  nodeRuns,
  projectName,
  onRun,
  onStop,
}: WorkflowRunPanelProps) {
  // 表单变量：隐藏变量（内部产物）与 output 变量不需要用户填写
  const visibleVars = useMemo(
    () => (definition.variables || []).filter((v) => !v.hidden && v.source_type !== "output"),
    [definition],
  );

  const [values, setValues] = useState<Record<string, string>>({});
  const [agentRole, setAgentRole] = useState("writer");
  const [formError, setFormError] = useState<string | null>(null);

  // 切换工作流定义时按变量默认值重置表单
  useEffect(() => {
    const initial: Record<string, string> = {};
    for (const v of visibleVars) initial[v.key] = v.default || "";
    setValues(initial);
    setFormError(null);
  }, [visibleVars]);

  // 日志区自动滚动到底部
  const logBoxRef = useRef<HTMLDivElement>(null);
  useEffect(() => {
    const el = logBoxRef.current;
    if (el) el.scrollTop = el.scrollHeight;
  }, [logs, workflowStatus]);

  // 节点 id → 展示名（node_runs 历史用）
  const nodeLabel = useMemo(() => {
    const map = new Map<string, string>();
    for (const n of definition.nodes || []) map.set(n.id, n.label || n.id);
    return map;
  }, [definition]);

  const handleRun = () => {
    const missing = visibleVars.filter((v) => v.required && !(values[v.key] || "").trim());
    if (missing.length > 0) {
      setFormError(`请填写必填项：${missing.map((v) => v.name || v.key).join("、")}`);
      return;
    }
    setFormError(null);
    onRun(values, agentRole);
  };

  return (
    <aside
      className="flex w-80 shrink-0 flex-col border-l border-border bg-surface"
      aria-label="工作流执行面板"
    >
      {/* 面板头：工作流名 + 版本 + 终态徽标 */}
      <div className="flex h-12 shrink-0 items-center gap-2 border-b border-border px-4">
        <h2 className="min-w-0 flex-1 truncate text-sm font-semibold text-foreground">
          {definition.name}
        </h2>
        <span className="shrink-0 text-xs text-muted">v{definition.version}</span>
        {workflowStatus === "completed" && <Badge variant="success">执行完成</Badge>}
        {workflowStatus === "failed" && <Badge variant="danger">执行失败</Badge>}
        {workflowStatus === "aborted" && <Badge>已中止</Badge>}
      </div>

      <div className="flex min-h-0 flex-1 flex-col overflow-y-auto">
        {/* 当前项目提示 */}
        <div className="shrink-0 px-4 pt-3">
          {projectName ? (
            <p className="text-xs text-muted">
              当前项目：<span className="text-foreground">{projectName}</span>
            </p>
          ) : (
            <p
              className="rounded-lg border border-amber-500/30 bg-amber-500/10 px-3 py-2 text-xs text-amber-300"
              role="alert"
            >
              未选择项目：请先在小说创作界面创建/打开一个项目，再运行工作流
            </p>
          )}
        </div>

        {/* 变量表单 */}
        <div className="shrink-0 space-y-3 px-4 py-3">
          {visibleVars.length === 0 && (
            <p className="text-xs text-muted">该工作流无需填写变量</p>
          )}
          {visibleVars.map((v) => {
            const inputId = `wf-var-${v.key}`;
            return (
              <div key={v.key} className="space-y-1.5">
                <Label htmlFor={inputId} className="flex items-center gap-1 text-xs">
                  {v.name || v.key}
                  {v.required && (
                    <span className="text-red-400" aria-label="必填项">
                      *
                    </span>
                  )}
                </Label>
                {v.type === "textarea" ? (
                  <Textarea
                    id={inputId}
                    value={values[v.key] ?? ""}
                    onChange={(e) =>
                      setValues((prev) => ({ ...prev, [v.key]: e.target.value }))
                    }
                    placeholder={v.description || undefined}
                    disabled={running}
                    rows={3}
                    className="rounded-lg border-border-strong/60 bg-surface text-xs"
                  />
                ) : (
                  <Input
                    id={inputId}
                    value={values[v.key] ?? ""}
                    onChange={(e) =>
                      setValues((prev) => ({ ...prev, [v.key]: e.target.value }))
                    }
                    placeholder={v.description || undefined}
                    disabled={running}
                    className="h-9 rounded-lg border-border-strong/60 bg-surface text-xs"
                  />
                )}
              </div>
            );
          })}

          {/* agent_role 下拉 */}
          <div className="space-y-1.5">
            <Label htmlFor="wf-agent-role" className="text-xs">
              执行角色（LLM 配置）
            </Label>
            <select
              id="wf-agent-role"
              value={agentRole}
              onChange={(e) => setAgentRole(e.target.value)}
              disabled={running}
              className="h-9 w-full rounded-lg border border-border-strong/60 bg-surface px-2 text-xs text-foreground focus-visible:outline-none"
            >
              {AGENT_ROLES.map((r) => (
                <option key={r.value} value={r.value}>
                  {r.label}
                </option>
              ))}
            </select>
          </div>

          {formError && (
            <p className="text-xs text-red-400" role="alert">
              {formError}
            </p>
          )}

          {/* 运行 / 停止按钮 */}
          {running ? (
            <button
              type="button"
              onClick={onStop}
              className="flex min-h-[44px] w-full cursor-pointer items-center justify-center gap-2 rounded-lg bg-red-500/90 px-4 text-sm font-medium text-white transition-colors hover:bg-red-400"
            >
              <CircleStop size={15} aria-hidden="true" />
              停止
            </button>
          ) : (
            <button
              type="button"
              onClick={handleRun}
              disabled={!projectName}
              title={projectName ? undefined : "请先在小说创作界面选择项目"}
              className="flex min-h-[44px] w-full cursor-pointer items-center justify-center gap-2 rounded-lg bg-purple-500 px-4 text-sm font-medium text-white transition-colors hover:bg-purple-400 disabled:cursor-not-allowed disabled:opacity-40"
            >
              <Play size={15} aria-hidden="true" />
              运行
            </button>
          )}
        </div>

        <Separator className="shrink-0 bg-secondary" />

        {/* 执行日志 */}
        <div className="flex min-h-0 flex-1 flex-col px-4 py-3">
          <h3 className="mb-2 shrink-0 text-xs font-semibold text-foreground">执行日志</h3>
          <div
            ref={logBoxRef}
            className="min-h-[120px] flex-1 space-y-1.5 overflow-y-auto rounded-lg border border-border bg-surface p-2.5"
            aria-live="polite"
          >
            {logs.length === 0 ? (
              <p className="text-[11px] text-muted">点击「运行」后此处显示节点执行进度</p>
            ) : (
              logs.map((log) => (
                <div key={log.id} className="flex items-start gap-2 text-[11px] leading-relaxed">
                  <span className="shrink-0 font-mono text-muted">{log.time}</span>
                  <span className={cn("shrink-0", LOG_KIND_CLASS[log.kind])}>
                    {LOG_KIND_LABEL[log.kind]}
                  </span>
                  <span className="min-w-0 break-words text-foreground">{log.text}</span>
                </div>
              ))
            )}
          </div>
        </div>

        {/* node_runs 节点历史 */}
        {nodeRuns && nodeRuns.length > 0 && (
          <div className="shrink-0 px-4 pb-4">
            <h3 className="mb-2 text-xs font-semibold text-foreground">
              节点历史（{nodeRuns.length}）
            </h3>
            <div className="space-y-1.5">
              {nodeRuns.map((r, i) => (
                <div
                  key={`${r.node_id}-${i}`}
                  className="rounded-lg border border-border bg-surface px-2.5 py-1.5"
                >
                  <div className="flex items-center gap-2 text-[11px]">
                    <span className="min-w-0 flex-1 truncate text-foreground">
                      {nodeLabel.get(r.node_id) || r.node_id}
                    </span>
                    <Badge variant={r.status === "ok" ? "success" : "danger"}>
                      {r.status === "ok" ? "完成" : "失败"}
                    </Badge>
                    <span className="shrink-0 font-mono text-muted">{r.elapsed_s}s</span>
                  </div>
                  {(r.output_preview || r.error) && (
                    <p
                      className="mt-1 truncate text-[10px] text-muted"
                      title={r.error || r.output_preview}
                    >
                      {r.error || r.output_preview}
                    </p>
                  )}
                </div>
              ))}
            </div>
          </div>
        )}
      </div>
    </aside>
  );
}
