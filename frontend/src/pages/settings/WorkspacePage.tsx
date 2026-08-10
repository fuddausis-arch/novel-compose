/** 全局设置 · 工作区页：左侧文件树 + 右侧文件内容查看 */
import { useCallback, useEffect, useState, type ReactNode } from "react";
import { File, FolderClosed, FolderOpen, Loader2 } from "lucide-react";
import { Card } from "@/components/ui/card";
import { EmptyState } from "@/components/ui/empty-state";
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
      <div className="grid gap-4 lg:grid-cols-[300px_1fr]">
        <Card className="p-2">
          <div className="max-h-[60vh] overflow-y-auto">
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
        <Card className="p-4">
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
              <pre className="max-h-[60vh] overflow-auto whitespace-pre-wrap rounded-lg border border-border bg-background p-3 text-xs text-muted">
                {content ?? "（空文件）"}
              </pre>
            </div>
          )}
        </Card>
      </div>
    );
  }

  return (
    <div className="h-full overflow-y-auto">
      <div className="mx-auto max-w-6xl space-y-6 p-6">
        {header}
        {body}
      </div>
    </div>
  );
}
