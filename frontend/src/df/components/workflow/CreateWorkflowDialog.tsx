/** 新建自定义工作流弹窗
 *
 * 用户填写 workflow_id / name / description，并选择模板：
 * - 空白：初始化为只含 __start__ → __end__ 的最小 workflow_json
 * - 克隆现有：选择一个已有工作流，复制其 workflow_json 作为起点
 *
 * 克隆时按是否自定义分别走两条数据源：
 * - 自定义工作流：GET /api/bible/{pid}/custom-workflows/{wid} 拿原始 workflow_json
 * - 内置工作流：GET /api/workflows/{wid}?project_id={pid} 转 WorkflowDefinition 再转 workflow_json
 */
import { useEffect, useState } from "react";
import { Loader2, Plus } from "lucide-react";
import { Dialog, DialogContent, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Textarea } from "@/components/ui/textarea";
import { Badge } from "@/components/ui/badge";
import { cn } from "@/lib/utils";
import { buildFlowGraph } from "./graph";
import type {
  CustomWorkflowEdge,
  CustomWorkflowNode,
  WorkflowDefinition,
  WorkflowJson,
  WorkflowSummary,
} from "./types";

/** workflow_id 合法字符：英文 + 数字 + 横线 */
const WORKFLOW_ID_PATTERN = /^[a-zA-Z][a-zA-Z0-9-]*$/;

interface CreateWorkflowDialogProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  projectId: number | null;
  /** 项目内全部工作流（用于克隆源选择） */
  workflows: WorkflowSummary[];
  /** 创建回调：返回 workflow_id + name + description + 初始 workflow_json */
  onCreate: (workflowId: string, name: string, description: string, workflowJson: WorkflowJson) => Promise<void> | void;
}

/** 空白模板：仅 __start__ → __end__ 的最小 workflow_json */
function emptyWorkflowJson(name: string): WorkflowJson {
  return {
    name,
    description: undefined,
    nodes: [],
    edges: [{ source: "__start__", target: "__end__" }],
    variables: [],
  };
}

/** WorkflowDefinition（GET /api/workflows/{id}）→ WorkflowJson（保留 BFS 布局位置） */
function definitionToWorkflowJson(def: WorkflowDefinition): WorkflowJson {
  const graph = buildFlowGraph(def);
  const positionOf = (id: string) =>
    graph.nodes.find((n) => n.id === id)?.position ?? { x: 0, y: 0 };

  const nodes: CustomWorkflowNode[] = (def.nodes || []).map((n) => ({
    id: n.id,
    node_type: (n.node_type === "script" ? "script" : "agent") as "agent" | "script",
    agent_type: n.agent_type,
    label: n.label || n.id,
    position: positionOf(n.id),
  }));

  const edges: CustomWorkflowEdge[] = (def.edges || []).map((e) => ({
    source: e.source,
    target: e.target,
  }));

  return {
    name: def.name,
    description: undefined,
    nodes,
    edges,
    variables: def.variables || [],
  };
}

export function CreateWorkflowDialog({
  open,
  onOpenChange,
  projectId,
  workflows,
  onCreate,
}: CreateWorkflowDialogProps) {
  const [workflowId, setWorkflowId] = useState("");
  const [name, setName] = useState("");
  const [description, setDescription] = useState("");
  /** 模板：blank=空白，clone=克隆现有 */
  const [templateMode, setTemplateMode] = useState<"blank" | "clone">("blank");
  /** 克隆源 workflow_id */
  const [cloneSourceId, setCloneSourceId] = useState<string>("");
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  // 打开时重置表单
  useEffect(() => {
    if (!open) return;
    setWorkflowId("");
    setName("");
    setDescription("");
    setTemplateMode("blank");
    setCloneSourceId("");
    setError(null);
    setSubmitting(false);
  }, [open]);

  // 检查 workflow_id 是否已被占用
  const idConflict = workflows.some((w) => w.workflow_id === workflowId.trim());
  const idValid = WORKFLOW_ID_PATTERN.test(workflowId.trim()) && !idConflict;

  const canSubmit =
    !submitting &&
    idValid &&
    name.trim().length > 0 &&
    (templateMode === "blank" || cloneSourceId.length > 0);

  /** 解析克隆源 workflow_json：自定义走 custom-workflows API，内置走 workflows API + 转换 */
  const fetchCloneSourceJson = async (sourceId: string): Promise<WorkflowJson> => {
    if (!projectId) throw new Error("项目尚未加载");
    const source = workflows.find((w) => w.workflow_id === sourceId);
    if (!source) throw new Error("克隆源不存在");

    if (source.is_custom) {
      // 自定义工作流：直接拿原始 workflow_json（保留 first_message 等所有字段）
      const res = await fetch(
        `/api/bible/${projectId}/custom-workflows/${encodeURIComponent(sourceId)}`,
      );
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      const record = await res.json();
      return record.workflow_json as WorkflowJson;
    }

    // 内置工作流：转 WorkflowDefinition → WorkflowJson（缺失 first_message 等编辑器字段）
    const res = await fetch(
      `/api/workflows/${encodeURIComponent(sourceId)}?project_id=${projectId}`,
    );
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    const def = (await res.json()) as WorkflowDefinition;
    return definitionToWorkflowJson(def);
  };

  const handleSubmit = async () => {
    if (!canSubmit) return;
    setError(null);
    setSubmitting(true);
    try {
      let json: WorkflowJson;
      if (templateMode === "blank") {
        json = emptyWorkflowJson(name.trim());
      } else {
        json = await fetchCloneSourceJson(cloneSourceId);
        // 用用户填写的 name/description 覆盖克隆源的元信息
        json = { ...json, name: name.trim(), description: description.trim() || undefined };
      }
      await onCreate(workflowId.trim(), name.trim(), description.trim(), json);
      onOpenChange(false);
    } catch (e) {
      const msg = e instanceof Error ? e.message : String(e);
      setError(`创建失败：${msg}`);
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="max-w-md">
        <DialogHeader>
          <DialogTitle>新建自定义工作流</DialogTitle>
        </DialogHeader>

        <div className="mt-2 space-y-3">
          {/* workflow_id */}
          <div className="space-y-1">
            <Label htmlFor="cw-id" className="text-xs">
              workflow_id <span className="text-red-400">*</span>
            </Label>
            <Input
              id="cw-id"
              value={workflowId}
              onChange={(e) => setWorkflowId(e.target.value)}
              placeholder="英文/数字/横线，如 my-workflow-1"
              className="h-9 font-mono text-xs"
              disabled={submitting}
            />
            {workflowId.length > 0 && !WORKFLOW_ID_PATTERN.test(workflowId.trim()) && (
              <p className="text-[10px] text-red-400">仅允许英文+数字+横线，且以字母开头</p>
            )}
            {idConflict && (
              <p className="text-[10px] text-red-400">该 ID 已被占用，请换一个</p>
            )}
          </div>

          {/* name */}
          <div className="space-y-1">
            <Label htmlFor="cw-name" className="text-xs">
              名称 <span className="text-red-400">*</span>
            </Label>
            <Input
              id="cw-name"
              value={name}
              onChange={(e) => setName(e.target.value)}
              placeholder="如 我的创作工作流"
              className="h-9 text-xs"
              disabled={submitting}
            />
          </div>

          {/* description */}
          <div className="space-y-1">
            <Label htmlFor="cw-desc" className="text-xs">
              描述（可选）
            </Label>
            <Textarea
              id="cw-desc"
              value={description}
              onChange={(e) => setDescription(e.target.value)}
              placeholder="工作流用途说明"
              rows={2}
              className="text-xs"
              disabled={submitting}
            />
          </div>

          {/* 模板选择 */}
          <div className="space-y-1.5">
            <Label className="text-xs">模板</Label>
            <div className="grid grid-cols-2 gap-2">
              <button
                type="button"
                onClick={() => setTemplateMode("blank")}
                disabled={submitting}
                className={cn(
                  "rounded-lg border px-3 py-2 text-left text-xs transition-colors",
                  templateMode === "blank"
                    ? "border-purple-500/60 bg-purple-500/10 text-foreground"
                    : "border-border bg-surface text-muted hover:border-purple-500/40",
                )}
              >
                <div className="font-medium">空白</div>
                <div className="text-[10px] text-muted">仅起始 → 结束</div>
              </button>
              <button
                type="button"
                onClick={() => setTemplateMode("clone")}
                disabled={submitting}
                className={cn(
                  "rounded-lg border px-3 py-2 text-left text-xs transition-colors",
                  templateMode === "clone"
                    ? "border-purple-500/60 bg-purple-500/10 text-foreground"
                    : "border-border bg-surface text-muted hover:border-purple-500/40",
                )}
              >
                <div className="font-medium">克隆现有</div>
                <div className="text-[10px] text-muted">复制已有工作流</div>
              </button>
            </div>
          </div>

          {/* 克隆源选择 */}
          {templateMode === "clone" && (
            <div className="space-y-1">
              <Label htmlFor="cw-clone-source" className="text-xs">
                选择克隆源 <span className="text-red-400">*</span>
              </Label>
              <select
                id="cw-clone-source"
                value={cloneSourceId}
                onChange={(e) => setCloneSourceId(e.target.value)}
                disabled={submitting}
                className="h-9 w-full rounded-lg border border-border-strong/60 bg-surface px-2 text-xs text-foreground focus-visible:outline-none"
              >
                <option value="">请选择...</option>
                {workflows.map((w) => (
                  <option key={w.workflow_id} value={w.workflow_id}>
                    {w.name}
                    {w.is_custom ? "（自定义）" : "（内置）"} · {w.workflow_id}
                  </option>
                ))}
              </select>
              <p className="text-[10px] text-muted">
                克隆自定义工作流会保留全部 prompt；克隆内置工作流仅复制结构（first_message 等需后续补充）
              </p>
            </div>
          )}

          {/* 错误提示 */}
          {error && (
            <p className="rounded-lg border border-red-500/30 bg-red-500/10 px-3 py-2 text-xs text-red-400" role="alert">
              {error}
            </p>
          )}

          {/* 已有工作流徽章预览 */}
          <div className="rounded-lg border border-border bg-surface-elevated px-3 py-2">
            <div className="mb-1 text-[10px] text-muted">已有工作流（{workflows.length}）</div>
            <div className="flex flex-wrap gap-1">
              {workflows.slice(0, 6).map((w) => (
                <Badge key={w.workflow_id} variant={w.is_custom ? "primary" : "default"} className="text-[10px]">
                  {w.is_custom ? "自定义" : "内置"} {w.name}
                </Badge>
              ))}
              {workflows.length > 6 && (
                <span className="text-[10px] text-muted">+{workflows.length - 6}</span>
              )}
            </div>
          </div>

          {/* 操作按钮 */}
          <div className="flex justify-end gap-2 pt-2">
            <Button variant="ghost" size="sm" onClick={() => onOpenChange(false)} disabled={submitting}>
              取消
            </Button>
            <Button variant="primary" size="sm" onClick={handleSubmit} disabled={!canSubmit}>
              {submitting ? (
                <Loader2 size={13} className="animate-spin motion-reduce:animate-none" aria-hidden="true" />
              ) : (
                <Plus size={13} aria-hidden="true" />
              )}
              创建
            </Button>
          </div>
        </div>
      </DialogContent>
    </Dialog>
  );
}
