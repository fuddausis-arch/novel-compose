import { api } from "../../api";
import type { GenerationEvent, SliceCreator } from "../types";
import { bumpDataVersion } from "./dataVersion";

/** 管线/生成域：流水线状态、风格分析、章节生成 SSE 流（旧章节生成路径）。 */
export const pipelineSlice: SliceCreator = (set, get) => ({
  pipelineEvents: [],
  pipelineStatus: "idle",
  pipelineProgress: 0,
  pipelineSource: null,
  styleAnalysis: "",
  styleBenchmark: "",
  activeGeneration: null,
  __generationSubscribers: new Set<(event: GenerationEvent) => void>(),
  __currentEventSource: null as EventSource | null,

  startPipeline: (label) => set({ pipelineStatus: "running", pipelineProgress: 0, pipelineEvents: label ? [label] : [], styleAnalysis: "", styleBenchmark: "" }),
  addPipelineEvent: (msg, progress) => set((state) => ({
    pipelineEvents: [...state.pipelineEvents, msg],
    ...(progress !== undefined ? { pipelineProgress: progress } : {}),
  })),
  setPipelineStatus: (status) => set({ pipelineStatus: status }),
  clearPipeline: () => set({ pipelineEvents: [], pipelineStatus: "idle", pipelineProgress: 0, pipelineSource: null, styleAnalysis: "", styleBenchmark: "" }),
  setStyleAnalysis: (analysis, benchmark) => set({ styleAnalysis: analysis, styleBenchmark: benchmark }),

  subscribeGeneration: (cb) => {
    const subs = (get() as any).__generationSubscribers as Set<(event: GenerationEvent) => void>;
    subs.add(cb);
    return () => subs.delete(cb);
  },

  startGenerationStream: (projectId, chapter, title) => {
    get().stopGenerationStream();
    const es = api.generateStream(projectId, chapter, title);
    const subs = (get() as any).__generationSubscribers as Set<(event: GenerationEvent) => void>;
    set({ activeGeneration: { projectId, chapter, title, threadId: "", mode: "generate" } });

    const notify = (event: GenerationEvent) => subs.forEach((cb) => cb(event));
    // 流结束（done/error/review_pending 后端已关闭流）时显式 close，
    // 否则浏览器 EventSource 自动重连同一 URL，会误报"连接中断"并可能重复触发生成
    const finish = (event: GenerationEvent) => {
      notify(event);
      es.close();
    };

    es.addEventListener("node", (e) => {
      let data: any;
      try { data = JSON.parse((e as MessageEvent).data); } catch { data = { raw: (e as MessageEvent).data }; }
      if (data.thread_id) {
        set((state) => ({ activeGeneration: state.activeGeneration ? { ...state.activeGeneration, threadId: data.thread_id } : null }));
      }
      notify({ type: "node", data });
    });
    es.addEventListener("review_pending", (e) => {
      let data: any;
      try { data = JSON.parse((e as MessageEvent).data); } catch { data = { raw: (e as MessageEvent).data }; }
      set((state) => ({ activeGeneration: state.activeGeneration ? { ...state.activeGeneration, reviewPendingData: data } : null }));
      finish({ type: "review_pending", data });
    });
    es.addEventListener("error", (e) => {
      let data: any;
      try { data = JSON.parse((e as MessageEvent).data || "{}"); } catch { data = { error: String((e as MessageEvent).data || "未知错误") }; }
      finish({ type: "error", data });
      set({ activeGeneration: null });
    });
    es.addEventListener("done", (e) => {
      let data: any;
      try { data = JSON.parse((e as MessageEvent).data || "{}"); } catch { data = { status: "failed", error: String((e as MessageEvent).data || "完成事件解析失败") }; }
      if (data.status !== "failed") {
        bumpDataVersion("chapters");
        bumpDataVersion("bible");
      }
      finish({ type: "done", data });
      set({ activeGeneration: null });
    });
    es.onerror = () => {
      // 主动 close() 后浏览器也会触发 onerror，此时不应误报连接中断
      if (es.readyState === EventSource.CLOSED) return;
      notify({ type: "connection_error" });
      set({ activeGeneration: null });
    };
    (get() as any).__currentEventSource = es;
  },

  resumeGenerationStream: (projectId, threadId, decision, feedback?: string, chapter?: number) => {
    get().stopGenerationStream();
    const es = api.resumeStream(projectId, threadId, decision, feedback);
    const subs = (get() as any).__generationSubscribers as Set<(event: GenerationEvent) => void>;
    set({ activeGeneration: { projectId, chapter: chapter ?? 0, title: "", threadId, mode: "resume", reviewDecision: decision } });

    const notify = (event: GenerationEvent) => subs.forEach((cb) => cb(event));
    const finish = (event: GenerationEvent) => {
      notify(event);
      es.close();
    };

    es.addEventListener("node", (e) => {
      let data: any;
      try { data = JSON.parse((e as MessageEvent).data); } catch { data = { raw: (e as MessageEvent).data }; }
      notify({ type: "node", data });
    });
    es.addEventListener("review_pending", (e) => {
      let data: any;
      try { data = JSON.parse((e as MessageEvent).data); } catch { data = { raw: (e as MessageEvent).data }; }
      set((state) => ({ activeGeneration: state.activeGeneration ? { ...state.activeGeneration, reviewPendingData: data } : null }));
      finish({ type: "review_pending", data });
    });
    es.addEventListener("error", (e) => {
      let data: any;
      try { data = JSON.parse((e as MessageEvent).data || "{}"); } catch { data = { error: String((e as MessageEvent).data || "未知错误") }; }
      finish({ type: "error", data });
      set({ activeGeneration: null });
    });
    es.addEventListener("done", (e) => {
      let data: any;
      try { data = JSON.parse((e as MessageEvent).data || "{}"); } catch { data = { status: "failed", error: String((e as MessageEvent).data || "完成事件解析失败") }; }
      if (data.status !== "failed") {
        bumpDataVersion("chapters");
        bumpDataVersion("bible");
      }
      finish({ type: "done", data });
      set({ activeGeneration: null });
    });
    es.onerror = () => {
      if (es.readyState === EventSource.CLOSED) return;
      notify({ type: "connection_error" });
      set({ activeGeneration: null });
    };
    (get() as any).__currentEventSource = es;
  },

  stopGenerationStream: () => {
    const es = (get() as any).__currentEventSource as EventSource | undefined;
    if (es) {
      es.close();
      (get() as any).__currentEventSource = null;
    }
    set({ activeGeneration: null });
  },
});
