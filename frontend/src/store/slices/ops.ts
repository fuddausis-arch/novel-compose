import { api } from "../../api";
import type { SliceCreator } from "../types";

/** 操作/批量域：批量生成状态 + 全局 loading 标记。 */
export const opsSlice: SliceCreator = (set, get) => ({
  loading: {
    projects: false,
    characters: false,
    foreshadows: false,
    outlines: false,
    worldSettings: false,
    chapters: false,
    summaries: false,
    genreContext: false,
    assets: false,
    states: false,
    events: false,
    factions: false,
    factionRelationships: false,
    characterRelationships: false,
    monsters: false,
    instances: false,
    entityAppearances: false,
    redLines: false,
    gags: false,
    importedChapters: false,
  },
  batchGenerating: false,
  batchProgress: { current: 0, total: 0, completed: 0, failed: 0 },
  batchErrors: [],
  __batchAbortController: null as AbortController | null,

  setLoading: (key, value) => set((state) => ({ loading: { ...state.loading, [key]: value } })),

  // ── 批量生成：逐章 SSE 流式 ──
  batchGenerate: async (projectId, startChapter, endChapter) => {
    const state = get();
    if (state.batchGenerating) return;
    const total = endChapter - startChapter + 1;
    set({
      batchGenerating: true,
      batchProgress: { current: 0, total, completed: 0, failed: 0 },
      batchErrors: [],
    });
    const controller = new AbortController();
    (get() as any).__batchAbortController = controller;
    try {
      await api.bookRunStream(
        projectId,
        startChapter,
        endChapter,
        (ch) => {
          set((s) => ({
            batchProgress: { ...s.batchProgress, current: ch - startChapter + 1 },
          }));
        },
        (ch, status, error) => {
          if (status === "failed") {
            if (error) {
              set((s) => ({
                batchErrors: [...s.batchErrors, { chapter: ch, error }],
              }));
            }
            set((s) => ({
              batchProgress: { ...s.batchProgress, failed: s.batchProgress.failed + 1 },
            }));
          } else {
            set((s) => ({
              batchProgress: { ...s.batchProgress, completed: s.batchProgress.completed + 1 },
            }));
          }
        },
        (doneTotal, doneCompleted, doneFailed) => {
          set((s) => ({
            batchProgress: {
              ...s.batchProgress,
              total: doneTotal,
              completed: doneCompleted,
              failed: doneFailed,
            },
          }));
        },
        (error) => {
          set((s) => ({
            batchErrors: [...s.batchErrors, { chapter: 0, error }],
          }));
        },
        controller.signal,
      );
    } catch (e: any) {
      if (e.name !== "AbortError") {
        set((s) => ({
          batchErrors: [...s.batchErrors, { chapter: 0, error: e.message }],
        }));
      }
    } finally {
      set({ batchGenerating: false });
      (get() as any).__batchAbortController = null;
      get().refreshChapters().catch(() => {});
    }
  },

  batchStop: () => {
    const controller = (get() as any).__batchAbortController as AbortController | null;
    if (controller) {
      controller.abort();
      (get() as any).__batchAbortController = null;
    }
    set({ batchGenerating: false });
  },
});
