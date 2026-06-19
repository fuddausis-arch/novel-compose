import type { Project, Character, Foreshadow, Outline, WorldSetting, ChapterListItem, ChapterText, ReviewResult, ChapterBrief, Summary, GenreContext, PlanningResult, Faction, FactionRelationship, CharacterRelationship, Monster, ImportPreviewData, EntityAppearance, EntityType, AppearanceRole, LLMConfig, SuggestionItem } from "./types";

const API_BASE = "";

function extractErrorMessage(status: number, text: string): string {
  if (!text) return `请求失败（HTTP ${status}）`;
  try {
    const parsed = JSON.parse(text);
    if (parsed.detail) return String(parsed.detail);
    if (parsed.message) return String(parsed.message);
  } catch {
    // 不是 JSON，直接返回原文
  }
  return text;
}

async function request<T>(path: string, options: RequestInit = {}): Promise<T> {
  const isFormData = options.body instanceof FormData;
  const res = await fetch(`${API_BASE}${path}`, {
    headers: isFormData ? undefined : { "Content-Type": "application/json" },
    ...options,
  });
  if (!res.ok) {
    const text = await res.text().catch(() => "Unknown error");
    throw new Error(extractErrorMessage(res.status, text));
  }
  if (res.status === 204) return undefined as T;
  return res.json();
}

export const api = {
  // Projects
  listProjects: () => request<Project[]>("/api/projects"),
  getProject: (id: number) => request<Project>(`/api/projects/${id}`),
  createProject: (data: Partial<Project> & { template_key?: string }) => request<Project>("/api/projects", { method: "POST", body: JSON.stringify(data) }),
  updateProject: (id: number, data: Partial<Project>) => request<Project>(`/api/projects/${id}`, { method: "PUT", body: JSON.stringify(data) }),
  deleteProject: (id: number) => request<void>(`/api/projects/${id}`, { method: "DELETE" }),
  listGenreTemplates: () => request<{ key: string; title: string; description: string }[]>("/api/projects/templates/genres"),

  // Bible: characters
  listCharacters: (projectId: number) => request<Character[]>(`/api/bible/${projectId}/characters`),
  createCharacter: (projectId: number, data: Partial<Character>) => request<Character>(`/api/bible/${projectId}/characters`, { method: "POST", body: JSON.stringify(data) }),
  updateCharacter: (projectId: number, name: string, data: Partial<Character>) => request<Character>(`/api/bible/${projectId}/characters/${encodeURIComponent(name)}`, { method: "PUT", body: JSON.stringify(data) }),
  deleteCharacter: (projectId: number, name: string) => request<void>(`/api/bible/${projectId}/characters/${encodeURIComponent(name)}`, { method: "DELETE" }),

  // Bible: foreshadows
  listForeshadows: (projectId: number) => request<Foreshadow[]>(`/api/bible/${projectId}/foreshadows`),
  createForeshadow: (projectId: number, data: Partial<Foreshadow>) => request<Foreshadow>(`/api/bible/${projectId}/foreshadows`, { method: "POST", body: JSON.stringify(data) }),
  updateForeshadow: (projectId: number, id: string, data: Partial<Foreshadow>) => request<Foreshadow>(`/api/bible/${projectId}/foreshadows/${encodeURIComponent(id)}`, { method: "PUT", body: JSON.stringify(data) }),
  deleteForeshadow: (projectId: number, id: string) => request<void>(`/api/bible/${projectId}/foreshadows/${encodeURIComponent(id)}`, { method: "DELETE" }),

  // Bible: world settings
  listWorldSettings: (projectId: number) => request<WorldSetting[]>(`/api/bible/${projectId}/world-settings`),
  createWorldSetting: (projectId: number, data: Partial<WorldSetting>) => request<WorldSetting>(`/api/bible/${projectId}/world-settings`, { method: "POST", body: JSON.stringify(data) }),
  updateWorldSetting: (projectId: number, id: number, data: Partial<WorldSetting>) => request<WorldSetting>(`/api/bible/${projectId}/world-settings/${id}`, { method: "PUT", body: JSON.stringify(data) }),
  deleteWorldSetting: (projectId: number, id: number) => request<void>(`/api/bible/${projectId}/world-settings/${id}`, { method: "DELETE" }),

  // Bible: outlines
  listOutlines: (projectId: number, level?: string, parentId?: number) => {
    const params = new URLSearchParams();
    if (level) params.append("level", level);
    if (parentId !== undefined) params.append("parent_id", String(parentId));
    const query = params.toString() ? `?${params.toString()}` : "";
    return request<Outline[]>(`/api/bible/${projectId}/outlines${query}`);
  },
  createOutline: (projectId: number, data: Partial<Outline>) => request<Outline>(`/api/bible/${projectId}/outlines`, { method: "POST", body: JSON.stringify(data) }),
  updateOutline: (projectId: number, id: number, data: Partial<Outline>) => request<Outline>(`/api/bible/${projectId}/outlines/${id}`, { method: "PUT", body: JSON.stringify(data) }),
  deleteOutline: (projectId: number, id: number) => request<void>(`/api/bible/${projectId}/outlines/${id}`, { method: "DELETE" }),

  // Bible: factions
  listFactions: (projectId: number) => request<Faction[]>(`/api/bible/${projectId}/factions`),
  createFaction: (projectId: number, data: Partial<Faction>) => request<Faction>(`/api/bible/${projectId}/factions`, { method: "POST", body: JSON.stringify(data) }),
  updateFaction: (projectId: number, id: number, data: Partial<Faction>) => request<Faction>(`/api/bible/${projectId}/factions/${id}`, { method: "PUT", body: JSON.stringify(data) }),
  deleteFaction: (projectId: number, id: number) => request<void>(`/api/bible/${projectId}/factions/${id}`, { method: "DELETE" }),

  // Bible: faction relationships
  listFactionRelationships: (projectId: number) => request<FactionRelationship[]>(`/api/bible/${projectId}/faction-relationships`),
  createFactionRelationship: (projectId: number, data: Partial<FactionRelationship>) => request<FactionRelationship>(`/api/bible/${projectId}/faction-relationships`, { method: "POST", body: JSON.stringify(data) }),
  updateFactionRelationship: (projectId: number, id: number, data: Partial<FactionRelationship>) => request<FactionRelationship>(`/api/bible/${projectId}/faction-relationships/${id}`, { method: "PUT", body: JSON.stringify(data) }),
  deleteFactionRelationship: (projectId: number, id: number) => request<void>(`/api/bible/${projectId}/faction-relationships/${id}`, { method: "DELETE" }),

  // Bible: character relationships
  listCharacterRelationships: (projectId: number) => request<CharacterRelationship[]>(`/api/bible/${projectId}/character-relationships`),
  createCharacterRelationship: (projectId: number, data: Partial<CharacterRelationship>) => request<CharacterRelationship>(`/api/bible/${projectId}/character-relationships`, { method: "POST", body: JSON.stringify(data) }),
  updateCharacterRelationship: (projectId: number, id: number, data: Partial<CharacterRelationship>) => request<CharacterRelationship>(`/api/bible/${projectId}/character-relationships/${id}`, { method: "PUT", body: JSON.stringify(data) }),
  deleteCharacterRelationship: (projectId: number, id: number) => request<void>(`/api/bible/${projectId}/character-relationships/${id}`, { method: "DELETE" }),

  // Bible: monsters
  listMonsters: (projectId: number) => request<Monster[]>(`/api/bible/${projectId}/monsters`),
  createMonster: (projectId: number, data: Partial<Monster>) => request<Monster>(`/api/bible/${projectId}/monsters`, { method: "POST", body: JSON.stringify(data) }),
  updateMonster: (projectId: number, id: number, data: Partial<Monster>) => request<Monster>(`/api/bible/${projectId}/monsters/${id}`, { method: "PUT", body: JSON.stringify(data) }),
  deleteMonster: (projectId: number, id: number) => request<void>(`/api/bible/${projectId}/monsters/${id}`, { method: "DELETE" }),

  // Entity appearances
  listEntityAppearances: (projectId: number, params?: { entity_type?: EntityType; entity_id?: string; chapter?: number }) => {
    const qs = new URLSearchParams();
    if (params?.entity_type) qs.append("entity_type", params.entity_type);
    if (params?.entity_id) qs.append("entity_id", String(params.entity_id));
    if (params?.chapter !== undefined) qs.append("chapter", String(params.chapter));
    const query = qs.toString() ? `?${qs.toString()}` : "";
    return request<EntityAppearance[]>(`/api/bible/${projectId}/entity-appearances${query}`);
  },
  createEntityAppearance: (projectId: number, data: Partial<EntityAppearance>) => request<EntityAppearance>(`/api/bible/${projectId}/entity-appearances`, { method: "POST", body: JSON.stringify(data) }),
  updateEntityAppearance: (projectId: number, id: number, data: Partial<EntityAppearance>) => request<EntityAppearance>(`/api/bible/${projectId}/entity-appearances/${id}`, { method: "PUT", body: JSON.stringify(data) }),
  deleteEntityAppearance: (projectId: number, id: number) => request<void>(`/api/bible/${projectId}/entity-appearances/${id}`, { method: "DELETE" }),
  recordChapterAppearances: (projectId: number, chapter: number, data: { appearances: { entity_type: EntityType; entity_id: string; role_in_chapter: AppearanceRole; context_snippet?: string }[] }) =>
    request<{ recorded: number }>(`/api/bible/${projectId}/chapters/${chapter}/record-appearances`, { method: "POST", body: JSON.stringify(data) }),

  // AI generation: entities
  generateCharacter: (projectId: number, data?: Partial<Character>) => request<Character>(`/api/bible/${projectId}/generate-character`, { method: "POST", body: JSON.stringify(data || {}) }),
  generateFaction: (projectId: number, data?: Partial<Faction>) => request<Faction>(`/api/bible/${projectId}/generate-faction`, { method: "POST", body: JSON.stringify(data || {}) }),
  generateMonster: (projectId: number, data?: Partial<Monster>) => request<Monster>(`/api/bible/${projectId}/generate-monster`, { method: "POST", body: JSON.stringify(data || {}) }),
  generateCharacterRelationship: (projectId: number, data: { source_character?: string; target_character?: string } & Partial<CharacterRelationship>) =>
    request<CharacterRelationship>(`/api/bible/${projectId}/generate-character-relationship`, { method: "POST", body: JSON.stringify(data) }),

  // Summaries
  listSummaries: (projectId: number) => request<Summary[]>(`/api/bible/${projectId}/summaries`),
  deleteSummary: (projectId: number, chapter: number) => request<void>(`/api/bible/${projectId}/summaries/${chapter}`, { method: "DELETE" }),

  // Import
  importStructured: (projectId: number, data: Partial<ImportPreviewData>) => request<{ imported: { world_settings: number; factions: number; faction_relationships: number; character_relationships: number; characters: number; foreshadows: number; outlines: number; monsters: number } }>(`/api/bible/${projectId}/import`, { method: "POST", body: JSON.stringify(data) }),
  importDocument: (projectId: number, content: string) => request<{ imported: { world_settings: number; factions: number; faction_relationships: number; character_relationships: number; characters: number; foreshadows: number; outlines: number; monsters: number }; raw_summary: { world_settings: number; factions: number; faction_relationships: number; character_relationships: number; characters: number; foreshadows: number; outlines: number; monsters: number } }>(`/api/bible/${projectId}/import-document`, { method: "POST", body: JSON.stringify({ content }) }),
  importFile: (projectId: number, file: File) => {
    const formData = new FormData();
    formData.append("file", file);
    return request<{ imported: { world_settings: number; factions: number; faction_relationships: number; character_relationships: number; characters: number; foreshadows: number; outlines: number; monsters: number }; raw_summary: { world_settings: number; factions: number; faction_relationships: number; character_relationships: number; characters: number; foreshadows: number; outlines: number; monsters: number } }>(`/api/bible/${projectId}/import-file`, { method: "POST", body: formData });
  },
  parseDocument: (projectId: number, content: string) => request<ImportPreviewData>(`/api/bible/${projectId}/parse-document`, { method: "POST", body: JSON.stringify({ content }) }),
  parseFile: (projectId: number, file: File) => {
    const formData = new FormData();
    formData.append("file", file);
    return request<ImportPreviewData>(`/api/bible/${projectId}/parse-file`, { method: "POST", body: formData });
  },

  // Genre context
  getGenreContext: (projectId: number) => request<GenreContext>("/api/generation/genre-context", { method: "POST", body: JSON.stringify({ project_id: projectId }) }),

  // Consistency dashboard
  getConsistencyDashboard: (projectId: number) => request<{ stats: any; recent_state_changes: any[]; unresolved_foreshadows: any[]; overdue_foreshadows: any[]; recent_events: any[]; conflicts: any[] }>(`/api/bible/${projectId}/consistency-dashboard`),

  // Generation
  generateWorld: (projectId: number, requirements: string, style: string) => request<{ created: number; items: Partial<WorldSetting>[] }>("/api/generation/world/generate", { method: "POST", body: JSON.stringify({ project_id: projectId, requirements, style }) }),
  generateCharacters: (projectId: number, protagonistCount: number, supportingCount: number, antagonistCount: number, style: string) => request<{ created: number; items: Partial<Character>[] }>("/api/generation/characters/generate", { method: "POST", body: JSON.stringify({ project_id: projectId, protagonist_count: protagonistCount, supporting_count: supportingCount, antagonist_count: antagonistCount, style }) }),
  generateVolumes: (projectId: number, count: number, customPrompt: string) => request<{ created: number; items: Partial<Outline>[] }>("/api/generation/volumes/generate", { method: "POST", body: JSON.stringify({ project_id: projectId, count, custom_prompt: customPrompt }) }),
  generateArcs: (projectId: number, parentId: number, count: number, customPrompt: string) => request<{ created: number; items: Partial<Outline>[] }>("/api/generation/arcs/generate", { method: "POST", body: JSON.stringify({ project_id: projectId, parent_id: parentId, count, custom_prompt: customPrompt }) }),
  generateChapters: (projectId: number, parentId: number, count: number, customPrompt: string) => request<{ created: number; items: Partial<Outline>[] }>("/api/generation/chapters/generate", { method: "POST", body: JSON.stringify({ project_id: projectId, parent_id: parentId, count, custom_prompt: customPrompt }) }),
  generateChapterBrief: (projectId: number, chapter: number, title: string) => request<ChapterBrief>("/api/generation/chapter/brief", { method: "POST", body: JSON.stringify({ project_id: projectId, chapter, title }) }),
  reviewChapter: (projectId: number, chapter: number) => request<ReviewResult>("/api/generation/chapter/review", { method: "POST", body: JSON.stringify({ project_id: projectId, chapter }) }),
  commitChapter: (projectId: number, chapter: number) => request<{ chapter: number; committed: boolean; summary: string; deltas: number; relationships: number; events: number; foreshadow_updates: number }>("/api/generation/chapter/commit", { method: "POST", body: JSON.stringify({ project_id: projectId, chapter }) }),
  suggest: (projectId: number, contextType: string, contextId: string | number, suggestType: string, count: number, customPrompt: string) =>
    request<{ suggestions: SuggestionItem[] }>("/api/generation/suggest", {
      method: "POST",
      body: JSON.stringify({
        project_id: projectId,
        context_type: contextType,
        context_id: String(contextId),
        suggest_type: suggestType,
        count,
        custom_prompt: customPrompt,
      }),
    }),
  adoptSuggestions: (projectId: number, data: {
    context_type: string;
    context_id: string | number;
    suggest_type: string;
    prompt: string;
    raw_response: string;
    status: "adopted" | "partial" | "rejected";
    suggestions: SuggestionItem[];
  }) => request<{ created: Record<string, { id: number; title?: string; name?: string }[]> }>("/api/generation/suggest/adopt", {
    method: "POST",
    body: JSON.stringify({
      project_id: projectId,
      ...data,
      context_id: String(data.context_id),
    }),
  }),

  // Chapters
  listChapters: (projectId: number) => request<ChapterListItem[]>(`/api/chapters/list?project_id=${projectId}`),
  getChapterText: (chapter: number) => request<ChapterText>(`/api/chapters/${chapter}/text`),
  saveChapterText: (chapter: number, title: string, content: string) => request<void>(`/api/chapters/${chapter}/text`, { method: "PUT", body: JSON.stringify({ title, content }) }),
  deleteChapter: (chapter: number) => request<void>(`/api/chapters/${chapter}`, { method: "DELETE" }),
  exportTxt: (projectId: number) => `/api/chapters/export/txt?project_id=${projectId}`,
  generateStream: (projectId: number, chapter: number, title: string, threadId?: string) => {
    const params = new URLSearchParams({ project_id: String(projectId), chapter: String(chapter), title });
    if (threadId) params.append("thread_id", threadId);
    return new EventSource(`/api/chapters/generate/stream?${params.toString()}`);
  },

  // Planning
  runPlanning: (projectId: number, volume: string, chapterCount: number, threadId?: string) => request<PlanningResult>("/api/planning/run", { method: "POST", body: JSON.stringify({ project_id: projectId, volume, chapter_count: chapterCount, thread_id: threadId || crypto.randomUUID() }) }),
  resumePlanning: (projectId: number, threadId: string, approved: boolean, edits?: string) => request<PlanningResult>("/api/planning/resume", { method: "POST", body: JSON.stringify({ project_id: projectId, thread_id: threadId, approved, edits: edits || "" }) }),

  // Config
  getLLMConfig: () => request<LLMConfig>("/api/config/llm"),
  updateLLMConfig: (data: Partial<LLMConfig>) => request<{ saved: boolean; context_length?: number }>("/api/config/llm", { method: "PUT", body: JSON.stringify(data) }),
  testLLMConfig: (data?: Partial<LLMConfig>) => request<{ ok: boolean; response: string; context_length?: number }>("/api/config/llm/test", { method: "POST", body: JSON.stringify(data || {}) }),
};
