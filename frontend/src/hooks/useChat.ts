import { useCallback, useEffect, useState } from "react";
import { api } from "@/api";
import { useToast } from "@/hooks/useToast";
import type { ChatActionEvent, ChatMessageItem, ChatObjectType, ChatSessionType } from "@/types/chat";

interface UseChatOptions {
  projectId: number;
  objectType: ChatObjectType | "";
  objectId: string | number;
  title?: string;
}

export function useChat({ projectId, objectType, objectId, title }: UseChatOptions) {
  const [mode, setMode] = useState<ChatSessionType>("object");
  const [messages, setMessages] = useState<ChatMessageItem[]>([]);
  const [input, setInput] = useState("");
  const [loading, setLoading] = useState(false);
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
        }
      );
      await loadHistory();
    } catch (e: any) {
      showError("发送失败：" + e.message);
    } finally {
      setLoading(false);
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
  };
}
