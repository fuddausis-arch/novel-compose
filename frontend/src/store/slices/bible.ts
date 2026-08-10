import { api } from "../../api";
import type { AppState, SliceCreator } from "../types";

/** 圣经/资产域：角色、伏笔、大纲、世界观、势力、关系、怪物、副本、实体出现、
 * 状态、事件、红线、梗、导入章纲等全部资产实体 + 各自加载器。 */
export const bibleSlice: SliceCreator = (set, get) => ({
  characters: [],
  foreshadows: [],
  outlines: [],
  worldSettings: [],
  factions: [],
  factionRelationships: [],
  characterRelationships: [],
  monsters: [],
  instances: [],
  entityAppearances: [],
  states: [],
  events: [],
  redLines: [],
  gags: [],
  importedChapters: [],

  setCharacters: (characters) => set({ characters }),
  setForeshadows: (foreshadows) => set({ foreshadows }),
  setOutlines: (outlines) => set({ outlines }),
  setWorldSettings: (worldSettings) => set({ worldSettings }),
  setFactions: (factions) => set({ factions }),
  setFactionRelationships: (factionRelationships) => set({ factionRelationships }),
  setCharacterRelationships: (characterRelationships) => set({ characterRelationships }),
  setMonsters: (monsters) => set({ monsters }),
  setInstances: (instances) => set({ instances }),
  setEntityAppearances: (entityAppearances) => set({ entityAppearances }),
  setStates: (states) => set({ states }),
  setEvents: (events) => set({ events }),
  setRedLines: (redLines) => set({ redLines }),
  setGags: (gags) => set({ gags }),
  setImportedChapters: (importedChapters) => set({ importedChapters }),

  refreshAssets: async () => {
    const project = get().currentProject;
    if (!project) return;
    set((state) => ({ loading: { ...state.loading, assets: true } }));
    try {
      const results = await Promise.allSettled([
        api.listCharacters(project.id),
        api.listForeshadows(project.id),
        api.listOutlines(project.id),
        api.listWorldSettings(project.id),
        api.listChapters(project.id),
        api.listFactions(project.id),
        api.listFactionRelationships(project.id),
        api.listCharacterRelationships(project.id),
        api.listMonsters(project.id),
        api.listInstances(project.id),
        api.listEntityAppearances(project.id),
        api.listStates(project.id),
        api.listEvents(project.id),
      ]);
      const keys = ["characters", "foreshadows", "outlines", "worldSettings", "chapters", "factions", "factionRelationships", "characterRelationships", "monsters", "instances", "entityAppearances", "states", "events"] as const;
      const updates: Partial<AppState> = {};
      results.forEach((r, i) => {
        if (r.status === "fulfilled") {
          (updates as any)[keys[i]] = r.value;
        }
      });
      set(updates as any);
    } finally {
      set((state) => ({ loading: { ...state.loading, assets: false } }));
    }
  },

  refreshCharacters: async () => {
    const project = get().currentProject;
    if (!project) return;
    set((state) => ({ loading: { ...state.loading, characters: true } }));
    try {
      const characters = await api.listCharacters(project.id);
      set({ characters });
    } finally {
      set((state) => ({ loading: { ...state.loading, characters: false } }));
    }
  },

  refreshForeshadows: async () => {
    const project = get().currentProject;
    if (!project) return;
    set((state) => ({ loading: { ...state.loading, foreshadows: true } }));
    try {
      const foreshadows = await api.listForeshadows(project.id);
      set({ foreshadows });
    } finally {
      set((state) => ({ loading: { ...state.loading, foreshadows: false } }));
    }
  },

  refreshOutlines: async () => {
    const project = get().currentProject;
    if (!project) return;
    set((state) => ({ loading: { ...state.loading, outlines: true } }));
    try {
      const outlines = await api.listOutlines(project.id);
      set({ outlines });
    } finally {
      set((state) => ({ loading: { ...state.loading, outlines: false } }));
    }
  },

  refreshWorldSettings: async () => {
    const project = get().currentProject;
    if (!project) return;
    set((state) => ({ loading: { ...state.loading, worldSettings: true } }));
    try {
      const worldSettings = await api.listWorldSettings(project.id);
      set({ worldSettings });
    } finally {
      set((state) => ({ loading: { ...state.loading, worldSettings: false } }));
    }
  },

  refreshFactions: async () => {
    const project = get().currentProject;
    if (!project) return;
    set((state) => ({ loading: { ...state.loading, factions: true } }));
    try {
      const factions = await api.listFactions(project.id);
      set({ factions });
    } finally {
      set((state) => ({ loading: { ...state.loading, factions: false } }));
    }
  },

  refreshFactionRelationships: async () => {
    const project = get().currentProject;
    if (!project) return;
    set((state) => ({ loading: { ...state.loading, factionRelationships: true } }));
    try {
      const factionRelationships = await api.listFactionRelationships(project.id);
      set({ factionRelationships });
    } finally {
      set((state) => ({ loading: { ...state.loading, factionRelationships: false } }));
    }
  },

  refreshCharacterRelationships: async () => {
    const project = get().currentProject;
    if (!project) return;
    set((state) => ({ loading: { ...state.loading, characterRelationships: true } }));
    try {
      const characterRelationships = await api.listCharacterRelationships(project.id);
      set({ characterRelationships });
    } finally {
      set((state) => ({ loading: { ...state.loading, characterRelationships: false } }));
    }
  },

  refreshMonsters: async () => {
    const project = get().currentProject;
    if (!project) return;
    set((state) => ({ loading: { ...state.loading, monsters: true } }));
    try {
      const monsters = await api.listMonsters(project.id);
      set({ monsters });
    } finally {
      set((state) => ({ loading: { ...state.loading, monsters: false } }));
    }
  },

  refreshInstances: async () => {
    const project = get().currentProject;
    if (!project) return;
    set((state) => ({ loading: { ...state.loading, instances: true } }));
    try {
      const instances = await api.listInstances(project.id);
      set({ instances });
    } finally {
      set((state) => ({ loading: { ...state.loading, instances: false } }));
    }
  },

  refreshRedLines: async () => {
    const project = get().currentProject;
    if (!project) return;
    set((state) => ({ loading: { ...state.loading, redLines: true } }));
    try {
      const redLines = await api.listRedLines(project.id);
      set({ redLines });
    } finally {
      set((state) => ({ loading: { ...state.loading, redLines: false } }));
    }
  },

  refreshGags: async () => {
    const project = get().currentProject;
    if (!project) return;
    set((state) => ({ loading: { ...state.loading, gags: true } }));
    try {
      const gags = await api.listGags(project.id);
      set({ gags });
    } finally {
      set((state) => ({ loading: { ...state.loading, gags: false } }));
    }
  },

  refreshImportedChapters: async () => {
    const project = get().currentProject;
    if (!project) return;
    set((state) => ({ loading: { ...state.loading, importedChapters: true } }));
    try {
      const importedChapters = await api.listImportedChapters(project.id);
      set({ importedChapters });
    } finally {
      set((state) => ({ loading: { ...state.loading, importedChapters: false } }));
    }
  },

  getEntityAppearances: (entityType, entityId) => {
    return get().entityAppearances.filter((a) => a.entity_type === entityType && String(a.entity_id) === String(entityId));
  },
});
