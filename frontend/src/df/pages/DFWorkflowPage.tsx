/** 工作流页（项目内路由 /projects/:projectId/workflow）
 *
 * 三栏布局：左侧工作流列表 / 中间 ReactFlow 画布 / 右侧执行面板。
 * 后端为只读定义 + SSE 流式执行（POST /api/workflows/{id}/run）。
 *
 * 自定义工作流支持：
 * - 「新建工作流」按钮 → 弹窗填写 workflow_id/name/description，选空白或克隆模板
 * - 「编辑模式」切换（仅自定义工作流可用）→ 中间画布切换为可编辑 ReactFlow
 *   右侧从执行面板切换为节点编辑面板（节点工具箱/节点表单/变量编辑器）
 * - 「保存」按钮 → PUT /api/bible/{pid}/custom-workflows/{wid}
 * - 「删除」按钮 → DELETE /api/bible/{pid}/custom-workflows/{wid}（二次确认）
 */
import { useCallback, useEffect, useRef, useState } from "react";
import {
  Edit3,
  Eye,
  Loader2,
  Menu,
  Play,
  Plus,
  Trash2,
  X,
} from "lucide-react";
import { AppLayout } from "@/components/layout/AppLayout";
import { useCurrentProject } from "@/hooks/useCurrentProject";
import { useToast } from "@/hooks/useToast";
import { useConfirmDialog } from "@/hooks/useConfirmDialog";
import { useMediaQuery } from "@/hooks/useMediaQuery";
import { Button } from "@/components/ui/button";
import { cn } from "@/lib/utils";
import { DF_BRAND_MARK_DARK } from "../brand";
import { DFIconButton } from "../components/admin/df-ui";
import WorkflowCanvas from "../components/workflow/WorkflowCanvas";
import WorkflowEditor from "../components/workflow/WorkflowEditor";
import WorkflowListPanel from "../components/workflow/WorkflowListPanel";
import WorkflowRunPanel from "../components/workflow/WorkflowRunPanel";
import { CreateWorkflowDialog } from "../components/workflow/CreateWorkflowDialog";
import type {
  CustomWorkflowRecord,
  NodeRunInfo,
  NodeRunRecord,
  WorkflowDefinition,
  WorkflowJson,
  WorkflowLogEntry,
  WorkflowSummary,
} from "../components/workflow/types";

/** 日志时间戳（HH:MM:SS） */
function nowTime(): string {
  return new Date().toLocaleTimeString("zh-CN", { hour12: false });
}

// 日志条目自增 id（模块级，避免 key 重复）
let logSeq = 0;

type EditorMode = "view" | "edit";

export default function DFWorkflowPage() {
  // 项目来自路由参数（useCurrentProject 负责加载到 store）
  const { projectId, project } = useCurrentProject();
  const { showSuccess, showError } = useToast();
  const { confirm: confirmDelete, dialog: deleteDialog } = useConfirmDialog();

  const [workflows, setWorkflows] = useState<WorkflowSummary[]>([]);
  const [listLoading, setListLoading] = useState(true);
  const [listError, setListError] = useState<string | null>(null);

  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [definition, setDefinition] = useState<WorkflowDefinition | null>(null);
  const [defLoading, setDefLoading] = useState(false);

  /** 当前选中工作流是否自定义（由列表项 is_custom 决定；切换工作流时同步重置） */
  const [selectedIsCustom, setSelectedIsCustom] = useState(false);

  /** 视图模式：view=只读画布+执行面板；edit=可编辑画布+节点编辑面板 */
  const [editorMode, setEditorMode] = useState<EditorMode>("view");

  /** 编辑器初始化用的 workflow_json（进入编辑模式前由 GET /custom-workflows/{id} 拉取） */
  const [editorInitialJson, setEditorInitialJson] = useState<WorkflowJson | null>(null);
  const [editorLoading, setEditorLoading] = useState(false);
  const [editorSaving, setEditorSaving] = useState(false);

  /** 控制新建工作流弹窗 */
  const [showCreateDialog, setShowCreateDialog] = useState(false);

  // 移动端（<768px）：工作流列表 / 运行面板改为抽屉，避免固定宽侧栏挤压画布
  const isMobile = useMediaQuery("(max-width: 767px)");
  const [listOpen, setListOpen] = useState(false);
  const [runOpen, setRunOpen] = useState(false);

  // SSE 执行状态
  const [running, setRunning] = useState(false);
  const [nodeStatuses, setNodeStatuses] = useState<Record<string, NodeRunInfo>>({});
  const [logs, setLogs] = useState<WorkflowLogEntry[]>([]);
  const [workflowStatus, setWorkflowStatus] = useState<string | null>(null);
  const [nodeRuns, setNodeRuns] = useState<NodeRunRecord[] | null>(null);
  const abortRef = useRef<AbortController | null>(null);
  // 定义请求序号：快速切换工作流时丢弃过期响应
  const defReqRef = useRef(0);

  const appendLog = useCallback((kind: WorkflowLogEntry["kind"], text: string) => {
    setLogs((prev) => [...prev, { id: ++logSeq, time: nowTime(), kind, text }]);
  }, []);

  /** 刷新工作流列表（首次加载 + 创建/删除后调用） */
  const refreshList = useCallback(() => {
    setListLoading(true);
    const url = projectId
      ? `/api/workflows?project_id=${projectId}`
      : "/api/workflows";
    fetch(url)
      .then((res) => {
        if (!res.ok) throw new Error(`HTTP ${res.status}`);
        return res.json();
      })
      .then((data) => {
        setWorkflows(data.workflows || []);
      })
      .catch(() => {
        setListError("工作流列表加载失败，请确认后端已启动");
      })
      .finally(() => {
        setListLoading(false);
      });
  }, [projectId]);

  // 加载工作流列表（依赖 projectId：登录后/切换项目时重拉，确保拿到自定义工作流）
  useEffect(() => {
    refreshList();
  }, [refreshList]);

  // 中止进行中的执行（停止按钮 / 切换工作流 / 页面卸载）
  const abortRun = useCallback(() => {
    abortRef.current?.abort();
    abortRef.current = null;
  }, []);
  useEffect(() => abortRun, [abortRun]);

  /** 选择工作流：拉取完整定义并重置执行状态；若处于编辑模式则退出 */
  const handleSelect = useCallback(
    (id: string) => {
      if (id === selectedId) return;
      abortRun();
      setSelectedId(id);
      setDefinition(null);
      setRunning(false);
      setNodeStatuses({});
      setLogs([]);
      setWorkflowStatus(null);
      setNodeRuns(null);
      setEditorMode("view");
      setEditorInitialJson(null);

      // 同步 is_custom 标记
      const wf = workflows.find((w) => w.workflow_id === id);
      setSelectedIsCustom(Boolean(wf?.is_custom));

      setDefLoading(true);
      const reqId = ++defReqRef.current;
      const defUrl = projectId
        ? `/api/workflows/${encodeURIComponent(id)}?project_id=${projectId}`
        : `/api/workflows/${encodeURIComponent(id)}`;
      fetch(defUrl)
        .then((res) => {
          if (!res.ok) throw new Error(`HTTP ${res.status}`);
          return res.json();
        })
        .then((data: WorkflowDefinition) => {
          if (defReqRef.current === reqId) setDefinition(data);
        })
        .catch(() => {
          if (defReqRef.current === reqId) appendLog("error", "工作流定义加载失败");
        })
        .finally(() => {
          if (defReqRef.current === reqId) setDefLoading(false);
        });
    },
    [selectedId, abortRun, appendLog, projectId, workflows],
  );

  /** 进入编辑模式：先从 /api/bible/{pid}/custom-workflows/{wid} 拉取完整 workflow_json */
  const handleEnterEdit = useCallback(async () => {
    if (!selectedId || !projectId || !selectedIsCustom) return;
    setEditorLoading(true);
    setEditorMode("edit");
    try {
      const res = await fetch(
        `/api/bible/${projectId}/custom-workflows/${encodeURIComponent(selectedId)}`,
      );
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      const record = (await res.json()) as CustomWorkflowRecord;
      setEditorInitialJson(record.workflow_json);
    } catch (e) {
      const msg = e instanceof Error ? e.message : String(e);
      showError(`加载工作流 JSON 失败：${msg}`);
      setEditorMode("view");
      setEditorInitialJson(null);
    } finally {
      setEditorLoading(false);
    }
  }, [selectedId, projectId, selectedIsCustom, showError]);

  /** 退出编辑模式（不保存）：回到只读视图，并重新拉取定义以反映最新状态 */
  const handleExitEdit = useCallback(() => {
    setEditorMode("view");
    setEditorInitialJson(null);
    if (selectedId) {
      // 重新拉取定义（用户可能修改了节点但未保存，恢复到服务器状态）
      const defUrl = projectId
        ? `/api/workflows/${encodeURIComponent(selectedId)}?project_id=${projectId}`
        : `/api/workflows/${encodeURIComponent(selectedId)}`;
      fetch(defUrl)
        .then((res) => (res.ok ? res.json() : Promise.reject(new Error(`HTTP ${res.status}`))))
        .then((data: WorkflowDefinition) => setDefinition(data))
        .catch(() => {
          /* 静默失败：保持原定义 */
        });
    }
  }, [selectedId, projectId]);

  /** 保存编辑器内容：PUT /api/bible/{pid}/custom-workflows/{wid} */
  const handleSaveWorkflow = useCallback(
    async (json: WorkflowJson) => {
      if (!selectedId || !projectId) return;
      setEditorSaving(true);
      try {
        const res = await fetch(
          `/api/bible/${projectId}/custom-workflows/${encodeURIComponent(selectedId)}`,
          {
            method: "PUT",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({
              name: json.name,
              description: json.description || "",
              workflow_json: json,
            }),
          },
        );
        if (!res.ok) {
          const text = await res.text().catch(() => "");
          throw new Error(text || `HTTP ${res.status}`);
        }
        showSuccess("工作流已保存");
        // 退出编辑模式并刷新列表与定义
        setEditorMode("view");
        setEditorInitialJson(null);
        refreshList();
        const defUrl = `/api/workflows/${encodeURIComponent(selectedId)}?project_id=${projectId}`;
        fetch(defUrl)
          .then((r) => r.json())
          .then((data: WorkflowDefinition) => setDefinition(data))
          .catch(() => {
            /* 静默：列表已刷新 */
          });
      } catch (e) {
        const msg = e instanceof Error ? e.message : String(e);
        showError(`保存失败：${msg}`);
      } finally {
        setEditorSaving(false);
      }
    },
    [selectedId, projectId, showSuccess, showError, refreshList],
  );

  /** 删除自定义工作流：二次确认后 DELETE */
  const handleDeleteWorkflow = useCallback(async () => {
    if (!selectedId || !projectId || !selectedIsCustom) return;
    const ok = await confirmDelete({
      title: "删除自定义工作流",
      description: `确认删除工作流「${selectedId}」？此操作不可恢复。`,
      confirmText: "删除",
      variant: "danger",
    });
    if (!ok) return;
    try {
      const res = await fetch(
        `/api/bible/${projectId}/custom-workflows/${encodeURIComponent(selectedId)}`,
        { method: "DELETE" },
      );
      if (!res.ok) {
        const text = await res.text().catch(() => "");
        throw new Error(text || `HTTP ${res.status}`);
      }
      showSuccess("工作流已删除");
      // 清空选中状态并刷新列表
      setSelectedId(null);
      setDefinition(null);
      setSelectedIsCustom(false);
      setEditorMode("view");
      setEditorInitialJson(null);
      refreshList();
    } catch (e) {
      const msg = e instanceof Error ? e.message : String(e);
      showError(`删除失败：${msg}`);
    }
  }, [
    selectedId,
    projectId,
    selectedIsCustom,
    confirmDelete,
    showSuccess,
    showError,
    refreshList,
  ]);

  /** 创建自定义工作流：POST /api/bible/{pid}/custom-workflows */
  const handleCreateWorkflow = useCallback(
    async (workflowId: string, name: string, description: string, workflowJson: WorkflowJson) => {
      if (!projectId) {
        showError("项目尚未加载完成");
        return;
      }
      const res = await fetch(`/api/bible/${projectId}/custom-workflows`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          workflow_id: workflowId,
          name,
          description,
          workflow_json: workflowJson,
        }),
      });
      if (!res.ok) {
        const text = await res.text().catch(() => "");
        throw new Error(text || `HTTP ${res.status}`);
      }
      showSuccess(`已创建工作流：${name}`);
      refreshList();
      // 自动选中新创建的工作流
      setSelectedId(workflowId);
      setSelectedIsCustom(true);
      setEditorMode("view");
      setDefinition(null);
      setEditorInitialJson(null);
      // 拉取新工作流定义
      setDefLoading(true);
      const reqId = ++defReqRef.current;
      fetch(`/api/workflows/${encodeURIComponent(workflowId)}?project_id=${projectId}`)
        .then((r) => r.json())
        .then((data: WorkflowDefinition) => {
          if (defReqRef.current === reqId) setDefinition(data);
        })
        .catch(() => {
          if (defReqRef.current === reqId) appendLog("error", "工作流定义加载失败");
        })
        .finally(() => {
          if (defReqRef.current === reqId) setDefLoading(false);
        });
    },
    [projectId, showSuccess, showError, refreshList, appendLog],
  );

  /** 启动 SSE 流式执行（POST 不能用 EventSource，用 fetch + ReadableStream 逐行解析 event:/data: 帧） */
  const handleRun = useCallback(
    async (inputs: Record<string, string>, agentRole: string) => {
      if (!selectedId || running) return;
      if (!projectId) {
        appendLog("error", "项目尚未加载完成，请稍候重试");
        return;
      }
      abortRun();
      const controller = new AbortController();
      abortRef.current = controller;

      // 重置执行状态
      setRunning(true);
      setNodeStatuses({});
      setLogs([]);
      setWorkflowStatus(null);
      setNodeRuns(null);
      appendLog(
        "info",
        `开始执行工作流（项目 #${projectId}，角色 ${agentRole}）`,
      );

      try {
        const res = await fetch(`/api/workflows/${encodeURIComponent(selectedId)}/run`, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            project_id: projectId,
            inputs,
            agent_role: agentRole,
          }),
          signal: controller.signal,
        });
        if (!res.ok) {
          const text = await res.text().catch(() => "");
          throw new Error(text || `请求失败（HTTP ${res.status}）`);
        }
        if (!res.body) throw new Error("无法建立流式连接");

        const reader = res.body.getReader();
        const decoder = new TextDecoder();
        let buffer = "";
        let currentEvent = "";

        while (true) {
          const { done, value } = await reader.read();
          if (done) break;
          buffer += decoder.decode(value, { stream: true });
          const lines = buffer.split("\n");
          buffer = lines.pop() || "";

          for (const line of lines) {
            if (line.startsWith("event: ")) {
              currentEvent = line.slice(7).trim();
            } else if (line.startsWith("data: ")) {
              let data: {
                node?: string;
                label?: string;
                elapsed_s?: number;
                error?: string;
                status?: string;
                node_runs?: NodeRunRecord[];
              };
              try {
                data = JSON.parse(line.slice(6));
              } catch {
                continue; // 忽略无法解析的帧（如 ping）
              }

              if (currentEvent === "node_start") {
                if (data.node) {
                  setNodeStatuses((prev) => ({
                    ...prev,
                    [data.node as string]: { status: "running" },
                  }));
                  appendLog("start", `节点开始：${data.label || data.node}`);
                }
              } else if (currentEvent === "node_done") {
                if (data.node) {
                  setNodeStatuses((prev) => ({
                    ...prev,
                    [data.node as string]: { status: "ok", elapsed: data.elapsed_s },
                  }));
                  appendLog("done", `节点完成：${data.node}（耗时 ${data.elapsed_s}s）`);
                }
              } else if (currentEvent === "node_failed") {
                if (data.node) {
                  setNodeStatuses((prev) => ({
                    ...prev,
                    [data.node as string]: { status: "failed", error: data.error },
                  }));
                  appendLog("failed", `节点失败：${data.node} — ${data.error}`);
                }
              } else if (currentEvent === "workflow_done") {
                const status = data.status || "completed";
                setWorkflowStatus(status);
                setNodeRuns(Array.isArray(data.node_runs) ? data.node_runs : []);
                appendLog(
                  "info",
                  status === "completed" ? "工作流执行完成" : "工作流执行结束（存在失败节点）",
                );
              } else if (currentEvent === "error") {
                setWorkflowStatus("failed");
                appendLog("error", `执行错误：${data.error || "未知错误"}`);
              }
            }
          }
        }
      } catch (e) {
        const err = e as { name?: string; message?: string };
        if (err?.name === "AbortError") {
          // 停止按钮触发的中断：已有终态则保留，否则标记已中止
          setWorkflowStatus((prev) => (prev === null ? "aborted" : prev));
          appendLog("info", "已手动停止执行");
        } else {
          setWorkflowStatus("failed");
          appendLog("error", `连接中断：${err?.message || e}`);
        }
      } finally {
        setRunning(false);
        abortRef.current = null;
      }
    },
    [selectedId, running, projectId, abortRun, appendLog],
  );

  const handleStop = useCallback(() => {
    abortRun();
  }, [abortRun]);

  /** 列表顶部工具栏：新建按钮 + 模式切换/删除（选中自定义时显示） */
  const listToolbar = (
    <div className="flex flex-col gap-2">
      <Button
        size="sm"
        variant="primary"
        onClick={() => setShowCreateDialog(true)}
        className="w-full"
        disabled={!projectId}
        title={!projectId ? "请先在小说创作界面选择项目" : undefined}
      >
        <Plus size={13} aria-hidden="true" />
        新建工作流
      </Button>
      {selectedId && selectedIsCustom && editorMode === "view" && (
        <Button
          size="sm"
          variant="outline"
          onClick={handleEnterEdit}
          className="w-full"
          disabled={editorLoading}
        >
          {editorLoading ? (
            <Loader2 size={13} className="animate-spin motion-reduce:animate-none" aria-hidden="true" />
          ) : (
            <Edit3 size={13} aria-hidden="true" />
          )}
          编辑模式
        </Button>
      )}
      {selectedId && selectedIsCustom && editorMode === "edit" && (
        <Button
          size="sm"
          variant="outline"
          onClick={handleExitEdit}
          className="w-full"
          disabled={editorSaving}
        >
          <Eye size={13} aria-hidden="true" />
          退出编辑
        </Button>
      )}
      {selectedId && selectedIsCustom && (
        <Button
          size="sm"
          variant="danger"
          onClick={handleDeleteWorkflow}
          className="w-full"
          disabled={editorSaving}
        >
          <Trash2 size={13} aria-hidden="true" />
          删除工作流
        </Button>
      )}
    </div>
  );

  return (
    <AppLayout>
      <div className="flex h-full bg-background">
        {/* 左侧：工作流列表（含工具栏；移动端收进抽屉） */}
        {!isMobile && (
          <WorkflowListPanel
            workflows={workflows}
            loading={listLoading}
            error={listError}
            selectedId={selectedId}
            onSelect={handleSelect}
            toolbar={listToolbar}
          />
        )}

        {/* 中间 + 右侧：根据 editorMode 切换为「只读画布 + 执行面板」或「编辑器」 */}
        {editorMode === "edit" && editorInitialJson && selectedId ? (
          <WorkflowEditor
            key={selectedId}
            workflowId={selectedId}
            initialJson={editorInitialJson}
            saving={editorSaving}
            onSave={handleSaveWorkflow}
            onCancel={handleExitEdit}
          />
        ) : (
          <>
            {/* 中间：只读画布 / 加载态 / 空态 */}
            <section
              className="flex min-w-0 flex-1 flex-col"
              aria-label="工作流画布区"
            >
              {/* 移动端工具条：选择工作流 / 新建 / 编辑 / 删除 / 运行面板 */}
              {isMobile && (
                <div className="flex flex-wrap items-center gap-2 border-b border-border bg-surface px-3 py-2">
                  <Button
                    size="sm"
                    variant="outline"
                    onClick={() => setListOpen(true)}
                    className="shrink-0"
                  >
                    <Menu size={13} aria-hidden="true" />
                    工作流
                  </Button>
                  <span className="min-w-0 flex-1 truncate text-xs text-muted">
                    {definition?.name || "未选择工作流"}
                  </span>
                  {selectedId && selectedIsCustom && editorMode === "view" && (
                    <Button
                      size="sm"
                      variant="outline"
                      onClick={handleEnterEdit}
                      disabled={editorLoading}
                      className="shrink-0"
                    >
                      {editorLoading ? (
                        <Loader2 size={13} className="animate-spin motion-reduce:animate-none" aria-hidden="true" />
                      ) : (
                        <Edit3 size={13} aria-hidden="true" />
                      )}
                      编辑
                    </Button>
                  )}
                  {selectedId && selectedIsCustom && editorMode === "edit" && (
                    <Button
                      size="sm"
                      variant="outline"
                      onClick={handleExitEdit}
                      disabled={editorSaving}
                      className="shrink-0"
                    >
                      <Eye size={13} aria-hidden="true" />
                      预览
                    </Button>
                  )}
                  {selectedId && selectedIsCustom && (
                    <Button
                      size="sm"
                      variant="danger"
                      onClick={handleDeleteWorkflow}
                      disabled={editorSaving}
                      className="shrink-0"
                      aria-label="删除工作流"
                    >
                      <Trash2 size={13} aria-hidden="true" />
                    </Button>
                  )}
                  {definition && editorMode === "view" && (
                    <Button
                      size="sm"
                      variant="primary"
                      onClick={() => setRunOpen(true)}
                      className="shrink-0"
                    >
                      <Play size={13} aria-hidden="true" />
                      运行
                    </Button>
                  )}
                </div>
              )}
              {editorLoading && editorMode === "edit" ? (
                <div
                  className="flex flex-1 items-center justify-center gap-2 text-sm text-muted"
                  role="status"
                >
                  <Loader2
                    size={16}
                    className="animate-spin motion-reduce:animate-none"
                    aria-hidden="true"
                  />
                  加载工作流编辑器...
                </div>
              ) : defLoading ? (
                <div
                  className="flex flex-1 items-center justify-center gap-2 text-sm text-muted"
                  role="status"
                >
                  <Loader2
                    size={16}
                    className="animate-spin motion-reduce:animate-none"
                    aria-hidden="true"
                  />
                  加载工作流定义...
                </div>
              ) : definition ? (
                <div className="min-h-0 flex-1">
                  <WorkflowCanvas definition={definition} nodeStatuses={nodeStatuses} />
                </div>
              ) : (
                <div className="flex flex-1 flex-col items-center justify-center gap-3 px-6 text-center">
                  <img
                    src={DF_BRAND_MARK_DARK}
                    alt=""
                    className={cn("h-16 w-16 animate-float motion-reduce:animate-none")}
                    aria-hidden="true"
                  />
                  <p className="text-sm text-muted">从左侧选择一条工作流</p>
                </div>
              )}
            </section>

            {/* 右侧：执行面板（未选工作流时显示提示；移动端收进底部抽屉） */}
            {!isMobile && (definition && !defLoading ? (
              <WorkflowRunPanel
                definition={definition}
                running={running}
                logs={logs}
                workflowStatus={workflowStatus}
                nodeRuns={nodeRuns}
                projectName={project?.title ?? null}
                onRun={handleRun}
                onStop={handleStop}
              />
            ) : (
              <aside
                className="flex w-80 shrink-0 items-center justify-center border-l border-border bg-surface px-6 text-center"
                aria-label="工作流执行面板"
              >
                <p className="text-xs text-muted">选择工作流后在此填写变量并执行</p>
              </aside>
            ))}
          </>
        )}
      </div>

      {/* 移动端：工作流列表抽屉 */}
      {isMobile && listOpen && (
        <div className="fixed inset-0 z-40 md:hidden" role="dialog" aria-modal="true" aria-label="工作流列表抽屉">
          <div className="absolute inset-0 bg-black/40" onClick={() => setListOpen(false)} aria-hidden="true" />
          <div className="absolute left-0 top-0 bottom-0 flex w-72 max-w-[85vw] flex-col border-r border-border bg-surface shadow-xl">
            <div className="flex h-14 shrink-0 items-center justify-between border-b border-border px-4">
              <span className="text-sm font-semibold text-foreground">工作流</span>
              <DFIconButton
                type="button"
                onClick={() => setListOpen(false)}
                className="inline-flex h-10 w-10 min-h-0 min-w-0 items-center justify-center rounded-lg text-foreground transition-colors hover:bg-surface-hover"
                aria-label="关闭工作流列表"
              >
                <X size={20} aria-hidden="true" />
              </DFIconButton>
            </div>
            <WorkflowListPanel
              workflows={workflows}
              loading={listLoading}
              error={listError}
              selectedId={selectedId}
              onSelect={(id) => {
                handleSelect(id);
                setListOpen(false);
              }}
              toolbar={listToolbar}
            />
          </div>
        </div>
      )}

      {/* 移动端：运行面板底部抽屉 */}
      {isMobile && definition && !defLoading && runOpen && (
        <div
          className="fixed bottom-0 inset-x-0 z-30 flex max-h-[70vh] flex-col border-t border-border bg-surface shadow-[0_-8px_24px_rgba(0,0,0,0.12)]"
          style={{ paddingBottom: "env(safe-area-inset-bottom, 0px)" }}
        >
          <div className="flex h-12 shrink-0 items-center justify-between border-b border-border px-4">
            <span className="text-sm font-semibold text-foreground">运行面板</span>
            <DFIconButton
              type="button"
              onClick={() => setRunOpen(false)}
              className="inline-flex h-10 min-h-0 items-center justify-start gap-1 rounded-lg px-3 text-sm text-muted transition-colors hover:bg-surface-hover hover:text-muted"
              aria-label="收起运行面板"
            >
              <X size={16} aria-hidden="true" /> 收起
            </DFIconButton>
          </div>
          <div className="flex min-h-0 flex-1 justify-center overflow-y-auto">
            <WorkflowRunPanel
              definition={definition}
              running={running}
              logs={logs}
              workflowStatus={workflowStatus}
              nodeRuns={nodeRuns}
              projectName={project?.title ?? null}
              onRun={handleRun}
              onStop={handleStop}
            />
          </div>
        </div>
      )}

      {/* 新建工作流弹窗 */}
      <CreateWorkflowDialog
        open={showCreateDialog}
        onOpenChange={setShowCreateDialog}
        projectId={projectId}
        workflows={workflows}
        onCreate={handleCreateWorkflow}
      />

      {/* 删除二次确认弹窗 */}
      {deleteDialog}
    </AppLayout>
  );
}
