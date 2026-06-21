import { create } from "zustand";
import { api } from "./api";
import type { Project, Character, Foreshadow, Outline, WorldSetting, ChapterListItem, Summary, GenreContext, Faction, FactionRelationship, CharacterRelationship, Monster, EntityAppearance, EntityType } from "./types";

type LoadingKey = "projects" | "characters" | "foreshadows" | "outlines" | "worldSettings" | "chapters" | "summaries" | "genreContext" | "assets";

interface AppState {
  projects: Project[];
  currentProject: Project | null;
  characters: Character[];
  foreshadows: Foreshadow[];
  outlines: Outline[];
  worldSettings: WorldSetting[];
  chapters: ChapterListItem[];
  summaries: Summary[];
  genreContext: GenreContext | null;
  factions: Faction[];
  factionRelationships: FactionRelationship[];
  characterRelationships: CharacterRelationship[];
  monsters: Monster[];
  entityAppearances: EntityAppearance[];
  loading: Record<LoadingKey, boolean>;

  setProjects: (projects: Project[]) => void;
  setEntityAppearances: (entityAppearances: EntityAppearance[]) => void;
  setCurrentProject: (project: Project | null) => void;
  setCharacters: (characters: Character[]) => void;
  setForeshadows: (foreshadows: Foreshadow[]) => void;
  setOutlines: (outlines: Outline[]) => void;
  setWorldSettings: (worldSettings: WorldSetting[]) => void;
  setChapters: (chapters: ChapterListItem[]) => void;
  setSummaries: (summaries: Summary[]) => void;
  setGenreContext: (genreContext: GenreContext | null) => void;
  setFactions: (factions: Faction[]) => void;
  setFactionRelationships: (factionRelationships: FactionRelationship[]) => void;
  setCharacterRelationships: (characterRelationships: CharacterRelationship[]) => void;
  setMonsters: (monsters: Monster[]) => void;
  setLoading: (key: LoadingKey, value: boolean) => void;

  refreshAssets: () => Promise<void>;
  refreshCharacters: () => Promise<void>;
  refreshForeshadows: () => Promise<void>;
  refreshOutlines: () => Promise<void>;
  refreshWorldSettings: () => Promise<void>;
  refreshChapters: () => Promise<void>;
  refreshProjects: () => Promise<void>;
  loadProject: (projectId: number) => Promise<Project>;
  refreshSummaries: () => Promise<void>;
  refreshGenreContext: () => Promise<void>;
  refreshFactions: () => Promise<void>;
  refreshFactionRelationships: () => Promise<void>;
  refreshCharacterRelationships: () => Promise<void>;
  refreshMonsters: () => Promise<void>;
  refreshEntityAppearances: () => Promise<void>;
  getEntityAppearances: (entityType: EntityType, entityId: string) => EntityAppearance[];
}

export const useAppStore = create<AppState>((set, get) => ({
  projects: [],
  currentProject: null,
  characters: [],
  foreshadows: [],
  outlines: [],
  worldSettings: [],
  chapters: [],
  summaries: [],
  genreContext: null,
  factions: [],
  factionRelationships: [],
  characterRelationships: [],
  monsters: [],
  entityAppearances: [],
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
  },

  setProjects: (projects) => set({ projects }),
  setCurrentProject: (project) => set({ currentProject: project }),
  setCharacters: (characters) => set({ characters }),
  setForeshadows: (foreshadows) => set({ foreshadows }),
  setOutlines: (outlines) => set({ outlines }),
  setWorldSettings: (worldSettings) => set({ worldSettings }),
  setChapters: (chapters) => set({ chapters }),
  setSummaries: (summaries) => set({ summaries }),
  setGenreContext: (genreContext) => set({ genreContext }),
  setFactions: (factions) => set({ factions }),
  setFactionRelationships: (factionRelationships) => set({ factionRelationships }),
  setCharacterRelationships: (characterRelationships) => set({ characterRelationships }),
  setMonsters: (monsters) => set({ monsters }),
  setEntityAppearances: (entityAppearances) => set({ entityAppearances }),
  setLoading: (key, value) => set((state) => ({ loading: { ...state.loading, [key]: value } })),

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
        api.listEntityAppearances(project.id),
      ]);
      const keys = ["characters", "foreshadows", "outlines", "worldSettings", "chapters", "factions", "factionRelationships", "characterRelationships", "monsters", "entityAppearances"] as const;
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

  refreshFactions: async () => {
    const project = get().currentProject;
    if (!project) return;
    set((state) => ({ loading: { ...state.loading, assets: true } }));
    try {
      const factions = await api.listFactions(project.id);
      set({ factions });
    } finally {
      set((state) => ({ loading: { ...state.loading, assets: false } }));
    }
  },

  refreshFactionRelationships: async () => {
    const project = get().currentProject;
    if (!project) return;
    set((state) => ({ loading: { ...state.loading, assets: true } }));
    try {
      const factionRelationships = await api.listFactionRelationships(project.id);
      set({ factionRelationships });
    } finally {
      set((state) => ({ loading: { ...state.loading, assets: false } }));
    }
  },

  refreshCharacterRelationships: async () => {
    const project = get().currentProject;
    if (!project) return;
    set((state) => ({ loading: { ...state.loading, assets: true } }));
    try {
      const characterRelationships = await api.listCharacterRelationships(project.id);
      set({ characterRelationships });
    } finally {
      set((state) => ({ loading: { ...state.loading, assets: false } }));
    }
  },

  refreshMonsters: async () => {
    const project = get().currentProject;
    if (!project) return;
    set((state) => ({ loading: { ...state.loading, assets: true } }));
    try {
      const monsters = await api.listMonsters(project.id);
      set({ monsters });
    } finally {
      set((state) => ({ loading: { ...state.loading, assets: false } }));
    }
  },

  refreshEntityAppearances: async () => {
    const project = get().currentProject;
    if (!project) return;
    set((state) => ({ loading: { ...state.loading, assets: true } }));
    try {
      const entityAppearances = await api.listEntityAppearances(project.id);
      set({ entityAppearances });
    } finally {
      set((state) => ({ loading: { ...state.loading, assets: false } }));
    }
  },

  getEntityAppearances: (entityType, entityId) => {
    return get().entityAppearances.filter((a) => a.entity_type === entityType && String(a.entity_id) === String(entityId));
  },
}));
