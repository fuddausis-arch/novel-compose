/** 全局设置 · 工作区页：左侧文件树 + 右侧文件内容查看 + 会话树/附件/分支 */
import { useCallback, useEffect, useState, type ReactNode } from "react";
import { File, FolderClosed, FolderOpen, GitBranch, Loader2, MessageSquare, Paperclip } from "lucide-react";
import { api } from "@/api";
import { useToast } from "@/hooks/useToast";
import { Card } from "@/components/ui/card";
import { EmptyState } from "@/components/ui/empty-state";
import { Select } from "@/components/ui/select";
import { Input } from "@/components/ui/input";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { cn } from "@/lib/utils";

interface FileNode {
  name: string;
  path: string;
  type: "dir" | "file";
  children?: FileNode[];
}

interface FileContent {
  path: string;
  content: string;
}

interface SessionTreeNode {
  id: string;
  title: string;
  session_type?: string;
  children?: SessionTreeNode[];
}

function formatBytes(bytes: number): string {
  if (!bytes) return "0 B";
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  return `${(bytes / 1024 / 1024).toFixed(1)} MB`;
}

async function fetchJson<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(path, { headers: { "Content-Type": "application/json" }, ...init });
  if (!res.ok) {
    const text = await res.text().catch(() => "");
    let msg = `请求失败（HTTP ${res.status}）`;
    try {
      const j = JSON.parse(text);
      if (j.detail) msg = String(j.detail);
      else if (j.message) msg = String(j.message);
    } catch {
      /* 非 JSON，忽略 */
    }
    throw new Error(msg);
  }
  if (res.status === 204) return undefined as T;
  return (await res.json()) as T;
}

/** 递归文件树节点 */
function TreeNode({
  node,
  depth,
  selectedPath,
  onSelect,
}: {
  node: FileNode;
  depth: number;
  selectedPath: string | null;
  onSelect: (node: FileNode) => void;
}) {
  const [open, setOpen] = useState(depth === 0);
  const isDir = node.type === "dir";
  const isSelected = selectedPath === node.path;

  return (
    <div>
      <button
        type="button"
        onClick={() => (isDir ? setOpen((o) => !o) : onSelect(node))}
        className={cn(
          "flex w-full items-center gap-1.5 rounded-md px-2 py-1 text-left text-sm transition-colors",
          isSelected ? "bg-primary-muted text-primary" : "hover:bg-surface-hover",
        )}
        style={{ paddingLeft: `${depth * 12 + 8}px` }}
      >
        {isDir ? (
          open ? (
            <FolderOpen className="h-4 w-4 shrink-0 text-primary" />
          ) : (
            <FolderClosed className="h-4 w-4 shrink-0 text-muted" />
          )
        ) : (
          <File className="h-4 w-4 shrink-0 text-muted" />
        )}
        <span className="truncate">{node.name}</span>
      </button>
      {isDir && open && node.children && (
        <div>
          {node.children.map((child) => (
            <TreeNode
              key={child.path}
              node={child}
              depth={depth + 1}
              selectedPath={selectedPath}
              onSelect={onSelect}
            />
          ))}
        </div>
      )}
    </div>
  );
}

/**
 * 会话与附件管理：
 * - 会话树 GET /api/workspace/sessions/{project_id}/tree
 * - 附件列表 GET /api/workspace/attachments/{session_id}
 * - 会话分支 POST /api/workspace/sessions/{session_id}/branch
 */
function SessionWorkspaceSection() {
  const { showSuccess, showError } = useToast();
  const [projects, setProjects] = useState<{ id: number; title: string }[]>([]);
  const [projectId, setProjectId] = useState<number>(0);
  const [sessions, setSessions] = useState<SessionTreeNode[]>([]);
  const [loading, setLoading] = useState(false);
  const [attachments, setAttachments] = useState<Record<string, { filename: string; size: number }[]>>({});
  const [branchTitles, setBranchTitles] = useState<Record<string, string>>({});
  const [busyId, setBusyId] = useState<string | null>(null);
  const [attachingId, setAttachingId] = useState<string | null>(null);

  useEffect(() => {
    api.listProjects()
      .then((list) => {
        setProjects(list);
        if (list.length > 0) setProjectId(list[0].id);
      })
      .catch(() => { /* 忽略 */ });
  }, []);

  const loadTree = useCallback(async () => {
    if (!projectId) {
      setSessions([]);
      return;
    }
    setLoading(true);
    try {
      const data = await api.getSessionTree(projectId);
      setSessions(data.sessions || []);
    } catch (e: any) {
      showError("加载会话树失败：" + e.message);
    } finally {
      setLoading(false);
    }
  }, [projectId, showError]);

  useEffect(() => {
    void loadTree();
  }, [loadTree]);

  const loadAttachments = async (sessionId: string) => {
    setAttachingId(sessionId);
    try {
      const data = await api.listWorkspaceAttachments(projectId, sessionId);
      setAttachments((prev) => ({ ...prev, [sessionId]: data.attachments || [] }));
    } catch (e: any) {
      showError("加载附件失败：" + e.message);
    } finally {
      setAttachingId(null);
    }
  };

  const handleBranch = async (sessionId: string) => {
    setBusyId(sessionId);
    try {
      const title = (branchTitles[sessionId] || "").trim();
      const r = await api.branchSession(sessionId, projectId, title);
      showSuccess(`已创建分支会话：${r.title}`);
      setBranchTitles((prev) => ({ ...prev, [sessionId]: "" }));
      await loadTree();
    } catch (e: any) {
      showError("创建分支失败：" + e.message);
    } finally {
      setBusyId(null);
    }
  };

  const renderSession = (s: SessionTreeNode, depth: number) => {
    const attachList = attachments[s.id];
    const attachLoaded = attachList !== undefined;
    return (
      <div key={s.id} style={{ paddingLeft: depth * 16 }}>
        <div className="rounded-lg border border-border bg-surface-elevated p-3">
          <div className="flex flex-wrap items-center gap-2">
            <MessageSquare className="h-3.5 w-3.5 shrink-0 text-muted" />
            <span className="min-w-0 flex-1 truncate text-sm font-medium text-foreground">{s.title || s.id}</span>
            {s.session_type && <Badge variant="default">{s.session_type}</Badge>}
            <Button
              size="sm"
              variant="ghost"
              disabled={attachingId === s.id}
              onClick={() => void loadAttachments(s.id)}
              title="查看附件列表"
            >
              <Paperclip className="h-3.5 w-3.5 mr-1" />
              {attachLoaded ? `附件（${attachList.length}）` : "附件"}
            </Button>
          </div>

          {/* 附件列表 */}
          {attachLoaded && (
            <div className="mt-2 space-y-1 rounded-lg bg-surface/50 p-2">
              {attachList.length === 0 ? (
                <div className="text-xs text-muted">暂无附件</div>
              ) : (
                attachList.map((a) => (
                  <div key={a.filename} className="flex items-center gap-2 text-xs text-muted">
                    <File className="h-3 w-3 shrink-0" />
                    <span className="truncate">{a.filename}</span>
                    <span className="ml-auto shrink-0">{formatBytes(a.size)}</span>
                  </div>
                ))
              )}
            </div>
          )}

          {/* 分支表单 */}
          <div className="mt-2 flex items-center gap-2">
            <Input
              className="h-8 text-xs"
              placeholder="分支标题（可选）"
              value={branchTitles[s.id] || ""}
              onChange={(e) => setBranchTitles((prev) => ({ ...prev, [s.id]: e.target.value }))}
            />
            <Button size="sm" variant="outline" disabled={busyId === s.id} onClick={() => void handleBranch(s.id)}>
              <GitBranch className="h-3.5 w-3.5 mr-1" />
              {busyId === s.id ? "创建中…" : "创建分支"}
            </Button>
          </div>
        </div>
        {s.children && s.children.length > 0 && (
          <div className="mt-2 space-y-2">{s.children.map((c) => renderSession(c, depth + 1))}</div>
        )}
      </div>
    );
  };

  return (
    <Card className="p-4">
      <div className="flex flex-wrap items-center gap-3">
        <div className="flex items-center gap-2">
          <MessageSquare className="h-4 w-4 text-primary" />
          <h3 className="text-sm font-semibold text-foreground">会话与附件</h3>
        </div>
        <div className="flex items-center gap-2">
          <span className="text-xs text-muted">项目</span>
          <Select
            className="w-52"
            value={String(projectId || "")}
            onChange={(e) => setProjectId(Number(e.target.value) || 0)}
          >
            {projects.map((p) => (
              <option key={p.id} value={p.id}>{p.title}</option>
            ))}
          </Select>
        </div>
      </div>
      <p className="mt-1 text-xs text-muted">查看会话树、各会话附件，并可基于任一会话创建分支讨论。</p>

      <div className="mt-3">
        {loading ? (
          <div className="flex items-center gap-2 py-8 text-sm text-muted">
            <Loader2 className="h-4 w-4 animate-spin" /> 加载会话树…
          </div>
        ) : sessions.length === 0 ? (
          <EmptyState icon={<MessageSquare className="h-8 w-8 text-muted" />} title="暂无会话" description="该项目还没有会话记录" />
        ) : (
          <div className="space-y-2">{sessions.map((s) => renderSession(s, 0))}</div>
        )}
      </div>
    </Card>
  );
}

export default function WorkspacePage() {
  const [tree, setTree] = useState<FileNode[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [selected, setSelected] = useState<FileNode | null>(null);
  const [content, setContent] = useState<string | null>(null);
  const [contentLoading, setContentLoading] = useState(false);

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const data = await fetchJson<{ files: FileNode[] }>("/api/workspace/files");
      setTree(data.files || []);
    } catch (e) {
      setError(e instanceof Error ? e.message : "加载失败");
      setTree([]);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  const handleSelect = useCallback(async (node: FileNode) => {
    setSelected(node);
    setContentLoading(true);
    try {
      const data = await fetchJson<FileContent>(
        `/api/workspace/files/${encodeURIComponent(node.path)}`,
      );
      setContent(data.content);
    } catch (e) {
      setContent(e instanceof Error ? e.message : "加载文件内容失败");
    } finally {
      setContentLoading(false);
    }
  }, []);

  const header = (
    <div className="flex items-center gap-3">
      <div className="rounded-lg border border-border bg-primary-muted p-2 text-primary">
        <FolderOpen className="h-5 w-5" />
      </div>
      <div>
        <h2 className="text-lg font-semibold">工作区</h2>
        <p className="text-sm text-muted">浏览与管理项目工作区文件</p>
      </div>
    </div>
  );

  let body: ReactNode;
  if (loading) {
    body = (
      <div className="flex items-center justify-center py-20">
        <Loader2 className="mr-2 h-5 w-5 animate-spin text-muted" />
        <span className="text-sm text-muted">正在加载文件树...</span>
      </div>
    );
  } else if (error || tree.length === 0) {
    body = (
      <EmptyState
        icon={<FolderOpen className="h-10 w-10 text-muted" />}
        title={error ? "后端工作区尚未接入" : "工作区为空"}
        description={error ?? "/api/workspace/files 未返回任何文件"}
      />
    );
  } else {
    body = (
      <div className="grid min-h-0 flex-1 gap-4 lg:grid-cols-[300px_1fr]">
        <Card className="p-2 lg:h-full">
          <div className="max-h-[60vh] overflow-y-auto lg:max-h-none lg:h-full">
            {tree.map((node) => (
              <TreeNode
                key={node.path}
                node={node}
                depth={0}
                selectedPath={selected?.path ?? null}
                onSelect={(n) => void handleSelect(n)}
              />
            ))}
          </div>
        </Card>
        <Card className="p-4 lg:h-full lg:overflow-y-auto">
          {!selected ? (
            <div className="flex min-h-[320px] items-center justify-center text-sm text-muted">
              选择左侧文件查看内容
            </div>
          ) : contentLoading ? (
            <div className="flex items-center justify-center py-20">
              <Loader2 className="mr-2 h-5 w-5 animate-spin text-muted" />
              <span className="text-sm text-muted">加载内容...</span>
            </div>
          ) : (
            <div className="space-y-2">
              <div className="font-mono text-xs text-muted">{selected.path}</div>
              <pre className="max-h-[60vh] overflow-auto whitespace-pre-wrap rounded-lg border border-border bg-background p-3 text-xs text-muted lg:max-h-none">
                {content ?? "（空文件）"}
              </pre>
            </div>
          )}
        </Card>
      </div>
    );
  }

  return (
    <div className="flex h-full flex-col overflow-y-auto lg:overflow-hidden">
      <div className="mx-auto w-full max-w-6xl shrink-0 space-y-6 p-6 lg:pb-3">
        {header}
      </div>
      <div className="mx-auto flex w-full max-w-6xl min-h-0 flex-1 flex-col gap-6 px-6 pb-6">
        {body}
        <div className="shrink-0 lg:max-h-[45vh] lg:overflow-y-auto">
          <SessionWorkspaceSection />
        </div>
      </div>
    </div>
  );
}
