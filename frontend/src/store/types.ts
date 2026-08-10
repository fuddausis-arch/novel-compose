import type {
  Project, Character, Foreshadow, Outline, WorldSetting, ChapterListItem, Summary,
  GenreContext, Faction, FactionRelationship, CharacterRelationship, Monster, Instance,
  EntityAppearance, EntityType, StateChange, TruthEvent, ChatMessage, ChatHistoryMsg,
  InteractiveMode, RedLine, Gag, ImportedChapter,
} from "../types";
import type { StoreApi } from "zustand";

export type LoadingKey =
  | "projects" | "characters" | "foreshadows" | "outlines" | "worldSettings"
  | "chapters" | "summaries" | "genreContext" | "assets" | "states" | "events"
  | "factions" | "factionRelationships" | "characterRelationships" | "monsters"
  | "instances" | "entityAppearances" | "redLines" | "gags" | "importedChapters";

export type GenerationEvent =
  | { type: "node"; data: any }
  | { type: "review_pending"; data: any }
  | { type: "error"; data: any }
  | { type: "done"; data: any }
  | { type: "connection_error" };

export interface AppState {
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
  instances: Instance[];
  entityAppearances: EntityAppearance[];
  states: StateChange[];
  events: TruthEvent[];
  redLines: RedLine[];
  gags: Gag[];
  importedChapters: ImportedChapter[];
  loading: Record<LoadingKey, boolean>;
  pipelineEvents: string[];
  pipelineStatus: "idle" | "running" | "done" | "error";
  pipelineProgress: number;
  pipelineSource: "chapter" | "planning" | null;
  styleAnalysis: string;
  styleBenchmark: string;
  activeGeneration: {
    projectId: number;
    chapter: number;
    title: string;
    threadId: string;
    mode: "generate" | "resume";
    reviewDecision?: "approve" | "reject";
    reviewPendingData?: any;
  } | null;

  // 交互式创作状态（全局存储，支持切页后恢复）
  interactiveMessages: ChatMessage[];
  interactiveMode: InteractiveMode;
  interactiveInput: string;
  interactiveGenerating: boolean;
  interactiveUseWorkflow: boolean;  // MVP 26-agent 工作流模式开关
  interactiveNumVariants: number;   // 抽卡模式版本数：1=不抽卡，>1=生成 N 个候选版本
  interactiveElapsed: number;
  interactiveStreamThinking: { stage: string; detail: string }[];
  interactiveStreamContent: string;
  interactiveStreamReasoning: string;
  interactiveStreamType: "chapter" | "chat" | null;
  interactiveStreamActions: { type: string; status: string; [key: string]: any }[];
  interactiveStreamOptions: { label: string; value: string }[];
  interactiveLoadedProjectId: number | null;
  interactiveReconnecting: boolean;

  // 批量生成状态
  batchGenerating: boolean;
  batchProgress: { current: number; total: number; completed: number; failed: number };
  batchErrors: { chapter: number; error: string }[];

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
  setInstances: (instances: Instance[]) => void;
  setStates: (states: StateChange[]) => void;
  setEvents: (events: TruthEvent[]) => void;
  setRedLines: (redLines: RedLine[]) => void;
  setGags: (gags: Gag[]) => void;
  setImportedChapters: (importedChapters: ImportedChapter[]) => void;
  setLoading: (key: LoadingKey, value: boolean) => void;
  startPipeline: (label?: string, source?: "chapter" | "planning" | null) => void;
  addPipelineEvent: (msg: string, progress?: number) => void;
  setPipelineStatus: (status: "idle" | "running" | "done" | "error") => void;
  clearPipeline: () => void;
  setStyleAnalysis: (analysis: string, benchmark: string) => void;
  subscribeGeneration: (cb: (event: GenerationEvent) => void) => () => void;
  startGenerationStream: (projectId: number, chapter: number, title: string) => void;
  resumeGenerationStream: (projectId: number, threadId: string, decision: "approve" | "reject", feedback?: string, chapter?: number) => void;
  stopGenerationStream: () => void;

  // 交互式创作 actions
  setInteractiveMessages: (messages: ChatMessage[]) => void;
  setInteractiveMode: (mode: InteractiveMode) => void;
  setInteractiveInput: (input: string) => void;
  toggleInteractiveUseWorkflow: (on: boolean) => void;
  setInteractiveNumVariants: (n: number) => void;
  appendInteractiveMessage: (msg: ChatMessage) => void;
  updateInteractiveMessage: (index: number, updater: (msg: ChatMessage) => ChatMessage) => void;
  setInteractiveGenerating: (generating: boolean) => void;
  interactiveLoadMessages: (projectId: number) => Promise<void>;
  interactiveSaveMessages: (projectId: number, messages: ChatMessage[]) => Promise<void>;
  interactiveSend: (projectId: number, text: string, history: ChatHistoryMsg[], mode: InteractiveMode) => Promise<void>;
  interactiveResume: (projectId: number, threadId: string, decision: "approve" | "rewrite" | "polish", feedback: string, deepPolish: boolean, msgIndex: number) => Promise<void>;
  interactiveVariantResume: (projectId: number, threadId: string, selectedIndex: number, msgIndex: number) => Promise<void>;
  interactiveStop: () => void;

  // 批量生成 actions
  batchGenerate: (projectId: number, startChapter: number, endChapter: number) => Promise<void>;
  batchStop: () => void;

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
  refreshInstances: () => Promise<void>;
  refreshRedLines: () => Promise<void>;
  refreshGags: () => Promise<void>;
  refreshImportedChapters: () => Promise<void>;
  getEntityAppearances: (entityType: EntityType, entityId: string) => EntityAppearance[];

  // 私有运行时句柄（不参与 UI 渲染，仅供内部 action 使用）
  __generationSubscribers?: Set<(event: GenerationEvent) => void>;
  __currentEventSource?: EventSource | null;
  __interactiveAbortController?: AbortController | null;
  __interactiveElapsedTimer?: ReturnType<typeof setInterval> | null;
  __interactiveSaveTimeout?: ReturnType<typeof setTimeout> | null;
  __batchAbortController?: AbortController | null;
}

// 切片创建器：每个功能域切片返回 AppState 的部分字段 + actions。
// 通过共享的 set/get 组装进同一个 store，保证跨切片调用（如 refreshAssets 用
// currentProject、batch 用 refreshChapters）在组合后仍能正常工作。
export type SliceCreator = (
  set: StoreApi<AppState>["setState"],
  get: StoreApi<AppState>["getState"],
) => Partial<AppState>;
