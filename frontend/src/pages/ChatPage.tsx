/**
 * 聊天页（项目内路由 /projects/:projectId/chat）
 *
 * 融合两种模式：
 * - 对话模式（chat）：DF 风格 SSE 流式聊天（/api/chat/messages）
 * - 交互创作（creative）：问答/自由模式生成章节（/api/generation/interactive/chat/stream）
 *   - 章节卡片 + 人审 + 润色 + 重写 + 提交圣经
 *   - 思考过程 / 工具调用 / reasoning 实时显示
 *
 * 两种模式的消息历史独立存储，互不干扰。
 */
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import {
  CheckCircle2, Loader2, Sparkles, X, XCircle,
  MessageSquare, PenLine, Zap,
} from "lucide-react";
import { AppLayout } from "@/components/layout/AppLayout";
import { useCurrentProject } from "@/hooks/useCurrentProject";
import { useAppStore } from "@/store";
import { bumpDataVersion } from "@/store/slices/dataVersion";
import { api } from "@/api";
import { useToast } from "@/hooks/useToast";
import { useMediaQuery } from "@/hooks/useMediaQuery";
import { Markdown } from "@/components/markdown";
import { Button } from "@/components/ui/button";
import { Textarea } from "@/components/ui/textarea";
import { Switch } from "@/components/ui/switch";
import { HelpIcon } from "@/components/ui/help-icon";
import { helpTexts } from "@/help-texts";
import { cn } from "@/lib/utils";
import type { ChatHistoryMsg, ChapterCommitResult } from "@/types";
import {
  createPresetPhrase, deleteChatSession, deletePresetPhrase, estimateTokens,
  getChatMessages, getChatSessionStatus, getLLMConfig, listChatSessions,
  listPresetPhrases, sendChatMessageStream, updatePresetPhrase, uploadChatAttachment,
  type ChatTarget, type DFChatAction, type DFChatMessage, type DFChatSession,
  type LLMConfigInfo, type PresetPhrase,
} from "../df/components/chat/api";
import TokenMonitor, { type TokenStats } from "../df/components/chat/TokenMonitor";
import Composer from "../df/components/chat/Composer";
import ModelSwitcher from "../df/components/chat/ModelSwitcher";
import PresetPhraseDialog, { type PresetPhraseInput } from "../df/components/chat/PresetPhraseDialog";
import ConfirmDialog from "../df/components/chat/ConfirmDialog";
import SidePanel, { type SidePanelTab } from "../df/components/chat/SidePanel";

function errorMessage(e: unknown): string {
  return e instanceof Error ? e.message : String(e);
}

function formatElapsed(seconds: number): string {
  const m = Math.floor(seconds / 60);
  const s = seconds % 60;
  return `${m}分${s}秒`;
}

type ChatMode = "chat" | "creative";
type CreativeSubMode = "qa" | "free";

export default function ChatPage() {
  const { projectId, project } = useCurrentProject();
  const store = useAppStore();
  const { showSuccess, showError } = useToast();

  // ---------- 模式切换 ----------
  const [mode, setMode] = useState<ChatMode>("chat");
  const [creativeSubMode, setCreativeSubMode] = useState<CreativeSubMode>("qa");

  // ---------- 对话模式：会话/消息 ----------
  const [sessions, setSessions] = useState<DFChatSession[]>([]);
  const [messageCounts, setMessageCounts] = useState<Record<string, number>>({});
  const [activeSessionId, setActiveSessionId] = useState<string | null>(null);
  const [draftNew, setDraftNew] = useState<{ objectId: string; title: string } | null>(null);
  const [messages, setMessages] = useState<DFChatMessage[]>([]);
  const [loadingHistory, setLoadingHistory] = useState(false);
  const [historyError, setHistoryError] = useState<string | null>(null);
  const [historyReloadToken, setHistoryReloadToken] = useState(0);
  const [streaming, setStreaming] = useState(false);
  const [streamReasoning, setStreamReasoning] = useState("");
  const abortRef = useRef<AbortController | null>(null);

  // ---------- 交互创作：store 驱动 ----------
  const interactiveMessages = store.interactiveMessages;
  const interactiveInput = store.interactiveInput;
  const interactiveGenerating = store.interactiveGenerating;
  const interactiveReconnecting = store.interactiveReconnecting;
  const interactiveElapsed = store.interactiveElapsed;
  const streamThinking = store.interactiveStreamThinking;
  const streamContent = store.interactiveStreamContent;
  const streamReasoningContent = store.interactiveStreamReasoning;
  const streamType = store.interactiveStreamType;
  const streamActions = store.interactiveStreamActions;
  const streamOptions = store.interactiveStreamOptions;

  const creativeScrollRef = useRef<HTMLDivElement | null>(null);
  const creativeInputRef = useRef<HTMLTextAreaElement | null>(null);
  const [autoScroll, setAutoScroll] = useState(true);
  const [reasoningCollapsed, setReasoningCollapsed] = useState(false);
  const optionHandlerRef = useRef<(msgIdx: number, opt: { label: string; value: string }) => void>(() => {});

  const nextChapter = useMemo(() => {
    const chapterMsgs = interactiveMessages.filter((m) => m.msg_type === "chapter" && m.chapter);
    if (chapterMsgs.length > 0) return Math.max(...chapterMsgs.map((m) => m.chapter!)) + 1;
    if (store.chapters.length === 0) return 1;
    return Math.max(...store.chapters.map((c) => c.chapter)) + 1;
  }, [interactiveMessages, store.chapters]);

  // ---------- 其他 UI 状态 ----------
  const isMobile = useMediaQuery("(max-width: 767px)");
  const [sidePanelOpen, setSidePanelOpen] = useState(false);
  const [actionError, setActionError] = useState<string | null>(null);
  const [monitoringCollapsed, setMonitoringCollapsed] = useState(true);
  const [sideTab, setSideTab] = useState<SidePanelTab>("sessions");
  const [presetPhrases, setPresetPhrases] = useState<PresetPhrase[]>([]);
  const [presetDialogOpen, setPresetDialogOpen] = useState(false);
  const [llmConfig, setLlmConfig] = useState<LLMConfigInfo | null>(null);
  const [attaching, setAttaching] = useState(false);
  const [insertRequest, setInsertRequest] = useState<{ text: string; nonce: number } | null>(null);
  const [confirmDialog, setConfirmDialog] = useState<{
    open: boolean; title: string; message: string; onConfirm: () => void;
  }>({ open: false, title: "", message: "", onConfirm: () => {} });

  const visibleSessions = useMemo(
    () => sessions
      .filter((s) => s.session_type !== "interactive")
      .sort((a, b) => (b.updated_at || "").localeCompare(a.updated_at || "")),
    [sessions]
  );
  const globalSession = useMemo(
    () => visibleSessions.find((s) => s.session_type === "global") ?? null,
    [visibleSessions]
  );
  const activeSession = useMemo(() => {
    if (draftNew) return null;
    if (activeSessionId) return visibleSessions.find((s) => s.id === activeSessionId) ?? null;
    return globalSession;
  }, [draftNew, activeSessionId, visibleSessions, globalSession]);

  const conversationKey = draftNew
    ? `draft-${draftNew.objectId}`
    : activeSession?.id ?? "global-new";

  const visibleSessionRef = useRef<string | null>(null);
  visibleSessionRef.current = activeSession?.id ?? null;

  // ---------- 数据加载 ----------
  const loadSessions = useCallback(async (withCounts: boolean) => {
    if (!projectId) return;
    try {
      const list = await listChatSessions(projectId);
      setSessions(list);
      if (withCounts) {
        const counts: Record<string, number> = {};
        await Promise.all(
          list.filter((s) => s.session_type !== "interactive").map(async (s) => {
            try { counts[s.id] = (await getChatMessages(projectId, s.id)).length; } catch { counts[s.id] = 0; }
          })
        );
        setMessageCounts(counts);
      }
    } catch (e) { setActionError("加载会话列表失败：" + errorMessage(e)); }
  }, [projectId]);

  useEffect(() => { void loadSessions(true); }, [loadSessions]);

  useEffect(() => {
    listPresetPhrases().then(setPresetPhrases).catch(() => {});
    getLLMConfig().then(setLlmConfig).catch(() => {});
  }, []);

  const pollUntilIdle = useCallback(async (sessionId: string) => {
    for (let i = 0; i < 150; i++) {
      await new Promise((r) => setTimeout(r, 2000));
      try { const status = await getChatSessionStatus(sessionId); if (!status.busy) break; } catch { break; }
    }
    if (!projectId || visibleSessionRef.current !== sessionId) return;
    try {
      const msgs = await getChatMessages(projectId, sessionId);
      setMessages(msgs);
      setMessageCounts((prev) => ({ ...prev, [sessionId]: msgs.length }));
    } catch {}
  }, [projectId]);

  useEffect(() => {
    if (mode !== "chat") return;
    if (!projectId || draftNew) { if (draftNew) { setMessages([]); setHistoryError(null); } return; }
    if (!activeSession) { setMessages([]); setHistoryError(null); return; }
    const sessionId = activeSession.id;
    let cancelled = false;
    setLoadingHistory(true);
    setHistoryError(null);
    getChatMessages(projectId, sessionId)
      .then((msgs) => {
        if (cancelled) return;
        setMessages(msgs);
        setMessageCounts((prev) => ({ ...prev, [sessionId]: msgs.length }));
        getChatSessionStatus(sessionId)
          .then((st) => { if (st.busy && !cancelled) void pollUntilIdle(sessionId); })
          .catch(() => {});
      })
      .catch((e) => {
        if (cancelled) return;
        setHistoryError(errorMessage(e) || "加载消息失败");
        // 会话已被删除时自动恢复：刷新会话列表并清除过期 session ID
        const status = (e as any)?.status ?? (e as any)?.statusCode;
        if (status === 404) {
          setActiveSessionId(null);
          setMessages([]);
          void loadSessions(false);
        }
      })
      .finally(() => { if (!cancelled) setLoadingHistory(false); });
    return () => { cancelled = true; };
  }, [projectId, activeSession, draftNew, historyReloadToken, pollUntilIdle, mode]);

  // ---------- 交互创作：加载历史 + 自动保存 ----------
  useEffect(() => {
    if (mode !== "creative" || !project) return;
    store.interactiveLoadMessages(project.id);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [mode, project?.id]);

  const creativeSaveTimeout = useRef<ReturnType<typeof setTimeout> | null>(null);
  const interactiveMessagesRef = useRef(interactiveMessages);
  interactiveMessagesRef.current = interactiveMessages;
  useEffect(() => {
    if (mode !== "creative" || !project || store.interactiveLoadedProjectId !== project.id) return;
    const proj = project;
    if (creativeSaveTimeout.current) clearTimeout(creativeSaveTimeout.current);
    creativeSaveTimeout.current = setTimeout(() => {
      store.interactiveSaveMessages(proj.id, interactiveMessagesRef.current);
    }, 2000);
    return () => { if (creativeSaveTimeout.current) { clearTimeout(creativeSaveTimeout.current); creativeSaveTimeout.current = null; } };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [interactiveMessages, project?.id, mode]);

  useEffect(() => {
    return () => {
      if (project) {
        const proj = project;
        if (interactiveMessagesRef.current.length > 0) {
          store.interactiveSaveMessages(proj.id, interactiveMessagesRef.current);
        }
      }
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [mode, project?.id]);

  // 滚动逻辑
  const handleCreativeScroll = () => {
    const el = creativeScrollRef.current; if (!el) return;
    setAutoScroll(el.scrollHeight - el.scrollTop - el.clientHeight < 80);
  };
  useEffect(() => {
    if (autoScroll && creativeScrollRef.current) {
      creativeScrollRef.current.scrollTop = creativeScrollRef.current.scrollHeight;
    }
  }, [interactiveMessages, interactiveGenerating, streamContent, streamReasoningContent, streamActions, autoScroll]);
  useEffect(() => { if (streamContent) setReasoningCollapsed(true); }, [streamContent]);
  useEffect(() => { if (interactiveGenerating && !streamContent) setReasoningCollapsed(false); }, [interactiveGenerating, streamContent]);

  useEffect(() => {
    if (mode !== "creative") return;
    const handler = (e: KeyboardEvent) => {
      const tag = (e.target as HTMLElement)?.tagName;
      if (tag === "INPUT" || tag === "TEXTAREA") return;
      const msgs = interactiveMessagesRef.current;
      let targetIdx = -1;
      for (let i = msgs.length - 1; i >= 0; i--) {
        if (msgs[i].options && msgs[i].options!.length > 0 && !msgs[i].selectedOption) { targetIdx = i; break; }
      }
      if (targetIdx < 0) return;
      const opts = msgs[targetIdx].options!;
      const num = parseInt(e.key);
      if (num >= 1 && num <= opts.length) { e.preventDefault(); optionHandlerRef.current(targetIdx, opts[num - 1]); }
    };
    window.addEventListener("keydown", handler);
    return () => window.removeEventListener("keydown", handler);
  }, [mode]);

  // 移动端会话抽屉：Esc 关闭
  useEffect(() => {
    if (!sidePanelOpen) return;
    const handler = (e: KeyboardEvent) => { if (e.key === "Escape") setSidePanelOpen(false); };
    window.addEventListener("keydown", handler);
    return () => window.removeEventListener("keydown", handler);
  }, [sidePanelOpen]);

  // ---------- 对话模式：发送/停止 ----------
  const sendMessage = useCallback(async (text: string) => {
    if (!projectId || streaming) return;
    const target: ChatTarget = draftNew
      ? { session_type: "object", object_type: "chat", object_id: draftNew.objectId, title: draftNew.title }
      : activeSession
        ? { session_type: activeSession.session_type, object_type: activeSession.object_type, object_id: activeSession.object_id, title: activeSession.title }
        : { session_type: "global", object_type: "", object_id: "", title: project?.title || "全局对话" };

    const userMsg: DFChatMessage = { id: `user-${Date.now()}`, session_id: "", role: "user", content: text, actions: [], created_at: new Date().toISOString() };
    const assistantId = `assistant-${Date.now()}`;
    let assistantText = "";
    const actions: DFChatAction[] = [];
    let steered = false;

    setMessages((prev) => [...prev, userMsg]);
    setStreaming(true);
    setStreamReasoning("");
    setActionError(null);
    const controller = new AbortController();
    abortRef.current = controller;

    const patchAssistant = () => {
      setMessages((prev) => {
        const without = prev.filter((m) => m.id !== assistantId);
        return [...without, { id: assistantId, session_id: "", role: "assistant" as const, content: assistantText, actions: [...actions], created_at: new Date().toISOString() }];
      });
    };

    try {
      await sendChatMessageStream(projectId, target, text, {
        onChunk: (c) => { assistantText += c; patchAssistant(); },
        onReasoning: (c) => setStreamReasoning((prev) => prev + c),
        onAction: (a) => { actions.push(a); patchAssistant(); },
        onSteered: () => { steered = true; setActionError("会话正在生成中，消息已注入当前回合"); },
      }, controller.signal);
    } catch (e) {
      if (!controller.signal.aborted) setActionError("发送失败：" + errorMessage(e));
    } finally {
      setStreaming(false);
      abortRef.current = null;
      setStreamReasoning("");
      try {
        const list = await listChatSessions(projectId);
        setSessions(list);
        const found = list.find((s) => s.session_type === target.session_type && s.object_type === target.object_type && s.object_id === target.object_id);
        if (draftNew && found) { setDraftNew(null); setActiveSessionId(found.id); }
        const stillVisible = found && visibleSessionRef.current === found.id;
        if (found && (stillVisible || (draftNew && visibleSessionRef.current === null))) {
          const msgs = await getChatMessages(projectId, found.id);
          setMessages(msgs);
          setMessageCounts((prev) => ({ ...prev, [found.id]: msgs.length }));
        }
        if (steered && found) void pollUntilIdle(found.id);
      } catch {}
    }
  }, [projectId, streaming, draftNew, activeSession, project, pollUntilIdle]);

  const handleAbort = useCallback(() => { abortRef.current?.abort(); }, []);

  // ---------- 交互创作：发送/停止/决策 ----------
  const buildHistory = (): ChatHistoryMsg[] => interactiveMessages.map((m) => ({
    role: m.role, content: m.content, msg_type: m.msg_type,
    chapter: m.chapter ?? null, title: m.title ?? null,
    brief: m.brief ?? null, suggested_next: m.suggested_next ?? null,
  }));

  const handleCreativeSend = async (overrideText?: string) => {
    if (!project || interactiveGenerating) return;
    const text = (overrideText ?? interactiveInput).trim();
    if (creativeSubMode === "qa" && !text) { showError("请输入消息"); return; }
    await store.interactiveSend(project.id, text, buildHistory(), creativeSubMode);
  };

  const handleOptionClick = async (msgIdx: number, opt: { label: string; value: string }) => {
    store.updateInteractiveMessage(msgIdx, (m) => ({ ...m, selectedOption: opt.value }));
    await handleCreativeSend(opt.value);
  };
  optionHandlerRef.current = handleOptionClick;

  const handleReviewDecision = async (idx: number, decision: "approve" | "rewrite" | "polish", feedback?: string) => {
    const msg = interactiveMessages[idx];
    if (!project || !msg || !msg.threadId || !msg.reviewPending || msg.committing) return;
    await store.interactiveResume(project.id, msg.threadId, decision, feedback || "", msg.deepPolish || false, idx);
  };

  const handleSelectVariant = async (idx: number, variantIndex: number) => {
    const msg = interactiveMessages[idx];
    if (!project || !msg || !msg.threadId || !msg.awaitingVariant || msg.committing) return;
    await store.interactiveVariantResume(project.id, msg.threadId, variantIndex, idx);
  };

  const handleCreativeStop = () => store.interactiveStop();

  const handleCreativeKeyDown = (e: React.KeyboardEvent<HTMLTextAreaElement>) => {
    if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); handleCreativeSend(); }
  };

  const adjustCreativeInputHeight = () => {
    const el = creativeInputRef.current; if (!el) return;
    el.style.height = "auto";
    el.style.height = Math.min(el.scrollHeight, 200) + "px";
  };
  useEffect(() => { adjustCreativeInputHeight(); }, [interactiveInput]);

  const handleCommit = async (idx: number) => {
    const msg = interactiveMessages[idx];
    if (!project || !msg || msg.msg_type !== "chapter" || !msg.chapter || msg.committed || msg.committing) return;
    store.updateInteractiveMessage(idx, (m) => ({ ...m, committing: true }));
    try {
      const res: ChapterCommitResult = await api.commitChapter(project.id, msg.chapter);
      if (res.committed) {
        const parts: string[] = [];
        if (res.summary) parts.push(`摘要：${res.summary}`);
        if (res.deltas) parts.push(`状态变更 ${res.deltas} 项`);
        if (res.new_characters) parts.push(`新角色 ${res.new_characters} 个`);
        if (res.relationships) parts.push(`关系 ${res.relationships} 条`);
        if (res.events) parts.push(`事件 ${res.events} 个`);
        if (res.foreshadow_updates) parts.push(`伏笔更新 ${res.foreshadow_updates} 条`);
        if (res.new_factions) parts.push(`新势力 ${res.new_factions} 个`);
        if (res.new_monsters) parts.push(`新怪物 ${res.new_monsters} 个`);
        if (res.new_world_settings) parts.push(`新设定 ${res.new_world_settings} 条`);
        const resultText = parts.length > 0 ? parts.join("；") : "无数据变更";
        store.updateInteractiveMessage(idx, (m) => ({ ...m, committed: true, committing: false, commitResult: resultText }));
        showSuccess(`第 ${msg.chapter} 章已提交`);
        // 提交成功：刷新章节列表 + 全部 bible 实体，并通知各页面（百科/时间线/图谱）数据已变更
        store.refreshAssets().catch(() => {});
        bumpDataVersion("bible");
        bumpDataVersion("chapters");
      } else {
        const issues = (res as any).validation_issues;
        const issueText = issues && Array.isArray(issues) && issues.length > 0
          ? issues.map((v: any) => `[${v.severity}] ${v.message}`).join("；")
          : "未知原因";
        store.updateInteractiveMessage(idx, (m) => ({ ...m, committing: false, commitResult: `提交被阻止：${issueText}` }));
        showError(`提交被阻止：${issueText}`);
      }
    } catch (e: any) {
      store.updateInteractiveMessage(idx, (m) => ({ ...m, committing: false, commitResult: `提交失败：${e.message}` }));
      showError("提交失败：" + e.message);
    }
  };

  const toggleExpand = (idx: number) => {
    store.updateInteractiveMessage(idx, (m) => ({ ...m, expanded: !m.expanded }));
  };

  // ---------- 会话操作 ----------
  const handleNewSession = useCallback(() => {
    setActiveSessionId(null);
    setDraftNew({
      objectId: `chat-${Date.now()}`,
      title: `新会话 ${new Date().toLocaleTimeString("zh-CN", { hour: "2-digit", minute: "2-digit" })}`,
    });
    setMessages([]);
    setHistoryError(null);
  }, []);

  const handleSelectSession = useCallback((id: string) => {
    setDraftNew(null);
    setActiveSessionId(id);
  }, []);

  const handleDeleteSession = useCallback((id: string) => {
    if (!projectId) return;
    const session = sessions.find((s) => s.id === id);
    setConfirmDialog({
      open: true,
      title: "删除会话",
      message: `确定要删除会话「${session?.title || id}」吗？此操作不可恢复。`,
      onConfirm: async () => {
        try {
          await deleteChatSession(projectId, id);
          if (activeSessionId === id) { setActiveSessionId(null); setMessages([]); }
          setMessageCounts((prev) => { const next = { ...prev }; delete next[id]; return next; });
          await loadSessions(false);
        } catch { setActionError("删除会话失败，请重试"); }
      },
    });
  }, [projectId, sessions, activeSessionId, loadSessions]);

  // ---------- 预设短语 ----------
  const handlePresetClick = useCallback((phrase: PresetPhrase) => { void sendMessage(phrase.text); }, [sendMessage]);
  const handleSavePreset = useCallback(async (id: string | null, input: PresetPhraseInput) => {
    try {
      if (id) { const updated = await updatePresetPhrase(id, input); setPresetPhrases((prev) => prev.map((p) => (p.id === id ? updated : p))); }
      else { const created = await createPresetPhrase(input); setPresetPhrases((prev) => [...prev, created]); }
    } catch (e) { setActionError("保存预设短语失败，请重试"); throw e; }
  }, []);
  const handleDeletePreset = useCallback(async (id: string) => {
    try { await deletePresetPhrase(id); setPresetPhrases((prev) => prev.filter((p) => p.id !== id)); }
    catch { setActionError("删除预设短语失败，请重试"); }
  }, []);

  // ---------- 附件上传 ----------
  const handleAttach = useCallback(async (file: File) => {
    if (!projectId) return;
    setAttaching(true);
    try {
      const result = await uploadChatAttachment(projectId, activeSession?.id || "shared", file);
      setInsertRequest({ text: `[附件：${result.filename}]`, nonce: Date.now() });
    } catch (e) { setActionError("附件上传失败：" + errorMessage(e)); }
    finally { setAttaching(false); }
  }, [projectId, activeSession]);

  // ---------- Token 监控 ----------
  const tokenStats = useMemo<TokenStats | null>(() => {
    if (messages.length === 0) return null;
    let userTokens = 0, assistantTokens = 0, callCount = 0;
    for (const m of messages) {
      if (m.role === "user") userTokens += estimateTokens(m.content);
      else if (m.role === "assistant") { assistantTokens += estimateTokens(m.content); callCount += 1; }
    }
    return { systemTokens: 600, userTokens, assistantTokens, callCount, model: llmConfig?.model || "", maxContext: llmConfig?.context_length || 128000 };
  }, [messages, llmConfig]);

  // ---------- 渲染 ----------
  const canSend = Boolean(projectId) && !streaming;
  const placeholder = draftNew
    ? "输入消息以创建新会话... (Shift+Enter 换行)"
    : "输入消息... (Shift+Enter 换行)";

  const chatEmptyState = (
    <div className="flex flex-col items-center justify-center h-64 text-center" role="status" aria-label="暂无消息">
      <div className="mb-4 h-16 w-16 animate-float motion-reduce:animate-none">
        <MessageSquare className="h-full w-full text-muted" />
      </div>
      <h2 className="text-xl font-semibold text-foreground mb-2">对话模式</h2>
      <p className="text-muted text-sm">输入消息开始对话，或切换到「交互创作」模式生成章节</p>
    </div>
  );

  // 交互创作空状态
  const creativeEmptyState = (
    <div className="flex flex-col items-center justify-center gap-3 py-20 text-center text-muted">
      <div className="text-4xl">✍️</div>
      <div className="text-sm font-semibold text-foreground">交互式创作</div>
      <div className="max-w-md text-xs leading-relaxed">
        {creativeSubMode === "qa"
          ? "和 AI 一问一答地创作。描述你想要的剧情，AI 生成章节；也可以直接问 AI 关于角色、设定的问题。"
          : "自由模式下，每次发消息 AI 都会生成下一章。也可以直接点发送让 AI 自主推进剧情。"}
      </div>
      <div className="mt-2 text-xs text-muted/70">已有 {store.chapters.length} 章，将从第 {nextChapter} 章接续</div>
      {creativeSubMode === "qa" && (
        <div className="mt-4 flex flex-wrap justify-center gap-2">
          {["写第一章，主角在废土黑市被城防军盯上", "林深的能力是什么？帮我梳理一下", "下一章让他遇到神秘少女"].map((s) => (
            <button key={s} type="button" onClick={() => store.setInteractiveInput(s)}
              className="rounded-full border border-border bg-surface px-3 py-1 text-xs text-muted hover:text-foreground hover:border-border-strong transition-colors">
              {s}
            </button>
          ))}
        </div>
      )}
    </div>
  );

  return (
    <AppLayout>
      <div className="h-full flex">
        {/* 左侧：Token 监控竖栏 */}
        <div className={`shrink-0 flex flex-col transition-all duration-300 ${monitoringCollapsed ? "w-7" : "w-64"}`} role="complementary" aria-label="Token 监控面板">
          <div className={`h-full ${monitoringCollapsed ? "px-1" : "px-2"} py-3 overflow-y-auto`}>
            <TokenMonitor stats={tokenStats} collapsed={monitoringCollapsed} onToggle={() => setMonitoringCollapsed((v) => !v)} />
          </div>
        </div>

        {/* 中间：主聊天区 */}
        <div className="flex-1 flex flex-col min-w-0 min-h-0" role="main" aria-label="聊天区域">
          {/* 模式切换栏 */}
          <div className="flex flex-wrap items-center justify-between gap-2 border-b border-border px-4 py-2">
            <div className="flex gap-1 rounded-xl border border-border bg-surface p-0.5">
              <button type="button" onClick={() => setMode("chat")}
                className={cn("rounded-lg px-3 py-1 text-xs font-semibold transition-all flex items-center gap-1.5",
                  mode === "chat" ? "bg-primary text-primary-foreground shadow-sm" : "text-muted hover:text-foreground")}>
                <MessageSquare className="h-3.5 w-3.5" /> 对话
              </button>
              <button type="button" onClick={() => setMode("creative")}
                className={cn("rounded-lg px-3 py-1 text-xs font-semibold transition-all flex items-center gap-1.5",
                  mode === "creative" ? "bg-primary text-primary-foreground shadow-sm" : "text-muted hover:text-foreground")}>
                <PenLine className="h-3.5 w-3.5" /> 交互创作
              </button>
            </div>

            {mode === "creative" && (
              <div className="flex flex-wrap items-center gap-2">
                <span className="text-xs text-muted flex items-center gap-1">模式</span>
                <div className="flex gap-1 rounded-xl border border-border bg-surface p-0.5">
                  <button type="button" onClick={() => setCreativeSubMode("qa")}
                    className={cn("rounded-lg px-3 py-1 text-xs font-semibold transition-all",
                      creativeSubMode === "qa" ? "bg-primary text-primary-foreground shadow-sm" : "text-muted hover:text-foreground")}>
                    问答
                  </button>
                  <button type="button" onClick={() => setCreativeSubMode("free")}
                    className={cn("rounded-lg px-3 py-1 text-xs font-semibold transition-all",
                      creativeSubMode === "free" ? "bg-primary text-primary-foreground shadow-sm" : "text-muted hover:text-foreground")}>
                    自由
                  </button>
                </div>
                {/* MVP 26-agent 工作流模式开关 */}
                <button
                  type="button"
                  onClick={() => {
                    const next = !store.interactiveUseWorkflow;
                    store.toggleInteractiveUseWorkflow(next);
                    if (next) {
                      showSuccess("已开启 26-Agent 模式：质量更高，但单章约 10-25 分钟、消耗更多 token，适合关键章节");
                    }
                  }}
                  title={store.interactiveUseWorkflow
                    ? "MVP 工作流模式已开启：创作指令将触发 26-agent 管线（含资产桥接 DB↔文件），质量更高但耗时更长（约 10-25 分钟，消耗更多 token）"
                    : "开启 MVP 工作流模式：创作指令触发 26-agent 管线（含资产桥接），质量更高但耗时更长"}
                  className={cn(
                    "rounded-lg px-2.5 py-1 text-xs font-semibold transition-all flex items-center gap-1 border",
                    store.interactiveUseWorkflow
                      ? "bg-amber-500/15 text-amber-600 border-amber-500/30 dark:text-amber-400"
                      : "text-muted hover:text-foreground border-border bg-surface"
                  )}
                >
                  <Zap className="h-3 w-3" />
                  {store.interactiveUseWorkflow ? "26-Agent" : "单Agent"}
                </button>
                {store.interactiveUseWorkflow && (
                  <span className="text-[10px] text-amber-600 dark:text-amber-400 leading-tight">
                    更慢更贵·质量更高
                    <br />适合关键章节
                  </span>
                )}
                {/* 抽卡模式：一次生成 N 个候选版本 */}
                <div className="flex items-center gap-1">
                  <span className="text-xs text-muted flex items-center gap-1" title="抽卡模式：一次生成 N 个候选版本，选择一版后继续润色→审校→人审">
                    <Sparkles className="h-3 w-3" /> 抽卡
                  </span>
                  <div className="flex gap-1 rounded-xl border border-border bg-surface p-0.5">
                    {[1, 2, 3].map((n) => (
                      <button key={n} type="button" onClick={() => store.setInteractiveNumVariants(n)}
                        title={n === 1 ? "关闭抽卡（生成 1 版）" : `抽卡模式：生成 ${n} 个候选版本供选择`}
                        className={cn("rounded-lg px-2.5 py-1 text-xs font-semibold transition-all",
                          store.interactiveNumVariants === n ? "bg-primary text-primary-foreground shadow-sm" : "text-muted hover:text-foreground")}>
                        {n}
                      </button>
                    ))}
                  </div>
                  {store.interactiveNumVariants > 1 && (
                    <span className="text-[10px] text-primary leading-tight">
                      一次{store.interactiveNumVariants}选1
                      <br />耗时×{store.interactiveNumVariants}
                    </span>
                  )}
                </div>
                <span className="rounded-md bg-foreground/5 px-2 py-0.5 text-xs text-muted">下一章：第 {nextChapter} 章</span>
              </div>
            )}

            {mode === "chat" && isMobile && (
              <button
                type="button"
                onClick={() => setSidePanelOpen(true)}
                className="flex items-center gap-1.5 rounded-lg border border-border bg-surface px-3 py-1 text-xs font-semibold text-muted transition-colors hover:text-foreground cursor-pointer min-h-[44px]"
                aria-label="打开会话列表"
              >
                <MessageSquare className="h-3.5 w-3.5" /> 会话
              </button>
            )}
          </div>

          {/* === 对话模式消息区 === */}
          {mode === "chat" && (
            <>
              <MessageTimelineLite
                messages={messages}
                streaming={streaming}
                streamReasoning={streamReasoning}
                loading={loadingHistory}
                error={historyError}
                onRetry={() => setHistoryReloadToken((v) => v + 1)}
                emptyState={chatEmptyState}
              />
              <div className="px-6 pb-4">
                <div className="w-full max-w-4xl mx-auto">
                  <Composer
                    onSend={(text) => void sendMessage(text)}
                    onAbort={handleAbort}
                    streaming={streaming}
                    sendEnabled={canSend}
                    placeholder={placeholder}
                    presetPhrases={presetPhrases}
                    onPresetClick={handlePresetClick}
                    onOpenPresetEditor={() => setPresetDialogOpen(true)}
                    onAttach={(file) => void handleAttach(file)}
                    attaching={attaching}
                    conversationKey={conversationKey}
                    insertRequest={insertRequest}
                    trailingControls={
                      <ModelSwitcher config={llmConfig} disabled={streaming} onSwitched={setLlmConfig} onError={(msg) => setActionError(msg)} />
                    }
                  />
                </div>
              </div>
            </>
          )}

          {/* === 交互创作消息区 === */}
          {mode === "creative" && (
            <>
              <div ref={creativeScrollRef} onScroll={handleCreativeScroll} className="flex-1 overflow-y-auto">
                {!autoScroll && (
                  <button onClick={() => { setAutoScroll(true); creativeScrollRef.current?.scrollTo({ top: creativeScrollRef.current.scrollHeight, behavior: "smooth" }); }}
                    className="fixed bottom-24 left-1/2 -translate-x-1/2 z-10 rounded-full border border-border bg-surface shadow-lg px-3 py-1.5 text-xs hover:bg-surface-elevated">
                    ↓ 回到底部
                  </button>
                )}
                <div className="mx-auto max-w-3xl px-4 py-6">
                  {interactiveMessages.length === 0 && !interactiveGenerating ? (
                    creativeEmptyState
                  ) : (
                    <div className="flex flex-col gap-4">
                      {interactiveMessages.map((msg, idx) => (
                        <CreativeMessageBubble
                          key={idx}
                          msg={msg}
                          onToggleExpand={() => toggleExpand(idx)}
                          onCommit={() => handleCommit(idx)}
                          onReviewDecision={(decision, feedback) => handleReviewDecision(idx, decision, feedback)}
                          onSelectVariant={(variantIndex) => handleSelectVariant(idx, variantIndex)}
                          onOptionClick={(opt) => handleOptionClick(idx, opt)}
                          onToggleRewriteInput={() => store.updateInteractiveMessage(idx, (m) => ({ ...m, showRewriteInput: !m.showRewriteInput }))}
                          onUpdateRewriteFeedback={(text) => store.updateInteractiveMessage(idx, (m) => ({ ...m, rewriteFeedback: text }))}
                          onToggleDeepPolish={() => store.updateInteractiveMessage(idx, (m) => ({ ...m, deepPolish: !m.deepPolish }))}
                          onResetCommitting={() => store.updateInteractiveMessage(idx, (m) => ({ ...m, committing: false }))}
                        />
                      ))}

                      {interactiveReconnecting && (
                        <div className="flex items-center gap-2 text-sm text-amber-500 px-4 py-2">
                          <Loader2 className="w-4 h-4 animate-spin" />
                          <span>连接中断，正在重连...</span>
                        </div>
                      )}

                      {(interactiveGenerating || streamOptions.length > 0) && (
                        <div className="flex items-start gap-3">
                          <div className="flex h-8 w-8 shrink-0 items-center justify-center rounded-full bg-primary/10 text-sm">🤖</div>
                          <div className="flex-1 rounded-2xl rounded-tl-sm border border-border bg-surface overflow-hidden">
                            {streamThinking.length > 0 && (
                              <div className="border-b border-border bg-surface-elevated/50 px-4 py-2 max-h-[200px] overflow-y-auto">
                                {streamThinking.map((t, i) => (
                                  <div key={i} className="flex items-start gap-2 py-0.5 text-xs">
                                    <span className="text-primary shrink-0">{i < streamThinking.length - 1 ? "✓" : "⟳"}</span>
                                    <span className={i < streamThinking.length - 1 ? "text-muted line-through" : "text-foreground font-medium"}>{t.stage}</span>
                                    <span className="text-muted/70 truncate">{t.detail}</span>
                                  </div>
                                ))}
                              </div>
                            )}
                            {streamActions.length > 0 && (
                              <div className="border-b border-border bg-muted/30 px-4 py-2 flex flex-wrap gap-1.5 max-h-[160px] overflow-y-auto">
                                {streamActions.map((a, i) => (
                                  <div key={i} className="flex items-center gap-2 px-2.5 py-1.5 rounded-lg bg-muted/30 text-xs">
                                    {a.status === "running" && <Loader2 className="w-3 h-3 animate-spin text-primary" />}
                                    {a.status === "done" && <CheckCircle2 className="w-3 h-3 text-green-500" />}
                                    {(a.status === "error" || a.status === "failed") && <XCircle className="w-3 h-3 text-red-500" />}
                                    <span className="font-medium">{a.type}</span>
                                  </div>
                                ))}
                              </div>
                            )}
                            {streamOptions.length > 0 && (
                              <div className="border-b border-border px-4 py-2 space-y-2">
                                {streamOptions.map((opt, i) => (
                                  <button key={i} type="button" title={opt.label} disabled
                                    className="w-full text-left px-3 py-2 rounded-lg border border-border text-sm line-clamp-2 opacity-60">
                                    {opt.label}
                                  </button>
                                ))}
                              </div>
                            )}
                            {streamReasoningContent && (
                              <div className="border-b border-border bg-muted/30 px-4 py-2">
                                <button type="button" onClick={() => setReasoningCollapsed((v) => !v)}
                                  className="flex w-full items-center gap-1.5 text-xs text-muted-foreground">
                                  {!streamContent && <Loader2 className="h-3 w-3 animate-spin" />}
                                  <span>{!streamContent ? "AI 思考中..." : "思考过程"}</span>
                                  <span className="ml-auto text-[10px] opacity-60">{reasoningCollapsed ? "展开" : "收起"}</span>
                                </button>
                                {!reasoningCollapsed && (
                                  <div className="mt-1 max-h-[200px] overflow-y-auto border-l-2 border-primary/40 pl-2 text-xs text-muted-foreground/70 whitespace-pre-wrap">
                                    {streamReasoningContent}
                                  </div>
                                )}
                              </div>
                            )}
                            {streamContent ? (
                              <div className="px-4 py-3">
                                {streamType === "chapter" && (
                                  <div className="mb-2 text-xs font-semibold text-primary">正在生成章节：{formatElapsed(interactiveElapsed)}</div>
                                )}
                                <div className="text-sm text-foreground/90 max-h-[400px] overflow-y-auto">
                                  <Markdown content={streamContent} />
                                  <span className="inline-block w-[2px] h-[1.1em] bg-primary animate-[blink_1s_steps(2)_infinite] align-text-bottom ml-0.5" />
                                </div>
                              </div>
                            ) : (
                              <div className="px-4 py-3">
                                <div className="flex items-center gap-2 text-sm text-muted">
                                  <span className="inline-block h-3 w-3 animate-spin rounded-full border-2 border-primary border-t-transparent" />
                                  {streamThinking.length > 0 ? streamThinking[streamThinking.length - 1].detail : "正在准备..."}
                                </div>
                              </div>
                            )}
                          </div>
                        </div>
                      )}
                    </div>
                  )}
                </div>
              </div>

              {/* 交互创作输入区 */}
              <div className="shrink-0 border-t border-border bg-surface-elevated px-4 py-3">
                <div className="mx-auto flex max-w-3xl items-end gap-2">
                  <div className="flex flex-1 items-end gap-2">
                    <Textarea
                      ref={creativeInputRef}
                      value={interactiveInput}
                      onChange={(e) => { store.setInteractiveInput(e.target.value); adjustCreativeInputHeight(); }}
                      onKeyDown={handleCreativeKeyDown}
                      placeholder={creativeSubMode === "qa"
                        ? "描述剧情走向、问 AI 问题…（Enter 发送，Shift+Enter 换行）"
                        : "留空直接发送 = AI 自主生成下一章；或输入额外要求…"}
                      className="min-h-[44px] flex-1 resize-none"
                      rows={1}
                      disabled={interactiveGenerating}
                    />
                    <HelpIcon title="输入框" content={`${helpTexts.interactive?.inputArea ?? ""}\n\n${helpTexts.interactive?.userReferences ?? ""}\n\n${helpTexts.interactive?.arcSplitCommand ?? ""}`} />
                  </div>
                  {interactiveGenerating ? (
                    <Button variant="danger" onClick={handleCreativeStop} className="h-[44px] shrink-0">停止</Button>
                  ) : (
                    <Button variant="primary" onClick={() => handleCreativeSend()}
                      disabled={creativeSubMode === "qa" && !interactiveInput.trim()} className="h-[44px] shrink-0">
                      发送
                    </Button>
                  )}
                </div>
              </div>
            </>
          )}
        </div>

        {/* 右侧：可拖拽侧边栏（桌面端内嵌 / 移动端抽屉） */}
        {mode === "chat" && projectId && !isMobile && (
          <SidePanel
            projectId={projectId}
            tab={sideTab}
            setTab={setSideTab}
            sessions={visibleSessions}
            messageCounts={messageCounts}
            activeSessionId={activeSession?.id ?? null}
            draftNew={Boolean(draftNew)}
            onSelectSession={handleSelectSession}
            onNewSession={handleNewSession}
            onDeleteSession={handleDeleteSession}
            llmConfig={llmConfig}
          />
        )}

        {/* 移动端：会话面板抽屉（覆盖式，避免挤压聊天区） */}
        {mode === "chat" && projectId && isMobile && sidePanelOpen && (
          <div className="fixed inset-0 z-50" role="dialog" aria-modal="true" aria-label="会话列表抽屉">
            <div className="absolute inset-0 bg-black/40" onClick={() => setSidePanelOpen(false)} aria-hidden="true" />
            <div className="absolute right-0 top-0 bottom-0 flex w-[85vw] max-w-[320px] flex-col shadow-xl">
              <SidePanel
                projectId={projectId}
                tab={sideTab}
                setTab={setSideTab}
                sessions={visibleSessions}
                messageCounts={messageCounts}
                activeSessionId={activeSession?.id ?? null}
                draftNew={Boolean(draftNew)}
                onSelectSession={(id) => { handleSelectSession(id); setSidePanelOpen(false); }}
                onNewSession={() => { handleNewSession(); setSidePanelOpen(false); }}
                onDeleteSession={handleDeleteSession}
                llmConfig={llmConfig}
              />
            </div>
          </div>
        )}

        {/* 预设短语编辑弹窗 */}
        <PresetPhraseDialog
          open={presetDialogOpen}
          phrases={presetPhrases}
          onClose={() => setPresetDialogOpen(false)}
          onSave={handleSavePreset}
          onDelete={handleDeletePreset}
        />

        {/* 确认对话框 */}
        <ConfirmDialog
          open={confirmDialog.open}
          title={confirmDialog.title}
          message={confirmDialog.message}
          onConfirm={() => { confirmDialog.onConfirm(); setConfirmDialog((prev) => ({ ...prev, open: false })); }}
          onCancel={() => setConfirmDialog((prev) => ({ ...prev, open: false }))}
        />

        {/* 右下角错误提示条 */}
        {actionError && (
          <div className="fixed bottom-4 right-4 z-50 max-w-sm bg-red-500/10 border border-red-500/30 rounded-lg px-4 py-3 flex items-center gap-3 shadow-lg"
            role="alert" aria-live="polite">
            <span className="text-xs text-red-300 flex-1">{actionError}</span>
            <button type="button" onClick={() => setActionError(null)}
              className="text-red-400 hover:text-red-300 cursor-pointer min-h-[44px] min-w-[44px] flex items-center justify-center"
              aria-label="关闭错误提示">
              <X size={14} aria-hidden="true" />
            </button>
          </div>
        )}
      </div>
    </AppLayout>
  );
}

// ── 对话模式轻量消息列表（避免引入 MessageTimeline 依赖的复杂性） ──
function MessageTimelineLite({
  messages, streaming, streamReasoning, loading, error, onRetry, emptyState,
}: {
  messages: DFChatMessage[];
  streaming: boolean;
  streamReasoning: string;
  loading: boolean;
  error: string | null;
  onRetry: () => void;
  emptyState: React.ReactNode;
}) {
  const scrollRef = useRef<HTMLDivElement | null>(null);
  useEffect(() => {
    if (scrollRef.current) scrollRef.current.scrollTop = scrollRef.current.scrollHeight;
  }, [messages, streaming, streamReasoning]);

  if (loading) {
    return <div className="flex-1 flex items-center justify-center"><Loader2 className="mr-2 h-5 w-5 animate-spin text-muted" /><span className="text-sm text-muted">正在加载消息...</span></div>;
  }
  if (error) {
    return (
      <div className="flex-1 flex flex-col items-center justify-center gap-2">
        <XCircle className="h-8 w-8 text-danger" />
        <p className="text-sm text-muted">{error}</p>
        <Button variant="outline" size="sm" onClick={onRetry}>重试</Button>
      </div>
    );
  }
  if (messages.length === 0 && !streaming) {
    return <div className="flex-1 overflow-y-auto">{emptyState}</div>;
  }
  return (
    <div ref={scrollRef} className="flex-1 overflow-y-auto">
      <div className="mx-auto max-w-4xl px-6 py-6 space-y-4">
        {messages.map((m) => {
          if (m.role === "user") {
            return (
              <div key={m.id} className="flex justify-end">
                <div className="max-w-[80%] rounded-2xl rounded-tr-sm bg-primary px-4 py-2 text-sm text-primary-foreground">
                  {m.content}
                </div>
              </div>
            );
          }
          return (
            <div key={m.id} className="flex items-start gap-3">
              <div className="flex h-8 w-8 shrink-0 items-center justify-center rounded-full bg-primary/10 text-sm">🤖</div>
              <div className="max-w-[80%] rounded-2xl rounded-tl-sm border border-border bg-surface px-4 py-2 text-sm text-foreground/90">
                <Markdown content={m.content} />
                {streamReasoning && streaming && m.id === messages[messages.length - 1]?.id && (
                  <div className="mt-2 border-t border-border pt-2 text-xs text-muted/70 whitespace-pre-wrap">{streamReasoning}</div>
                )}
              </div>
            </div>
          );
        })}
        {streaming && messages.length === 0 && (
          <div className="flex items-center gap-2 text-sm text-muted">
            <Loader2 className="h-4 w-4 animate-spin" /> 正在思考...
          </div>
        )}
      </div>
    </div>
  );
}

// ── 交互创作消息气泡（从 InteractivePage 移植） ──
function CreativeMessageBubble({
  msg,
  onToggleExpand,
  onCommit,
  onReviewDecision,
  onSelectVariant,
  onOptionClick,
  onToggleRewriteInput,
  onUpdateRewriteFeedback,
  onToggleDeepPolish,
  onResetCommitting,
}: {
  msg: import("@/types").ChatMessage;
  onToggleExpand: () => void;
  onCommit: () => void;
  onReviewDecision: (decision: "approve" | "rewrite" | "polish", feedback?: string) => void;
  onSelectVariant: (variantIndex: number) => void;
  onOptionClick: (opt: { label: string; value: string }) => void;
  onToggleRewriteInput: () => void;
  onUpdateRewriteFeedback: (text: string) => void;
  onToggleDeepPolish: () => void;
  onResetCommitting: () => void;
}) {
  const isUser = msg.role === "user";
  const showRewriteInput = msg.showRewriteInput || false;
  const rewriteFeedback = msg.rewriteFeedback || "";

  if (isUser) {
    return (
      <div className="flex justify-end">
        <div className="max-w-[80%] rounded-2xl rounded-tr-sm bg-primary px-4 py-2 text-sm text-primary-foreground">{msg.content}</div>
      </div>
    );
  }

  // AI 章节消息
  if (msg.msg_type === "chapter") {
    return (
      <div className="flex items-start gap-3">
        <div className="flex h-8 w-8 shrink-0 items-center justify-center rounded-full bg-primary/10 text-sm">🤖</div>
        <div className="min-w-0 flex-1 rounded-2xl rounded-tl-sm border border-border bg-surface">
          {/* 标题栏 */}
          <div className="flex items-center justify-between border-b border-border px-4 py-2">
            <div className="flex items-center gap-2 min-w-0">
              {msg.awaitingVariant ? (
                <span className="rounded-md bg-primary/15 px-2 py-0.5 text-xs font-semibold text-primary flex items-center gap-1">
                  🎴 抽卡候选
                </span>
              ) : (
                <span className="rounded-md bg-success/15 px-2 py-0.5 text-xs font-semibold text-success flex items-center gap-1">
                  第 {msg.chapter} 章
                  <HelpIcon title="章节卡片" content={helpTexts.interactive?.chapterCard ?? ""} size="sm" />
                </span>
              )}
              <span className="truncate text-sm font-semibold text-foreground">{msg.title || "无标题"}</span>
              {msg.isDraft && !msg.polished && !msg.committed && (
                <span className="rounded-md bg-warning/15 px-1.5 py-0.5 text-[10px] font-semibold text-warning">初稿</span>
              )}
              {msg.polished && !msg.committed && (
                <span className="rounded-md bg-info/15 px-1.5 py-0.5 text-[10px] font-semibold text-info">已润色</span>
              )}
              {msg.committed && (
                <span className="rounded-md bg-success/15 px-1.5 py-0.5 text-[10px] font-semibold text-success">已提交</span>
              )}
            </div>
            <div className="flex items-center gap-2 shrink-0">
              {msg.word_count != null && <span className="text-xs text-muted">{msg.word_count} 字</span>}
              <button type="button" onClick={onToggleExpand} className="rounded-md px-2 py-0.5 text-xs text-primary hover:bg-primary/10">
                {msg.expanded ? "收起" : "展开"}
              </button>
            </div>
          </div>

          {/* 抽卡候选版本卡片（等待用户选 1） */}
          {msg.awaitingVariant && msg.variants && msg.variants.length > 0 && (
            <div className="border-t border-border px-4 py-3">
              <div className="mb-2 flex items-center gap-2 text-xs font-semibold text-primary">
                <Sparkles className="h-3.5 w-3.5" /> 已生成 {msg.variants.length} 个候选版本，请选择一版后继续（润色→审校→人审）
              </div>
              {msg.committing ? (
                <div className="flex items-center gap-2 text-xs text-muted">
                  <span className="inline-block h-3 w-3 animate-spin rounded-full border-2 border-primary border-t-transparent" />
                  已选中版本，AI 工作室处理中...
                </div>
              ) : (
                <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
                  {msg.variants.map((v) => (
                    <div key={v.index} className="flex flex-col rounded-xl border border-border bg-surface p-3">
                      <div className="mb-1 flex items-center justify-between gap-2">
                        <span className="truncate text-sm font-semibold text-foreground">
                          <span className="text-muted font-normal">版本 {v.index + 1} · </span>
                          {v.title || "无标题"}
                        </span>
                        <span className="shrink-0 text-xs text-muted">{v.word_count} 字</span>
                      </div>
                      <p className="mb-2 line-clamp-3 text-xs leading-5 text-foreground/70 whitespace-pre-wrap">{v.content}</p>
                      <Button variant="primary" size="sm" className="h-7 w-full text-xs" onClick={() => onSelectVariant(v.index)}>
                        选这版
                      </Button>
                    </div>
                  ))}
                </div>
              )}
            </div>
          )}

          {/* 正文 */}
          {msg.expanded && msg.content && (
            <div className="max-h-[60vh] overflow-y-auto px-4 py-3">
              <div className="whitespace-pre-wrap text-[15px] leading-7 text-foreground/90">{msg.content}</div>
            </div>
          )}

          {/* AI 审校报告 */}
          {msg.auditReport && (
            <div className="border-t border-border bg-muted/30 px-4 py-3">
              <div className="mb-2 flex items-center gap-2">
                <HelpIcon title="AI 审校报告" content={helpTexts.interactive?.auditReport ?? ""} size="sm" />
                <span className={cn("rounded-md px-2 py-0.5 text-xs font-semibold",
                  msg.auditReport.passed ? "bg-success/15 text-success" : "bg-danger/15 text-danger")}>
                  {msg.auditReport.passed ? "✓ 审校通过" : "✗ 审校未通过"}
                </span>
                {msg.auditReport.overall_score != null && <span className="text-xs text-muted">综合评分：{msg.auditReport.overall_score}</span>}
              </div>
              {msg.auditReport.summary && <p className="mb-2 text-xs text-foreground/80">{msg.auditReport.summary}</p>}
              {msg.auditReport.user_perspective && (
                <div className="mb-1.5 flex items-start gap-2 text-xs">
                  <span className="shrink-0 font-semibold text-foreground/70">读者视角：</span>
                  <span className={msg.auditReport.user_perspective.passed ? "text-success" : "text-danger"}>
                    {msg.auditReport.user_perspective.score}分 {msg.auditReport.user_perspective.passed ? "✓" : "✗"}
                  </span>
                  {msg.auditReport.user_perspective.summary && <span className="text-muted">- {msg.auditReport.user_perspective.summary}</span>}
                </div>
              )}
              {msg.auditReport.expert_perspective && (
                <div className="mb-1.5 flex items-start gap-2 text-xs">
                  <span className="shrink-0 font-semibold text-foreground/70">专家视角：</span>
                  <span className={msg.auditReport.expert_perspective.passed ? "text-success" : "text-danger"}>
                    {msg.auditReport.expert_perspective.score}分 {msg.auditReport.expert_perspective.passed ? "✓" : "✗"}
                  </span>
                  {msg.auditReport.expert_perspective.summary && <span className="text-muted">- {msg.auditReport.expert_perspective.summary}</span>}
                </div>
              )}
              {msg.auditReport.editor_perspective && (
                <div className="mb-1.5 flex items-start gap-2 text-xs">
                  <span className="shrink-0 font-semibold text-foreground/70">编辑视角：</span>
                  <span className={msg.auditReport.editor_perspective.passed ? "text-success" : "text-danger"}>
                    {msg.auditReport.editor_perspective.score}分 {msg.auditReport.editor_perspective.passed ? "✓" : "✗"}
                  </span>
                  {msg.auditReport.editor_perspective.summary && <span className="text-muted">- {msg.auditReport.editor_perspective.summary}</span>}
                </div>
              )}
              {msg.auditReport.issues && msg.auditReport.issues.length > 0 && (
                <div className="mt-2 space-y-1">
                  <div className="text-xs font-semibold text-foreground/70">问题清单：</div>
                  {msg.auditReport.issues.slice(0, 8).map((issue, i) => (
                    <div key={i} className="flex items-start gap-1.5 text-xs">
                      <span className={cn("shrink-0 rounded px-1 py-0.5 font-semibold",
                        issue.severity === "critical" ? "bg-danger/15 text-danger"
                        : issue.severity === "high" ? "bg-warning/15 text-warning"
                        : "bg-muted text-muted")}>
                        {issue.severity || "minor"}
                      </span>
                      <span className="text-foreground/80">{issue.message}</span>
                    </div>
                  ))}
                  {msg.auditReport.issues.length > 8 && <div className="text-xs text-muted">...还有 {msg.auditReport.issues.length - 8} 个问题</div>}
                </div>
              )}
              {msg.auditReport.suggestions && msg.auditReport.suggestions.length > 0 && (
                <div className="mt-2 space-y-1">
                  <div className="text-xs font-semibold text-primary">改进建议：</div>
                  {msg.auditReport.suggestions.slice(0, 5).map((s, i) => <div key={i} className="text-xs text-foreground/80">- {s}</div>)}
                </div>
              )}
            </div>
          )}

          {/* 润色后处理 */}
          {msg.polished && msg.polishIssues && msg.polishIssues.length > 0 && (
            <div className="border-t border-border px-4 py-2">
              <div className="text-xs font-semibold text-muted">润色后处理：</div>
              <div className="mt-1 space-y-0.5">
                {msg.polishIssues.slice(0, 5).map((issue, i) => <div key={i} className="text-xs text-foreground/70">- {issue}</div>)}
              </div>
            </div>
          )}

          {/* 人审决策区 */}
          {msg.reviewPending && (
            <div className="border-t border-border bg-primary/5 px-4 py-3">
              {msg.polished && (
                <div className="mb-3 rounded-md bg-success/10 p-2">
                  <div className="flex items-center gap-1.5 text-xs font-semibold text-success">
                    <Sparkles className="h-3.5 w-3.5" /> 润色已完成，请重新审阅新版本
                  </div>
                </div>
              )}
              <div className="mb-2 flex items-center gap-2 text-xs font-semibold text-foreground">
                请审阅后选择下一步：
                <HelpIcon title="人审决策区" content={helpTexts.interactive?.reviewPending ?? ""} size="sm" />
              </div>
              {showRewriteInput ? (
                <div className="space-y-2">
                  <div className="flex items-center gap-1">
                    <span className="text-xs font-semibold text-foreground/70">重写意见</span>
                    <HelpIcon title="重写意见" content={helpTexts.interactive?.rewriteFeedback ?? ""} size="sm" />
                  </div>
                  <Textarea value={rewriteFeedback} onChange={(e) => onUpdateRewriteFeedback(e.target.value)}
                    placeholder="请输入修改意见，AI 会据此重写..." className="min-h-[60px] text-xs" />
                  <div className="flex gap-2">
                    <Button variant="primary" size="sm" className="h-7 px-3 text-xs" onClick={() => onReviewDecision("rewrite", rewriteFeedback)}>确认重写</Button>
                    <Button variant="ghost" size="sm" className="h-7 px-3 text-xs" onClick={() => onToggleRewriteInput()}>取消</Button>
                  </div>
                </div>
              ) : (
                <div className="space-y-2">
                  <div className="flex items-center gap-2">
                    <Switch id={`deep-polish-${msg.threadId}`} checked={msg.deepPolish || false} onCheckedChange={() => onToggleDeepPolish()} className="data-[state=checked]:bg-primary" />
                    <label htmlFor={`deep-polish-${msg.threadId}`} className="cursor-pointer text-xs text-muted-foreground flex items-center gap-1">
                      再润色时使用深度润色（质量更高，耗时更长）
                      <HelpIcon title="深度润色" content={helpTexts.interactive?.deepPolish ?? ""} size="sm" />
                    </label>
                  </div>
                  <div className="flex flex-wrap gap-2">
                    <Button variant="primary" size="sm" className="h-7 px-3 text-xs" onClick={() => onReviewDecision("approve")}>通过并提交</Button>
                    <Button variant="outline" size="sm" className="h-7 px-3 text-xs" onClick={() => onToggleRewriteInput()}>重写</Button>
                    <Button variant="ghost" size="sm" className="h-7 px-3 text-xs" onClick={() => onReviewDecision("polish")}>再润色</Button>
                    <Button variant="ghost" size="sm" className="h-7 px-3 text-xs text-warning hover:text-warning" onClick={() => onResetCommitting()}
                      title="如果按钮长时间卡住无法点击，点此重置状态">
                      重置状态
                    </Button>
                  </div>
                </div>
              )}
            </div>
          )}

          {/* 决策处理中 */}
          {msg.committing && !msg.reviewPending && (
            <div className="border-t border-border px-4 py-2">
              <div className="flex items-center gap-2 text-xs text-muted">
                <span className="inline-block h-3 w-3 animate-spin rounded-full border-2 border-primary border-t-transparent" />
                AI 工作室处理中...
              </div>
            </div>
          )}

          {/* 本章摘要 */}
          {msg.brief && (
            <div className="border-t border-border px-4 py-2">
              <div className="text-xs font-semibold text-muted">本章摘要</div>
              <p className="mt-0.5 text-xs text-foreground/70">{msg.brief}</p>
            </div>
          )}

          {/* 下一章建议 */}
          {msg.suggested_next && (
            <div className="border-t border-border bg-primary/5 px-4 py-2">
              <div className="flex items-center gap-1 text-xs font-semibold text-primary">
                💡 下一章建议
                <HelpIcon title="下一章建议" content={helpTexts.interactive?.suggestedNext ?? ""} size="sm" />
              </div>
              <p className="mt-0.5 text-xs text-foreground/80">{msg.suggested_next}</p>
            </div>
          )}

          {/* 圣经提交详情 */}
          {msg.committed && msg.commitDetail && (
            <div className="border-t border-border px-4 py-3">
              <div className="mb-3 rounded-lg bg-success/10 p-3">
                <div className="flex items-center gap-2 text-sm font-semibold text-success">
                  <CheckCircle2 className="h-4 w-4" /> 第 {msg.chapter} 章已完成并写入圣经
                  <HelpIcon title="写入圣经" content={helpTexts.interactive?.commitSuccess ?? ""} size="sm" />
                </div>
                <p className="mt-1 text-xs text-muted">你可以继续描述下一章剧情，或参考上方的「下一章建议」直接开始创作。</p>
              </div>
              {msg.commitDetail.chapter_summary && (
                <div className="space-y-2">
                  {msg.commitDetail.chapter_summary.core_events && (
                    <div className="rounded-md bg-surface p-2">
                      <span className="text-xs font-semibold text-foreground/70">核心事件</span>
                      <p className="mt-0.5 text-xs text-foreground/90">{msg.commitDetail.chapter_summary.core_events}</p>
                    </div>
                  )}
                  <div className="flex flex-wrap gap-2">
                    {msg.commitDetail.chapter_summary.characters_present && (
                      <div className="rounded-md bg-primary/10 px-2.5 py-1.5">
                        <span className="text-[10px] font-semibold uppercase text-primary/80">出场角色</span>
                        <p className="text-xs text-foreground/90">{msg.commitDetail.chapter_summary.characters_present}</p>
                      </div>
                    )}
                    {msg.commitDetail.chapter_summary.foreshadow_dynamics && (
                      <div className="rounded-md bg-warning/10 px-2.5 py-1.5">
                        <span className="text-[10px] font-semibold uppercase text-warning/80">伏笔动态</span>
                        <p className="text-xs text-foreground/90">{msg.commitDetail.chapter_summary.foreshadow_dynamics}</p>
                      </div>
                    )}
                    {msg.commitDetail.chapter_summary.chapter_hook && (
                      <div className="rounded-md bg-info/10 px-2.5 py-1.5">
                        <span className="text-[10px] font-semibold uppercase text-info/80">章末钩子</span>
                        <p className="text-xs text-foreground/90">{msg.commitDetail.chapter_summary.chapter_hook}</p>
                      </div>
                    )}
                  </div>
                </div>
              )}
            </div>
          )}

          {/* 兼容旧版手动提交 */}
          {!msg.threadId && !msg.committed && !msg.committing && !msg.reviewPending && (
            <div className="border-t border-border px-4 py-2">
              <div className="flex items-center gap-2">
                <Button variant="primary" size="sm" onClick={onCommit} className="h-7 px-3 text-xs">提交到圣经</Button>
                <HelpIcon title="提交到圣经" content={helpTexts.interactive?.commitButton ?? ""} size="sm" />
                <span className="text-xs text-muted/70">提取角色/伏笔/世界观变更，写入数据库</span>
              </div>
            </div>
          )}
          {!msg.threadId && !msg.committed && !msg.committing && msg.commitResult && (
            <p className="mt-1 px-4 pb-2 text-xs text-warning">{msg.commitResult}</p>
          )}
        </div>
      </div>
    );
  }

  // AI 纯文字回复
  return (
    <div className="flex items-start gap-3">
      <div className="flex h-8 w-8 shrink-0 items-center justify-center rounded-full bg-primary/10 text-sm">🤖</div>
      <div className="group relative max-w-[80%]">
        <div className="rounded-2xl rounded-tl-sm border border-border bg-surface overflow-hidden">
          <div className="px-4 py-2 text-sm text-foreground/90">
            <Markdown content={msg.content} />
          </div>
          {msg.options && msg.options.length > 0 && (
            <div className="border-t border-border px-3 py-2 space-y-1.5">
              {msg.options.map((opt, i) => {
                const selected = msg.selectedOption === opt.value;
                return (
                  <button key={i} type="button" title={opt.label} disabled={!!msg.selectedOption}
                    onClick={() => onOptionClick(opt)}
                    className={cn("flex items-center gap-2 w-full text-left px-3 py-2 rounded-lg border text-sm transition-colors",
                      selected ? "border-primary bg-primary/10 text-primary font-medium"
                      : msg.selectedOption ? "border-border opacity-40"
                      : "border-border hover:bg-accent hover:text-accent-foreground")}>
                    <span className="flex-shrink-0 w-5 h-5 rounded-full bg-primary/10 text-primary text-xs flex items-center justify-center font-medium">{i + 1}</span>
                    <span className="flex-1 line-clamp-2">{selected && "✓ "}{opt.label}</span>
                  </button>
                );
              })}
              {!msg.selectedOption && <div className="text-xs text-muted-foreground text-center pt-0.5">点击选项，或在下方输入框直接输入</div>}
            </div>
          )}
        </div>
        <button onClick={() => navigator.clipboard.writeText(msg.content)}
          className="absolute -bottom-2 right-2 opacity-0 group-hover:opacity-100 transition-opacity text-xs text-muted-foreground hover:text-foreground bg-surface border border-border rounded px-1.5 py-0.5">
          复制
        </button>
      </div>
    </div>
  );
}
