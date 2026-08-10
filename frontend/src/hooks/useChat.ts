import { useCallback, useEffect, useState } from "react";
import { api } from "@/api";
import { useToast } from "@/hooks/useToast";
import type { ChatActionEvent, ChatMessageItem, ChatObjectType, ChatSessionType } from "@/types/chat";

interface UseChatOptions {
  projectId: number;
  objectType: ChatObjectType | "";
  objectId: string | number;
  title?: string;
  onRewriteChapter?: (chapter: number, title: string) => void;
}

export function useChat({ projectId, objectType, objectId, title, onRewriteChapter }: UseChatOptions) {
  const [mode, setMode] = useState<ChatSessionType>("object");
  const [messages, setMessages] = useState<ChatMessageItem[]>([]);
  const [input, setInput] = useState("");
  const [loading, setLoading] = useState(false);
  const [streamReasoning, setStreamReasoning] = useState("");
  const [sessions, setSessions] = useState<{ id: string; title: string; session_type: ChatSessionType }[]>([]);
  const { showError } = useToast();

  const effectiveObjectType = mode === "global" ? "" : objectType;
  const effectiveObjectId = mode === "global" ? "" : String(objectId);

  const loadSessions = useCallback(async () => {
    try {
      const list = await api.listChatSessions(projectId);
      setSessions(list.map((s) => ({ id: s.id, title: s.title, session_type: s.session_type })));
    } catch (e: any) {
      showError("加载会话失败：" + e.message);
    }
  }, [projectId, showError]);

  const loadHistory = useCallback(async () => {
    try {
      const list = await api.listChatSessions(projectId);
      const session = list.find(
        (s) =>
          s.session_type === mode &&
          s.object_type === effectiveObjectType &&
          s.object_id === effectiveObjectId
      );
      if (session) {
        const msgs = await api.getChatMessages(projectId, session.id);
        setMessages(msgs);
      } else {
        setMessages([]);
      }
    } catch (e: any) {
      showError("加载历史失败：" + e.message);
    }
  }, [projectId, mode, effectiveObjectType, effectiveObjectId, showError]);

  useEffect(() => {
    if (!projectId) return;
    loadHistory();
    loadSessions();
  }, [loadHistory, loadSessions, projectId]);

  const send = useCallback(async () => {
    if (!input.trim() || loading) return;
    const userMsg = input.trim();
    setInput("");
    setMessages((prev) => [
      ...prev,
      { id: "user-" + Date.now(), session_id: "", role: "user", content: userMsg, actions: [], created_at: new Date().toISOString() },
    ]);
    setLoading(true);
    setStreamReasoning("");
    let assistantText = "";
    const assistantId = "assistant-" + Date.now();
    try {
      await api.sendChatMessage(
        {
          project_id: projectId,
          message: userMsg,
          session_type: mode,
          object_type: effectiveObjectType,
          object_id: effectiveObjectId,
          title,
        },
        (chunk) => {
          assistantText += chunk.content;
          setMessages((prev) => {
            const withoutTemp = prev.filter((m) => m.id !== assistantId);
            return [
              ...withoutTemp,
              { id: assistantId, session_id: "", role: "assistant", content: assistantText, actions: [], created_at: new Date().toISOString() },
            ];
          });
        },
        (action: ChatActionEvent) => {
          setMessages((prev) =>
            prev.map((m) =>
              m.id === assistantId
                ? { ...m, actions: [...m.actions, action] }
                : m
            )
          );
          // rewrite_chapter 返回 redirect 时，触发 generate/stream 走节点进度
          const result = action.result as { status?: string; chapter?: number; title?: string } | undefined;
          if (result?.status === "redirect" && result.chapter && onRewriteChapter) {
            onRewriteChapter(result.chapter, result.title || `第${result.chapter}章`);
          }
        },
        (reasoning) => {
          setStreamReasoning((prev) => prev + (reasoning.content || ""));
        }
      );
      await loadHistory();
      setLoading(false);
      setStreamReasoning("");
    } catch (e: any) {
      showError("发送失败：" + e.message);
      // 断线重连：3秒后重新加载消息，检查后端是否已完成
      setTimeout(async () => {
        await loadHistory();
        setLoading(false);
        setStreamReasoning("");
      }, 3000);
    }
  }, [input, loading, projectId, mode, effectiveObjectType, effectiveObjectId, title, loadHistory, showError]);

  const clearSession = useCallback(async () => {
    try {
      const list = await api.listChatSessions(projectId);
      const session = list.find(
        (s) =>
          s.session_type === mode &&
          s.object_type === effectiveObjectType &&
          s.object_id === effectiveObjectId
      );
      if (session) {
        await api.deleteChatSession(projectId, session.id);
        setMessages([]);
        loadSessions();
      }
    } catch (e: any) {
      showError("清空会话失败：" + e.message);
    }
  }, [projectId, mode, effectiveObjectType, effectiveObjectId, loadSessions, showError]);

  return {
    mode,
    setMode,
    messages,
    input,
    setInput,
    loading,
    send,
    sessions,
    clearSession,
    streamReasoning,
  };
}
