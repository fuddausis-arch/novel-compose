import { api } from "../../api";
import type { SliceCreator } from "../types";

/** 章节域：章节列表、摘要、题材上下文 + 各自加载器。 */
export const chapterSlice: SliceCreator = (set, get) => ({
  chapters: [],
  summaries: [],
  genreContext: null,

  setChapters: (chapters) => set({ chapters }),
  setSummaries: (summaries) => set({ summaries }),
  setGenreContext: (genreContext) => set({ genreContext }),

  refreshChapters: async () => {
    const project = get().currentProject;
    if (!project) return;
    set((state) => ({ loading: { ...state.loading, chapters: true } }));
    try {
      const chapters = await api.listChapters(project.id);
      set({ chapters });
    } finally {
      set((state) => ({ loading: { ...state.loading, chapters: false } }));
    }
  },

  refreshSummaries: async () => {
    const project = get().currentProject;
    if (!project) return;
    set((state) => ({ loading: { ...state.loading, summaries: true } }));
    try {
      const summaries = await api.listSummaries(project.id);
      set({ summaries });
    } finally {
      set((state) => ({ loading: { ...state.loading, summaries: false } }));
    }
  },

  refreshGenreContext: async () => {
    const project = get().currentProject;
    if (!project) return;
    set((state) => ({ loading: { ...state.loading, genreContext: true } }));
    try {
      const genreContext = await api.getGenreContext(project.id);
      set({ genreContext });
    } finally {
      set((state) => ({ loading: { ...state.loading, genreContext: false } }));
    }
  },
});
