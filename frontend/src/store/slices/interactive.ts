import { api } from "../../api";
import type { ChatMessage, MessagePhase } from "../../types";
import type { SliceCreator } from "../types";
import { bumpDataVersion } from "./dataVersion";

// ---- 状态机辅助 ----

/** 检查消息是否处于给定阶段（phase 为真相源，布尔标志做兼容兜底）。 */
function isPhase(msg: ChatMessage | undefined, phase: MessagePhase): boolean {
  if (!msg) return false;
  if (msg.phase) return msg.phase === phase;
  // 兼容旧消息（无 phase 字段）：从布尔标志推断
  switch (phase) {
    case "under_review": return !!msg.reviewPending && !msg.committing;
    case "awaiting_variant": return !!msg.awaitingVariant && !msg.committing;
    case "committing": return !!msg.committing;
    case "committed": return !!msg.committed;
    case "drafting": return !!msg.isDraft && !msg.reviewPending && !msg.committing;
    default: return false;
  }
}

/** 共享 SSE 事件处理器：处理 review_pending / audit / refined / commit / done 等公共事件。
 *  消除 interactiveSend / interactiveResume / interactiveVariantResume 三处的重复逻辑。
 *  返回 true 表示事件已处理，false 表示未处理（调用方自行处理）。
 */
function _processChapterSSEEvent(
  currentEvent: string,
  data: any,
  _state: { interactiveStreamOptions: any[] },
  set: (fn: (s: any) => any) => void,
  _get: () => any,
): boolean {
  if (currentEvent === "audit") {
    set((s: any) => {
      const next = [...s.interactiveMessages];
      for (let i = next.length - 1; i >= 0; i--) {
        if (next[i].msg_type === "chapter" && next[i].threadId === data.thread_id) {
          next[i] = { ...next[i], auditReport: data.report };
          break;
        }
      }
      return { interactiveMessages: next };
    });
    return true;
  }
  if (currentEvent === "review_pending") {
    set((s: any) => {
      const next = [...s.interactiveMessages];
      for (let i = next.length - 1; i >= 0; i--) {
        if (next[i].msg_type === "chapter" && next[i].threadId === data.thread_id) {
          next[i] = { ...next[i], reviewPending: true, committing: false, phase: "under_review" as MessagePhase };
          break;
        }
      }
      return { interactiveMessages: next };
    });
    return true;
  }
  if (currentEvent === "refined") {
    set((s: any) => {
      const next = [...s.interactiveMessages];
      for (let i = next.length - 1; i >= 0; i--) {
        if (next[i].msg_type === "chapter" && next[i].threadId === data.thread_id) {
          next[i] = {
            ...next[i],
            content: data.content,
            word_count: data.word_count,
            polished: true,
            polishIssues: data.polish_issues,
            isDraft: false,
            reviewPending: true,
            committing: false,
            phase: "under_review" as MessagePhase,
          };
          break;
        }
      }
      return { interactiveMessages: next };
    });
    return true;
  }
  if (currentEvent === "commit") {
    set((s: any) => {
      const next = [...s.interactiveMessages];
      for (let i = next.length - 1; i >= 0; i--) {
        if (next[i].msg_type === "chapter" && next[i].threadId === data.thread_id) {
          next[i] = {
            ...next[i],
            committed: true,
            commitDetail: data.result,
            reviewPending: false,
            committing: false,
            phase: "committed" as MessagePhase,
          };
          break;
        }
      }
      return { interactiveMessages: next };
    });
    return true;
  }
  return false;
}

/** 交互式创作域：消息、模式、流式状态、生成/润色/重写/抽卡动作。 */
export const interactiveSlice: SliceCreator = (set, get) => ({
  interactiveMessages: [],
  interactiveMode: "qa",
  interactiveInput: "",
  interactiveGenerating: false,
  interactiveUseWorkflow: true,  // 默认开启 26-Agent MVP 工作流模式（质量优先），用户可手动切回单 Agent
  interactiveNumVariants: 1,      // 默认不抽卡（生成 1 版）
  interactiveElapsed: 0,
  interactiveStreamThinking: [],
  interactiveStreamContent: "",
  interactiveStreamReasoning: "",
  interactiveStreamType: null,
  interactiveStreamActions: [],
  interactiveStreamOptions: [],
  interactiveLoadedProjectId: null,
  interactiveReconnecting: false,
  __interactiveAbortController: null as AbortController | null,
  __interactiveElapsedTimer: null as ReturnType<typeof setInterval> | null,
  __interactiveSaveTimeout: null as ReturnType<typeof setTimeout> | null,

  setInteractiveMessages: (messages) => set({ interactiveMessages: messages }),
  setInteractiveMode: (mode) => set({ interactiveMode: mode }),
  setInteractiveInput: (input) => set({ interactiveInput: input }),
  toggleInteractiveUseWorkflow: (on: boolean) => set({ interactiveUseWorkflow: on }),
  setInteractiveNumVariants: (n: number) => set({ interactiveNumVariants: Math.max(1, Math.floor(n)) }),
  appendInteractiveMessage: (msg) => set((state) => ({ interactiveMessages: [...state.interactiveMessages, msg] })),
  updateInteractiveMessage: (index, updater) => set((state) => {
    const next = [...state.interactiveMessages];
    if (index >= 0 && index < next.length) {
      next[index] = updater(next[index]);
    }
    return { interactiveMessages: next };
  }),
  setInteractiveGenerating: (generating) => set({ interactiveGenerating: generating }),

  interactiveLoadMessages: async (projectId) => {
    const state = get();
    if (state.interactiveLoadedProjectId === projectId) return;
    set({ interactiveLoadedProjectId: projectId, interactiveMessages: [], interactiveStreamOptions: [] });
    try {
      const list = await api.getInteractiveMessages(projectId);
      const parsed: ChatMessage[] = [];
      for (const item of list) {
        try {
          const m = JSON.parse(item.content);
          parsed.push(m);
        } catch {
          parsed.push({
            role: item.role as "user" | "assistant",
            content: item.content,
            msg_type: "chat" as const,
          });
        }
      }
      set({ interactiveMessages: parsed });
    } catch {
      // ignore
    }
  },

  interactiveSaveMessages: async (projectId, messages) => {
    // 完整保存消息对象（包括 reviewPending / threadId / auditReport / commitDetail 等前端状态），
    // 切页或刷新后重新加载才能恢复完全一致的状态。
    try {
      await api.saveInteractiveMessages(projectId, messages);
    } catch {
      // ignore
    }
  },

  interactiveSend: async (projectId, text, history, mode) => {
    const state = get();
    if (state.interactiveGenerating) return;

    const userMsg: ChatMessage = {
      role: "user",
      content: text || (mode === "free" ? "（继续生成下一章）" : ""),
      msg_type: "chat",
    };
    const messages = [...state.interactiveMessages, userMsg];
    set({
      interactiveMessages: messages,
      interactiveInput: "",
      interactiveGenerating: true,
      interactiveElapsed: 0,
      interactiveStreamThinking: [],
      interactiveStreamContent: "",
      interactiveStreamReasoning: "",
      interactiveStreamType: null,
      interactiveStreamActions: [],
      interactiveStreamOptions: [],
    });

    // 启动计时器
    const start = Date.now();
    const timer = setInterval(() => {
      set({ interactiveElapsed: Math.floor((Date.now() - start) / 1000) });
    }, 1000);
    (get() as any).__interactiveElapsedTimer = timer;

    const controller = new AbortController();
    (get() as any).__interactiveAbortController = controller;

    const clearTimer = () => {
      const t = (get() as any).__interactiveElapsedTimer as ReturnType<typeof setInterval> | null;
      if (t) {
        clearInterval(t);
        (get() as any).__interactiveElapsedTimer = null;
      }
    };

    try {
      const res = await api.interactiveChatStream(projectId, text || "", history, mode, controller.signal, (get() as any).interactiveUseWorkflow ?? false, (get() as any).interactiveNumVariants ?? 1);
      if (!res.body) throw new Error("无法建立流式连接");

      const reader = res.body.getReader();
      const decoder = new TextDecoder();
      let buffer = "";
      let currentEvent = "";
      let accumulatedContent = "";

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
            const dataStr = line.slice(6);
            let data: any;
            try { data = JSON.parse(dataStr); } catch { continue; }

            if (currentEvent === "thinking") {
              set((s) => ({ interactiveStreamThinking: [...s.interactiveStreamThinking, { stage: data.stage, detail: data.detail }] }));
            } else if (currentEvent === "reasoning") {
              set((s) => ({ interactiveStreamReasoning: s.interactiveStreamReasoning + (data.content || "") }));
            } else if (currentEvent === "type") {
              set({ interactiveStreamType: data.type });
            } else if (currentEvent === "chunk") {
              accumulatedContent += data.content || "";
              set({ interactiveStreamContent: accumulatedContent });
            } else if (currentEvent === "action") {
              if (data.type === "present_options" && data.options) {
                set({ interactiveStreamOptions: data.options });
              }
              set((s) => ({ interactiveStreamActions: [...s.interactiveStreamActions, data] }));
            } else if (currentEvent === "draft") {
              const aiMsg: ChatMessage = {
                role: "assistant",
                content: data.content,
                msg_type: "chapter",
                chapter: data.chapter ?? null,
                title: data.title ?? null,
                word_count: data.word_count ?? null,
                expanded: false,
                isDraft: true,
                threadId: data.thread_id ?? null,
                phase: "drafting",
              };
              set((s) => ({
                interactiveMessages: [...s.interactiveMessages, aiMsg],
                interactiveStreamContent: "",
                interactiveStreamType: null,
              }));
              accumulatedContent = "";
            } else if (currentEvent === "variants") {
              // 抽卡模式：收到 N 个候选版本，渲染候选卡片等待用户选择
              const aiMsg: ChatMessage = {
                role: "assistant",
                content: "",
                msg_type: "chapter",
                chapter: null,
                title: data.variants?.[0]?.title ?? null,
                word_count: data.variants?.[0]?.word_count ?? null,
                variants: data.variants ?? [],
                threadId: data.thread_id ?? null,
                awaitingVariant: true,
                expanded: false,
                phase: "awaiting_variant",
              };
              set((s) => ({
                interactiveMessages: [...s.interactiveMessages, aiMsg],
                interactiveStreamContent: "",
                interactiveStreamType: null,
              }));
              accumulatedContent = "";
            } else if (currentEvent === "await_variant_choice") {
              // 抽卡模式：等待用户在 N 个候选版本中选择，无需额外处理
            } else if (currentEvent === "audit") {
              _processChapterSSEEvent(currentEvent, data, { interactiveStreamOptions: get().interactiveStreamOptions }, set, get);
            } else if (currentEvent === "review_pending") {
              _processChapterSSEEvent(currentEvent, data, { interactiveStreamOptions: get().interactiveStreamOptions }, set, get);
            } else if (currentEvent === "refined") {
              _processChapterSSEEvent(currentEvent, data, { interactiveStreamOptions: get().interactiveStreamOptions }, set, get);
            } else if (currentEvent === "commit") {
              _processChapterSSEEvent(currentEvent, data, { interactiveStreamOptions: get().interactiveStreamOptions }, set, get);
            } else if (currentEvent === "done") {
              if (data.type === "chapter_committed") {
                // 章节已提交写入圣经：刷新章节列表 + 全部 bible 实体，并通知各页面
                get().refreshAssets().catch(() => {});
                bumpDataVersion("bible");
                bumpDataVersion("chapters");
              } else if (data.type === "chapter") {
                const aiMsg: ChatMessage = {
                  role: "assistant",
                  content: data.content ?? data.message,
                  msg_type: data.type,
                  chapter: data.chapter ?? null,
                  title: data.title ?? null,
                  word_count: data.word_count ?? null,
                  brief: data.brief ?? null,
                  suggested_next: data.suggested_next ?? null,
                  expanded: false,
                };
                set((s) => ({ interactiveMessages: [...s.interactiveMessages, aiMsg] }));
                get().refreshChapters().catch(() => {});
              } else {
                const aiMsg: ChatMessage = {
                  role: "assistant",
                  content: data.message,
                  msg_type: "chat",
                  options: get().interactiveStreamOptions.length > 0 ? get().interactiveStreamOptions : undefined,
                };
                set((s) => ({ interactiveMessages: [...s.interactiveMessages, aiMsg] }));
              }
            } else if (currentEvent === "error") {
              // 错误由页面 toast 处理
            }
          }
        }
      }
    } catch (e: any) {
      if (e.name !== "AbortError") {
        console.error("interactiveSend error", e);
        // 断线重连：3秒后查后端状态
        set({ interactiveReconnecting: true });
        setTimeout(async () => {
          try {
            // 重新加载消息，看后端是否已完成
            set({ interactiveLoadedProjectId: null });
            await get().interactiveLoadMessages(projectId);
            set({ interactiveReconnecting: false, interactiveGenerating: false });
          } catch {
            set({ interactiveReconnecting: false, interactiveGenerating: false });
          }
        }, 3000);
      }
    } finally {
      clearTimer();
      set({
        interactiveStreamThinking: [],
        interactiveStreamContent: "",
        interactiveStreamReasoning: "",
        interactiveStreamType: null,
        interactiveStreamActions: [],
        // 不重置 interactiveStreamOptions：选项持续显示直到用户点击或发新消息
      });
      (get() as any).__interactiveAbortController = null;
      // 如果正在重连，不重置 generating 状态（等重连逻辑处理）
      if (!get().interactiveReconnecting) {
        set({ interactiveGenerating: false });
      }
    }
  },

  interactiveResume: async (projectId, threadId, decision, feedback, deepPolish, msgIndex) => {
    const state = get();
    const msg = state.interactiveMessages[msgIndex];
    // 状态机 guard：只允许 under_review 阶段的消息触发人审决策
    if (!msg || !msg.threadId || !isPhase(msg, "under_review")) {
      console.warn("[interactiveResume] guard blocked (phase != under_review)", { phase: msg?.phase, reviewPending: msg?.reviewPending, committing: msg?.committing });
      return;
    }

    set((s) => {
      const next = [...s.interactiveMessages];
      next[msgIndex] = { ...next[msgIndex], reviewPending: false, committing: true, showRewriteInput: false, phase: "committing" as MessagePhase };
      return { interactiveMessages: next, interactiveGenerating: true, interactiveStreamReasoning: "" };
    });

    const start = Date.now();
    const timer = setInterval(() => {
      set({ interactiveElapsed: Math.floor((Date.now() - start) / 1000) });
    }, 1000);
    (get() as any).__interactiveElapsedTimer = timer;

    const clearTimer = () => {
      const t = (get() as any).__interactiveElapsedTimer as ReturnType<typeof setInterval> | null;
      if (t) {
        clearInterval(t);
        (get() as any).__interactiveElapsedTimer = null;
      }
    };

    const controller = new AbortController();
    (get() as any).__interactiveAbortController = controller;

    try {
      const res = await api.interactiveResume(projectId, threadId, decision, feedback, deepPolish, controller.signal);
      if (!res.body) throw new Error("无法建立流式连接");

      const reader = res.body.getReader();
      const decoder = new TextDecoder();
      let buffer = "";
      let currentEvent = "";
      let rewriteContent = "";

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
            const dataStr = line.slice(6);
            let data: any;
            try { data = JSON.parse(dataStr); } catch { continue; }

            if (currentEvent === "thinking") {
              set((s) => ({ interactiveStreamThinking: [...s.interactiveStreamThinking, { stage: data.stage, detail: data.detail }] }));
            } else if (currentEvent === "reasoning") {
              set((s) => ({ interactiveStreamReasoning: s.interactiveStreamReasoning + (data.content || "") }));
            } else if (currentEvent === "chunk") {
              rewriteContent += data.content || "";
              set({ interactiveStreamContent: rewriteContent, interactiveStreamType: "chapter" });
            } else if (currentEvent === "action") {
              if (data.type === "present_options" && data.options) {
                set({ interactiveStreamOptions: data.options });
              }
              set((s) => ({ interactiveStreamActions: [...s.interactiveStreamActions, data] }));
            } else if (currentEvent === "draft") {
              set((s) => {
                const next = [...s.interactiveMessages];
                next[msgIndex] = {
                  ...next[msgIndex],
                  content: data.content,
                  word_count: data.word_count,
                  isDraft: true,
                  polished: false,
                  committed: false,
                  committing: false,
                  auditReport: null,
                  commitDetail: null,
                  phase: "drafting" as MessagePhase,
                };
                return { interactiveMessages: next, interactiveStreamContent: "", interactiveStreamType: null };
              });
              rewriteContent = "";
            } else if (currentEvent === "audit") {
              _processChapterSSEEvent(currentEvent, data, { interactiveStreamOptions: get().interactiveStreamOptions }, set, get);
            } else if (currentEvent === "review_pending") {
              set((s) => {
                const next = [...s.interactiveMessages];
                next[msgIndex] = { ...next[msgIndex], reviewPending: true, committing: false, phase: "under_review" as MessagePhase };
                return { interactiveMessages: next };
              });
            } else if (currentEvent === "refined") {
              _processChapterSSEEvent(currentEvent, data, { interactiveStreamOptions: get().interactiveStreamOptions }, set, get);
            } else if (currentEvent === "commit") {
              _processChapterSSEEvent(currentEvent, data, { interactiveStreamOptions: get().interactiveStreamOptions }, set, get);
            } else if (currentEvent === "done") {
              if (data.type === "chapter_committed") {
                // 章节已提交写入圣经：刷新章节列表 + 全部 bible 实体，并通知各页面
                get().refreshAssets().catch(() => {});
                bumpDataVersion("bible");
                bumpDataVersion("chapters");
              }
            } else if (currentEvent === "error") {
              set((s) => {
                const next = [...s.interactiveMessages];
                next[msgIndex] = { ...next[msgIndex], reviewPending: true, committing: false, phase: "under_review" as MessagePhase };
                return { interactiveMessages: next };
              });
            }
          }
        }
      }
    } catch (e: any) {
      if (e.name !== "AbortError") {
        console.error("[interactiveResume] error", e);
      }
      set((s) => {
        const next = [...s.interactiveMessages];
        next[msgIndex] = { ...next[msgIndex], reviewPending: true, committing: false, phase: "under_review" as MessagePhase };
        return { interactiveMessages: next };
      });
    } finally {
      clearTimer();
      set({
        interactiveStreamThinking: [],
        interactiveStreamContent: "",
        interactiveStreamReasoning: "",
        interactiveStreamType: null,
        interactiveStreamActions: [],
        // 不重置 interactiveStreamOptions：选项持续显示直到用户点击或发新消息
      });
      (get() as any).__interactiveAbortController = null;
      // 人审 pending 状态不是「生成中」，不应显示底部流式占位符
      set({ interactiveGenerating: false });
    }
  },

  interactiveVariantResume: async (projectId, threadId, selectedIndex, msgIndex) => {
    const state = get();
    const msg = state.interactiveMessages[msgIndex];
    // 状态机 guard：只允许 awaiting_variant 阶段的消息触发选版
    if (!msg || !msg.threadId || !isPhase(msg, "awaiting_variant")) {
      console.warn("[interactiveVariantResume] guard blocked (phase != awaiting_variant)", { phase: msg?.phase, awaitingVariant: msg?.awaitingVariant, committing: msg?.committing });
      return;
    }

    set((s) => {
      const next = [...s.interactiveMessages];
      next[msgIndex] = { ...next[msgIndex], awaitingVariant: false, committing: true, showRewriteInput: false, phase: "committing" as MessagePhase };
      return { interactiveMessages: next, interactiveGenerating: true, interactiveStreamReasoning: "" };
    });

    const start = Date.now();
    const timer = setInterval(() => {
      set({ interactiveElapsed: Math.floor((Date.now() - start) / 1000) });
    }, 1000);
    (get() as any).__interactiveElapsedTimer = timer;

    const clearTimer = () => {
      const t = (get() as any).__interactiveElapsedTimer as ReturnType<typeof setInterval> | null;
      if (t) {
        clearInterval(t);
        (get() as any).__interactiveElapsedTimer = null;
      }
    };

    const controller = new AbortController();
    (get() as any).__interactiveAbortController = controller;

    try {
      const res = await api.interactiveVariantResume(projectId, threadId, selectedIndex, controller.signal);
      if (!res.body) throw new Error("无法建立流式连接");

      const reader = res.body.getReader();
      const decoder = new TextDecoder();
      let buffer = "";
      let currentEvent = "";
      let chunkContent = "";

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
            const dataStr = line.slice(6);
            let data: any;
            try { data = JSON.parse(dataStr); } catch { continue; }

            if (currentEvent === "thinking") {
              set((s) => ({ interactiveStreamThinking: [...s.interactiveStreamThinking, { stage: data.stage, detail: data.detail }] }));
            } else if (currentEvent === "reasoning") {
              set((s) => ({ interactiveStreamReasoning: s.interactiveStreamReasoning + (data.content || "") }));
            } else if (currentEvent === "chunk") {
              chunkContent += data.content || "";
              set({ interactiveStreamContent: chunkContent, interactiveStreamType: "chapter" });
            } else if (currentEvent === "draft") {
              set((s) => {
                const next = [...s.interactiveMessages];
                next[msgIndex] = {
                  ...next[msgIndex],
                  content: data.content,
                  chapter: data.chapter ?? next[msgIndex].chapter,
                  title: data.title ?? next[msgIndex].title,
                  word_count: data.word_count,
                  isDraft: true,
                  polished: false,
                  committed: false,
                  committing: false,
                  auditReport: null,
                  commitDetail: null,
                  awaitingVariant: false,
                  phase: "drafting" as MessagePhase,
                };
                return { interactiveMessages: next, interactiveStreamContent: "", interactiveStreamType: null };
              });
              chunkContent = "";
            } else if (currentEvent === "audit") {
              _processChapterSSEEvent(currentEvent, data, { interactiveStreamOptions: get().interactiveStreamOptions }, set, get);
            } else if (currentEvent === "review_pending") {
              set((s) => {
                const next = [...s.interactiveMessages];
                next[msgIndex] = { ...next[msgIndex], reviewPending: true, committing: false, awaitingVariant: false, phase: "under_review" as MessagePhase };
                return { interactiveMessages: next };
              });
            } else if (currentEvent === "error") {
              set((s) => {
                const next = [...s.interactiveMessages];
                next[msgIndex] = { ...next[msgIndex], committing: false, awaitingVariant: true, phase: "awaiting_variant" as MessagePhase };
                return { interactiveMessages: next };
              });
            }
          }
        }
      }
    } catch (e: any) {
      if (e.name !== "AbortError") {
        console.error("[interactiveVariantResume] error", e);
      }
      set((s) => {
        const next = [...s.interactiveMessages];
        next[msgIndex] = { ...next[msgIndex], committing: false, awaitingVariant: true, phase: "awaiting_variant" as MessagePhase };
        return { interactiveMessages: next };
      });
    } finally {
      clearTimer();
      set({
        interactiveStreamThinking: [],
        interactiveStreamContent: "",
        interactiveStreamReasoning: "",
        interactiveStreamType: null,
        interactiveStreamActions: [],
      });
      (get() as any).__interactiveAbortController = null;
      set({ interactiveGenerating: false });
    }
  },

  interactiveStop: () => {
    const controller = (get() as any).__interactiveAbortController as AbortController | null;
    if (controller) {
      controller.abort();
      (get() as any).__interactiveAbortController = null;
    }
    const timer = (get() as any).__interactiveElapsedTimer as ReturnType<typeof setInterval> | null;
    if (timer) {
      clearInterval(timer);
      (get() as any).__interactiveElapsedTimer = null;
    }
    set({ interactiveGenerating: false, interactiveStreamReasoning: "" });
  },
});
