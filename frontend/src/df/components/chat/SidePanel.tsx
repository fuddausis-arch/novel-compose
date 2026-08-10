/**
 * 右侧可拖拽调宽侧边栏
 *
 * - 拖拽左边线调宽（280–800px），宽度持久化 localStorage
 * - 顶部三个 tab：会话 / 提示词 / 工作空间
 *   - 会话：新建会话按钮 + 会话卡片列表（选中态 ring-1 ring-indigo-500/50）
 *   - 提示词：当前对话 Agent 的 prompt 预览（只读 + 刷新）
 *   - 工作空间：项目目录文件树（懒加载）+ 文件预览
 */
import { useCallback, useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import {
  ChevronDown, ChevronRight, File, FileText, FolderClosed, FolderCode, FolderOpen,
  GripVertical, MessageSquare, Plus, RefreshCw, Trash2, X,
} from "lucide-react";
import { ScrollArea } from "@/components/ui/scroll-area";
import {
  formatRelativeTime, formatTokens, getPromptPreview, listWorkspaceFiles, readWorkspaceFile,
  type DFChatSession, type LLMConfigInfo, type PromptPreview, type WorkspaceEntry,
} from "./api";

export type SidePanelTab = "sessions" | "prompt" | "workspace";

const WIDTH_STORAGE_KEY = "df.chat.sidePanelWidth";
const MIN_WIDTH = 280;
const MAX_WIDTH = 800;

/** 会话类型中文标签 */
const OBJECT_TYPE_LABELS: Record<string, string> = {
  chapter: "章节",
  outline: "大纲",
  character: "角色",
  monster: "怪物",
  world: "世界观",
  faction: "阵营",
  relationship: "关系",
  chat: "对话",
};

function sessionTypeLabel(session: DFChatSession): string {
  if (session.session_type === "global") return "全局";
  return OBJECT_TYPE_LABELS[session.object_type] || session.object_type || "对象";
}

// ---------- 会话面板 ----------

interface SessionsPanelProps {
  sessions: DFChatSession[];
  messageCounts: Record<string, number>;
  activeSessionId: string | null;
  draftNew: boolean;
  onSelectSession: (id: string) => void;
  onNewSession: () => void;
  onDeleteSession: (id: string) => void;
}

function SessionsPanel({
  sessions, messageCounts, activeSessionId, draftNew,
  onSelectSession, onNewSession, onDeleteSession,
}: SessionsPanelProps) {
  return (
    <ScrollArea className="h-full">
      <div className="px-3 py-2 space-y-2">
        <button
          type="button"
          onClick={onNewSession}
          className="w-full flex items-center justify-center gap-2 px-3 py-2 rounded-lg bg-indigo-500/20 text-indigo-400 hover:bg-indigo-500/30 transition-colors text-xs font-medium cursor-pointer min-h-[44px]"
        >
          <Plus size={14} aria-hidden="true" />
          新建会话
        </button>

        {sessions.length === 0 && (
          <div className="text-center text-muted text-sm py-4" role="status">暂无会话</div>
        )}

        {sessions.map((session) => {
          const isActive = !draftNew && activeSessionId === session.id;
          const count = messageCounts[session.id];
          return (
            <div
              key={session.id}
              role="button"
              tabIndex={0}
              onClick={() => onSelectSession(session.id)}
              onKeyDown={(e) => { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); onSelectSession(session.id); } }}
              aria-label={`会话 ${session.title}`}
              className={`group relative bg-surface-elevated/50 border border-border rounded-lg px-3 py-2.5 transition-all cursor-pointer ${
                isActive
                  ? "ring-1 ring-indigo-500/50 border-indigo-500/60 bg-indigo-500/10"
                  : "hover:border-indigo-500/30"
              }`}
            >
              {isActive && (
                <div className="absolute left-0 top-1/2 -translate-y-1/2 w-0.5 h-6 bg-indigo-500 rounded-r" aria-hidden="true" />
              )}
              <div className="flex items-center justify-between mb-1">
                <span className="text-xs font-medium text-foreground truncate">{session.title || "未命名会话"}</span>
                <span className="ml-2 shrink-0 rounded border border-cyan-500/30 px-1 py-px text-[10px] text-cyan-400">
                  {sessionTypeLabel(session)}
                </span>
              </div>
              <div className="flex items-center justify-between text-xs text-muted">
                <span>{count === undefined ? "…" : `${count} 条消息`}</span>
                <div className="flex items-center gap-1">
                  <span>{formatRelativeTime(session.updated_at)}</span>
                  <button
                    type="button"
                    onClick={(e) => { e.stopPropagation(); onDeleteSession(session.id); }}
                    aria-label={`删除会话 ${session.title}`}
                    className="p-0.5 rounded text-red-400 hover:bg-red-500/20 opacity-0 group-hover:opacity-100 transition-opacity cursor-pointer min-h-[44px] min-w-[44px] flex items-center justify-center"
                  >
                    <Trash2 size={12} aria-hidden="true" />
                  </button>
                </div>
              </div>
            </div>
          );
        })}
      </div>
    </ScrollArea>
  );
}

// ---------- 提示词面板 ----------

function PromptPanel({ llmConfig }: { llmConfig: LLMConfigInfo | null }) {
  const navigate = useNavigate();
  const [preview, setPreview] = useState<PromptPreview | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      // 对话 Agent 对应 orchestrator 角色的 prompt 编排
      setPreview(await getPromptPreview("orchestrator"));
    } catch (e) {
      setError(e instanceof Error ? e.message : "加载提示词失败");
      setPreview(null);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => { void load(); }, [load]);

  return (
    <div className="h-full flex flex-col">
      <div className="px-3 py-2 border-b border-border/50 flex-shrink-0">
        <div className="flex items-center justify-between mb-1.5">
          <span className="text-xs font-medium text-purple-400">System Prompt 上下文</span>
          <button
            type="button"
            onClick={() => void load()}
            disabled={loading}
            className="p-1 rounded-md text-muted hover:text-foreground hover:bg-surface transition-colors cursor-pointer disabled:opacity-40 min-h-[44px] min-w-[44px] flex items-center justify-center"
            aria-label="刷新提示词上下文"
          >
            <RefreshCw size={12} className={loading ? "animate-spin motion-reduce:animate-none" : ""} aria-hidden="true" />
          </button>
        </div>
        <div className="flex items-center gap-2 text-xs text-muted flex-wrap">
          <span className="font-mono text-cyan-500">{llmConfig?.model || "未配置模型"}</span>
          {preview ? (
            <>
              <span aria-hidden="true">·</span>
              <span>~{formatTokens(preview.estimated_tokens)}t</span>
              <span aria-hidden="true">·</span>
              <span>{preview.enabled_count}/{preview.section_count} 节</span>
            </>
          ) : null}
        </div>
      </div>
      <ScrollArea className="flex-1">
        <div className="px-3 py-2">
          {error && <div className="text-xs text-red-400 py-2" role="alert">{error}</div>}
          {!error && preview && !preview.prompt.trim() && (
            <div className="text-center py-6" role="status">
              <FileText size={24} className="mx-auto mb-2 text-slate-700" aria-hidden="true" />
              <p className="text-xs text-muted">当前对话 Agent 未配置 Prompt Section</p>
              <button
                type="button"
                onClick={() => navigate("/df/system-prompt")}
                className="mt-2 text-xs text-indigo-400 hover:text-indigo-300 cursor-pointer min-h-[44px] px-2"
              >
                前往提示词编排 →
              </button>
            </div>
          )}
          {!error && preview?.prompt.trim() && (
            <pre className="whitespace-pre-wrap break-words rounded-lg bg-surface-elevated border border-border p-3 text-xs leading-relaxed text-foreground font-mono">
              {preview.prompt}
            </pre>
          )}
        </div>
      </ScrollArea>
    </div>
  );
}

// ---------- 工作空间面板 ----------

interface TreeNodeState {
  entry: WorkspaceEntry;
  path: string;
  children: TreeNodeState[] | null; // null = 未加载
  loading: boolean;
}

function WorkspaceTreeItem({ node, depth, projectId, onPreview }: {
  node: TreeNodeState;
  depth: number;
  projectId: number;
  onPreview: (path: string) => void;
}) {
  const [expanded, setExpanded] = useState(false);
  const [children, setChildren] = useState<TreeNodeState[] | null>(node.children);
  const [loading, setLoading] = useState(false);
  const isDir = node.entry.type === "dir";

  const toggle = async () => {
    if (!isDir) {
      onPreview(node.path);
      return;
    }
    if (!expanded && children === null) {
      // 懒加载子目录
      setLoading(true);
      try {
        const files = await listWorkspaceFiles(projectId, node.path);
        setChildren(files.map((f) => ({
          entry: f,
          path: node.path ? `${node.path}/${f.name}` : f.name,
          children: f.type === "dir" ? null : [],
          loading: false,
        })));
      } catch {
        setChildren([]);
      } finally {
        setLoading(false);
      }
    }
    setExpanded((v) => !v);
  };

  return (
    <div role="treeitem" aria-expanded={isDir ? expanded : undefined}>
      <button
        type="button"
        onClick={() => void toggle()}
        className="w-full flex items-center gap-1 py-0.5 px-1 rounded text-xs hover:bg-white/5 transition-colors cursor-pointer min-h-[44px] text-foreground"
        style={{ paddingLeft: `${depth * 14 + 4}px` }}
        aria-label={isDir ? `${expanded ? "折叠" : "展开"}文件夹 ${node.entry.name}` : `打开文件 ${node.entry.name}`}
      >
        {isDir ? (
          loading ? (
            <RefreshCw size={14} className="text-muted flex-shrink-0 animate-spin motion-reduce:animate-none" aria-hidden="true" />
          ) : expanded ? (
            <ChevronDown size={14} className="text-muted flex-shrink-0" aria-hidden="true" />
          ) : (
            <ChevronRight size={14} className="text-muted flex-shrink-0" aria-hidden="true" />
          )
        ) : (
          <span className="w-3 flex-shrink-0" aria-hidden="true" />
        )}
        {isDir ? (
          expanded ? (
            <FolderOpen size={14} className="text-cyan-500 flex-shrink-0" aria-hidden="true" />
          ) : (
            <FolderClosed size={14} className="text-cyan-500/70 flex-shrink-0" aria-hidden="true" />
          )
        ) : (
          <File size={14} className="text-muted flex-shrink-0" aria-hidden="true" />
        )}
        <span className="truncate">{node.entry.name}</span>
      </button>
      {isDir && expanded && children && (
        <div role="group">
          {children.map((child) => (
            <WorkspaceTreeItem key={child.path} node={child} depth={depth + 1} projectId={projectId} onPreview={onPreview} />
          ))}
          {children.length === 0 && (
            <div className="text-xs text-muted py-1" style={{ paddingLeft: `${(depth + 1) * 14 + 4}px` }}>空目录</div>
          )}
        </div>
      )}
    </div>
  );
}

function WorkspacePanel({ projectId }: { projectId: number }) {
  const [roots, setRoots] = useState<TreeNodeState[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [previewPath, setPreviewPath] = useState<string | null>(null);
  const [previewContent, setPreviewContent] = useState<string>("");
  const [previewLoading, setPreviewLoading] = useState(false);

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const files = await listWorkspaceFiles(projectId, "");
      setRoots(files.map((f) => ({
        entry: f,
        path: f.name,
        children: f.type === "dir" ? null : [],
        loading: false,
      })));
    } catch (e) {
      setError(e instanceof Error ? e.message : "加载工作空间失败");
      setRoots([]);
    } finally {
      setLoading(false);
    }
  }, [projectId]);

  useEffect(() => { void load(); }, [load]);

  const handlePreview = useCallback(async (path: string) => {
    setPreviewPath(path);
    setPreviewLoading(true);
    try {
      const data = await readWorkspaceFile(projectId, path);
      setPreviewContent(data.content);
    } catch {
      setPreviewContent("// 无法加载文件内容");
    } finally {
      setPreviewLoading(false);
    }
  }, [projectId]);

  return (
    <div className="h-full flex flex-col">
      <div className="px-3 py-2 border-b border-border/50 flex-shrink-0">
        <div className="flex items-center justify-between">
          <div className="flex items-center gap-1.5">
            <FolderCode size={14} className="text-cyan-500" aria-hidden="true" />
            <span className="text-xs font-medium text-foreground">项目工作空间</span>
          </div>
          <button
            type="button"
            onClick={() => void load()}
            disabled={loading}
            className="p-1 rounded-md text-muted hover:text-foreground hover:bg-surface transition-colors cursor-pointer disabled:opacity-40 min-h-[44px] min-w-[44px] flex items-center justify-center"
            aria-label="刷新工作空间文件树"
          >
            <RefreshCw size={12} className={loading ? "animate-spin motion-reduce:animate-none" : ""} aria-hidden="true" />
          </button>
        </div>
      </div>

      {error && <div className="px-3 py-2 text-xs text-red-400" role="alert">{error}</div>}

      {!previewPath ? (
        <ScrollArea className="flex-1">
          <div className="py-1" role="tree" aria-label="工作空间文件树">
            {loading && roots.length === 0 ? (
              <div className="flex items-center justify-center gap-2 p-4 text-sm text-muted" role="status">
                <RefreshCw size={14} className="animate-spin motion-reduce:animate-none" aria-hidden="true" />
                加载中...
              </div>
            ) : (
              <>
                {roots.map((node) => (
                  <WorkspaceTreeItem key={node.path} node={node} depth={0} projectId={projectId} onPreview={(p) => void handlePreview(p)} />
                ))}
                {roots.length === 0 && !loading && !error && (
                  <div className="text-center text-muted text-xs py-4" role="status">空目录</div>
                )}
              </>
            )}
          </div>
        </ScrollArea>
      ) : (
        <div className="flex-1 flex flex-col overflow-hidden">
          <div className="px-3 py-1.5 border-b border-border/50 flex items-center gap-2 flex-shrink-0">
            <File size={12} className="text-muted" aria-hidden="true" />
            <span className="text-xs font-mono text-cyan-500 truncate flex-1">{previewPath}</span>
            <button
              type="button"
              onClick={() => setPreviewPath(null)}
              className="p-0.5 rounded text-muted hover:text-foreground cursor-pointer min-h-[44px] min-w-[44px] flex items-center justify-center"
              aria-label="关闭文件预览"
            >
              <X size={12} aria-hidden="true" />
            </button>
          </div>
          <ScrollArea className="flex-1">
            {previewLoading ? (
              <div className="flex items-center justify-center gap-2 p-4 text-sm text-muted" role="status">
                <RefreshCw size={12} className="animate-spin motion-reduce:animate-none" aria-hidden="true" />
                加载中...
              </div>
            ) : (
              <pre className="p-2 text-xs font-mono text-foreground leading-relaxed whitespace-pre-wrap">{previewContent}</pre>
            )}
          </ScrollArea>
        </div>
      )}
    </div>
  );
}

// ---------- 侧边栏主体 ----------

export interface SidePanelProps {
  projectId: number;
  tab: SidePanelTab;
  setTab: (tab: SidePanelTab) => void;
  sessions: DFChatSession[];
  messageCounts: Record<string, number>;
  activeSessionId: string | null;
  draftNew: boolean;
  onSelectSession: (id: string) => void;
  onNewSession: () => void;
  onDeleteSession: (id: string) => void;
  llmConfig: LLMConfigInfo | null;
}

const TABS: { key: SidePanelTab; icon: typeof MessageSquare; label: string }[] = [
  { key: "sessions", icon: MessageSquare, label: "会话" },
  { key: "prompt", icon: FileText, label: "提示词" },
  { key: "workspace", icon: FolderCode, label: "工作空间" },
];

export default function SidePanel({
  projectId, tab, setTab, sessions, messageCounts, activeSessionId, draftNew,
  onSelectSession, onNewSession, onDeleteSession, llmConfig,
}: SidePanelProps) {
  const [width, setWidth] = useState(() => {
    const saved = Number(localStorage.getItem(WIDTH_STORAGE_KEY));
    return saved >= MIN_WIDTH && saved <= MAX_WIDTH ? saved : 320;
  });
  const [isResizing, setIsResizing] = useState(false);

  // 拖拽左边线调宽
  useEffect(() => {
    if (!isResizing) return;
    const handleMouseMove = (e: MouseEvent) => {
      const newWidth = Math.max(MIN_WIDTH, Math.min(MAX_WIDTH, window.innerWidth - e.clientX));
      setWidth(newWidth);
    };
    const handleMouseUp = () => setIsResizing(false);
    document.addEventListener("mousemove", handleMouseMove);
    document.addEventListener("mouseup", handleMouseUp);
    document.body.style.cursor = "col-resize";
    document.body.style.userSelect = "none";
    return () => {
      document.removeEventListener("mousemove", handleMouseMove);
      document.removeEventListener("mouseup", handleMouseUp);
      document.body.style.cursor = "";
      document.body.style.userSelect = "";
    };
  }, [isResizing]);

  // 宽度持久化
  useEffect(() => {
    localStorage.setItem(WIDTH_STORAGE_KEY, String(width));
  }, [width]);

  const handleKeyDown = (e: React.KeyboardEvent) => {
    if (e.key === "ArrowLeft" || e.key === "ArrowRight") {
      e.preventDefault();
      const delta = e.key === "ArrowLeft" ? -10 : 10;
      setWidth((w) => Math.max(MIN_WIDTH, Math.min(MAX_WIDTH, w + delta)));
    }
  };

  return (
    <div
      className="shrink-0 border-l border-border bg-background flex flex-col relative"
      style={{ width: `${width}px`, minWidth: `${MIN_WIDTH}px`, maxWidth: `${MAX_WIDTH}px` }}
    >
      {/* 拖拽手柄 */}
      <div
        onMouseDown={(e) => { e.preventDefault(); setIsResizing(true); }}
        onKeyDown={handleKeyDown}
        role="separator"
        aria-orientation="vertical"
        aria-label="调整侧边面板宽度，使用左右箭头键调整"
        tabIndex={0}
        className={`absolute left-0 top-0 bottom-0 w-1 cursor-col-resize hover:bg-indigo-500/30 transition-colors z-10 group ${
          isResizing ? "bg-indigo-500/50" : ""
        }`}
      >
        <div className="absolute left-1/2 top-1/2 -translate-x-1/2 -translate-y-1/2 opacity-0 group-hover:opacity-100 transition-opacity">
          <GripVertical size={16} className="text-indigo-500" aria-hidden="true" />
        </div>
      </div>

      {/* Tab 头 */}
      <div className="flex border-b border-border" role="tablist" aria-label="侧边面板导航">
        {TABS.map(({ key, icon: Icon, label }) => (
          <button
            key={key}
            type="button"
            onClick={() => setTab(key)}
            role="tab"
            aria-selected={tab === key}
            aria-controls={`df-panel-${key}`}
            className={`flex-1 flex items-center justify-center gap-1.5 py-2.5 text-xs font-medium transition-colors cursor-pointer min-h-[44px] ${
              tab === key
                ? "text-indigo-500 border-b-2 border-indigo-500"
                : "text-muted hover:text-foreground"
            }`}
          >
            <Icon size={14} aria-hidden="true" />
            {label}
          </button>
        ))}
      </div>

      {/* 面板内容（切换时卸载重建，保证提示词/工作空间自动刷新） */}
      <div className="flex-1 overflow-hidden">
        {tab === "sessions" && (
          <div id="df-panel-sessions" className="h-full" role="tabpanel" aria-label="会话面板">
            <SessionsPanel
              sessions={sessions}
              messageCounts={messageCounts}
              activeSessionId={activeSessionId}
              draftNew={draftNew}
              onSelectSession={onSelectSession}
              onNewSession={onNewSession}
              onDeleteSession={onDeleteSession}
            />
          </div>
        )}
        {tab === "prompt" && (
          <div id="df-panel-prompt" className="h-full" role="tabpanel" aria-label="提示词面板">
            <PromptPanel llmConfig={llmConfig} />
          </div>
        )}
        {tab === "workspace" && (
          <div id="df-panel-workspace" className="h-full" role="tabpanel" aria-label="工作空间面板">
            <WorkspacePanel projectId={projectId} />
          </div>
        )}
      </div>
    </div>
  );
}
