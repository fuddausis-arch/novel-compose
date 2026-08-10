import { api } from "../../api";
import type { SliceCreator } from "../types";

/** 项目域：项目列表 + 当前项目 + 项目加载。 */
export const projectSlice: SliceCreator = (set) => ({
  projects: [],
  currentProject: null,

  setProjects: (projects) => set({ projects }),
  setCurrentProject: (project) => set({ currentProject: project }),

  refreshProjects: async () => {
    set((state) => ({ loading: { ...state.loading, projects: true } }));
    try {
      const projects = await api.listProjects();
      set({ projects });
    } finally {
      set((state) => ({ loading: { ...state.loading, projects: false } }));
    }
  },

  loadProject: async (projectId: number) => {
    const project = await api.getProject(projectId);
    set({ currentProject: project });
    return project;
  },
});
