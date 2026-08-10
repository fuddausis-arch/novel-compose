import type { Project, Character, Foreshadow, Outline, WorldSetting, ChapterListItem, ChapterText, ReviewResult, ChapterBrief, Summary, GenreContext, PlanningResult, PlanningIssue, Faction, FactionRelationship, CharacterRelationship, Monster, Instance, ImportPreviewData, ImportCounts, EntityAppearance, EntityType, LLMConfig, AgentLLMConfig, EmbeddingConfig, SuggestionItem, StateChange, TruthEvent, ChapterCommitResult, ChatHistoryMsg, InteractiveChatResponse, RedLine, Gag, ImportedChapter, ImportedChapterDetail, PlotDebt, RelationshipChange, AiStyleReport, AiStyleRepairResult, DeepAiStyleReport, AiModelStatus, Storyline, StorylineMeta, StorylineDetail, StorylineNode, StorylineRelation, ScanAlert } from "./types";
import type { ChatSession, ChatMessageItem, ChatSendPayload, ChatChunkEvent, ChatActionEvent } from "./types/chat";

// 后端 API 地址。默认同源（浏览器走 vite 代理 / 后端静态托管）。
// 打包手机 App 时通过 VITE_API_BASE 注入远程服务器地址，如 https://api.example.com
const API_BASE = (import.meta.env.VITE_API_BASE as string | undefined) || "";

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

async function request<T>(path: string, options: RequestInit = {}, timeoutMs?: number): Promise<T> {
  const isFormData = options.body instanceof FormData;
  // 鉴权：服务端设置 NOVEL_API_TOKEN 后，客户端从 localStorage 读同一 token 附在 X-API-Token
  const apiToken = localStorage.getItem("novel_api_token");
  const authHeaders: Record<string, string> = {};
  if (apiToken) authHeaders["X-API-Token"] = apiToken;
  // 超时保护：防止 HTTP 连接断开后 fetch 永久挂起导致 UI 卡死
  const controller = new AbortController();
  const timer = timeoutMs ? setTimeout(() => controller.abort(), timeoutMs) : null;
  try {
    const res = await fetch(`${API_BASE}${path}`, {
      headers: isFormData ? undefined : { "Content-Type": "application/json", ...authHeaders },
      signal: controller.signal,
      ...options,
    });
    if (!res.ok) {
      const text = await res.text().catch(() => "Unknown error");
      const err = new Error(extractErrorMessage(res.status, text)) as Error & { status: number };
      err.status = res.status;
      throw err;
    }
    if (res.status === 204) return undefined as T;
    return res.json();
  } catch (e: any) {
    if (e.name === "AbortError") {
      throw new Error("请求超时（连接可能已断开），请刷新页面后重试");
    }
    throw e;
  } finally {
    if (timer) clearTimeout(timer);
  }
}

// 生成类请求的超时时间：35 分钟（LLM 生成 128k tokens 可能需要 10-30 分钟）
const GEN_TIMEOUT = 35 * 60 * 1000;

export const api = {
  // Projects
  listProjects: () => request<Project[]>("/api/projects"),
  getProject: (id: number) => request<Project>(`/api/projects/${id}`),
  createProject: (data: { title: string } & Partial<Project> & { template_key?: string }) => request<Project>("/api/projects", { method: "POST", body: JSON.stringify(data) }),
  updateProject: (id: number, data: Partial<Project>) => request<Project>(`/api/projects/${id}`, { method: "PUT", body: JSON.stringify(data) }),
  deleteProject: (id: number, purgeData: boolean = true) => request<{ deleted: boolean; project_id: number; data_purged: number }>(`/api/projects/${id}?purge_data=${purgeData}`, { method: "DELETE" }),
  listGenreTemplates: () => request<{ key: string; title: string; description: string }[]>("/api/projects/templates/genres"),

  // Bible: characters
  listCharacters: (projectId: number) => request<Character[]>(`/api/bible/${projectId}/characters`),
  createCharacter: (projectId: number, data: Partial<Character>) => request<Character>(`/api/bible/${projectId}/characters`, { method: "POST", body: JSON.stringify(data) }),
  updateCharacter: (projectId: number, characterId: number, data: Partial<Character>) => request<Character>(`/api/bible/${projectId}/characters/${characterId}`, { method: "PUT", body: JSON.stringify(data) }),
  deleteCharacter: (projectId: number, characterId: number) => request<void>(`/api/bible/${projectId}/characters/${characterId}`, { method: "DELETE" }),

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
  batchDeleteOutlines: (projectId: number, ids: number[]) => request<{ deleted: number[]; failed: number[]; deleted_count: number }>(`/api/bible/${projectId}/outlines/batch-delete`, { method: "POST", body: JSON.stringify(ids) }),
  renumberOutlines: (projectId: number, level: string, parentId?: number) => {
    const params = new URLSearchParams({ level });
    if (parentId) params.append("parent_id", String(parentId));
    return request<{ level: string; total: number; renumbered: number }>(`/api/bible/${projectId}/outlines/renumber?${params.toString()}`, { method: "POST" });
  },
  enrichOutline: (projectId: number, outlineId: number, customPrompt?: string) => request<{ ok: boolean; outline_id: number; updated_fields: string[]; summary: string }>("/api/generation/outlines/enrich", { method: "POST", body: JSON.stringify({ project_id: projectId, outline_id: outlineId, custom_prompt: customPrompt || "" }) }),

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

  // Bible: instances（副本/特殊场景）
  listInstances: (projectId: number) => request<Instance[]>(`/api/bible/${projectId}/instances`),
  createInstance: (projectId: number, data: Partial<Instance>) => request<Instance>(`/api/bible/${projectId}/instances`, { method: "POST", body: JSON.stringify(data) }),
  updateInstance: (projectId: number, id: number, data: Partial<Instance>) => request<Instance>(`/api/bible/${projectId}/instances/${id}`, { method: "PUT", body: JSON.stringify(data) }),
  deleteInstance: (projectId: number, id: number) => request<void>(`/api/bible/${projectId}/instances/${id}`, { method: "DELETE" }),

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

  // Summaries
  listSummaries: (projectId: number) => request<Summary[]>(`/api/bible/${projectId}/summaries`),
  deleteSummary: (projectId: number, chapter: number) => request<void>(`/api/bible/${projectId}/summaries/${chapter}`, { method: "DELETE" }),

  // State changes & events
  listStates: (projectId: number) => request<StateChange[]>(`/api/bible/${projectId}/states`),
  listEvents: (projectId: number) => request<TruthEvent[]>(`/api/bible/${projectId}/events`),

  // Bible: plot debts（剧情债）
  listPlotDebts: (projectId: number, status?: string) => {
    const qs = status ? `?status=${encodeURIComponent(status)}` : "";
    return request<PlotDebt[]>(`/api/bible/${projectId}/plot-debts${qs}`);
  },
  createPlotDebt: (projectId: number, data: Partial<PlotDebt>) => request<PlotDebt>(`/api/bible/${projectId}/plot-debts`, { method: "POST", body: JSON.stringify(data) }),
  updatePlotDebt: (projectId: number, debtId: number, data: Partial<PlotDebt>) => request<PlotDebt>(`/api/bible/${projectId}/plot-debts/${debtId}`, { method: "PUT", body: JSON.stringify(data) }),
  deletePlotDebt: (projectId: number, debtId: number) => request<{ deleted: boolean }>(`/api/bible/${projectId}/plot-debts/${debtId}`, { method: "DELETE" }),

  // Bible: relationship changes（关系变更）
  listRelationshipChanges: (projectId: number) => request<RelationshipChange[]>(`/api/bible/${projectId}/relationship-changes`),

  // Bible: 单条 AI 生成（architect 模型）
  generateFaction: (projectId: number, req: { name_hint?: string; type?: string; alignment?: string }) =>
    request<Faction>(`/api/bible/${projectId}/generate-faction`, { method: "POST", body: JSON.stringify(req) }, GEN_TIMEOUT),
  generateMonster: (projectId: number, req: { name_hint?: string; rank?: string; species?: string }) =>
    request<Monster>(`/api/bible/${projectId}/generate-monster`, { method: "POST", body: JSON.stringify(req) }, GEN_TIMEOUT),
  generateCharacter: (projectId: number, req: { name_hint?: string; role_hint?: string; importance_hint?: string }) =>
    request<Character>(`/api/bible/${projectId}/generate-character`, { method: "POST", body: JSON.stringify(req) }, GEN_TIMEOUT),
  generateCharacterRelationship: (projectId: number, req: { source_character?: string; target_character?: string; relation_type_hint?: string }) =>
    request<CharacterRelationship>(`/api/bible/${projectId}/generate-character-relationship`, { method: "POST", body: JSON.stringify(req) }, GEN_TIMEOUT),

  // Cron 定时任务
  listCronJobs: () => request<{ jobs: any[]; total: number }>("/api/cron"),
  createCronJob: (data: { id: string; name: string; schedule: string; workflow_type: string; parameters?: Record<string, unknown>; enabled: boolean }) =>
    request<{ success: boolean; job: any }>("/api/cron", { method: "POST", body: JSON.stringify(data) }),
  updateCronJob: (jobId: string, data: { name?: string; schedule?: string; workflow_type?: string; parameters?: Record<string, unknown>; enabled?: boolean }) =>
    request<{ success: boolean; job: any }>(`/api/cron/${encodeURIComponent(jobId)}`, { method: "PUT", body: JSON.stringify(data) }),
  deleteCronJob: (jobId: string) => request<{ success: boolean }>(`/api/cron/${encodeURIComponent(jobId)}`, { method: "DELETE" }),
  triggerCronJob: (jobId: string) => request<any>(`/api/cron/${encodeURIComponent(jobId)}/trigger`, { method: "POST" }),
  toggleCronJob: (jobId: string, enabled: boolean) => request<{ success: boolean; enabled: boolean }>(`/api/cron/${encodeURIComponent(jobId)}/toggle?enabled=${enabled}`, { method: "POST" }),

  // Chapters: 批量删除
  batchDeleteChapters: (projectId: number, chapters: number[]) =>
    request<{ deleted: number[]; failed: number[]; deleted_count: number }>(`/api/chapters/batch-delete?project_id=${projectId}`, { method: "POST", body: JSON.stringify(chapters) }),

  // Workspace: 会话树 / 分支 / 附件
  getSessionTree: (projectId: number) => request<{ sessions: any[] }>(`/api/workspace/sessions/${projectId}/tree`),
  branchSession: (sessionId: string, projectId: number, title: string) =>
    request<{ session_id: string; parent_session_id: string; title: string }>(
      `/api/workspace/sessions/${encodeURIComponent(sessionId)}/branch`,
      { method: "POST", body: JSON.stringify({ project_id: projectId, parent_session_id: sessionId, title }) },
    ),
  listWorkspaceAttachments: (projectId: number, sessionId: string) =>
    request<{ attachments: { filename: string; size: number; modified_at: string }[] }>(
      `/api/workspace/attachments/${encodeURIComponent(sessionId)}?project_id=${projectId}`,
    ),

  // Plugins: 资产导入导出（skills/rules/preset_phrases → .naassets）
  exportPluginAssets: (outputPath: string, include: string[] = ["skills", "rules", "preset_phrases"]) =>
    request<{ status: string; path: string; counts: Record<string, number> }>("/api/plugins/assets/export", { method: "POST", body: JSON.stringify({ output_path: outputPath, include }) }),
  inspectPluginAssets: (packagePath: string) =>
    request<{ status: string; manifest?: any; files?: string[] }>("/api/plugins/assets/inspect", { method: "POST", body: JSON.stringify({ package_path: packagePath }) }),
  importPluginAssets: (packagePath: string, strategy: "merge" | "overwrite" = "merge") =>
    request<{ status: string; imported: Record<string, number>; skipped: Record<string, number> }>("/api/plugins/assets/import", { method: "POST", body: JSON.stringify({ package_path: packagePath, strategy }) }),

  // Agents: 删除 Agent 定义
  deleteAgent: (agentType: string) => request<{ deleted: boolean; agent_type: string }>(`/api/agents/${encodeURIComponent(agentType)}`, { method: "DELETE" }),

  // Import
  importStructured: (projectId: number, data: Partial<ImportPreviewData>) => request<{ imported: ImportCounts }>(`/api/bible/${projectId}/import`, { method: "POST", body: JSON.stringify(data) }),
  importDocument: (projectId: number, content: string) => request<{ imported: ImportCounts; raw_summary: ImportCounts }>(`/api/bible/${projectId}/import-document`, { method: "POST", body: JSON.stringify({ content }) }),
  importFile: (projectId: number, file: File) => {
    const formData = new FormData();
    formData.append("file", file);
    return request<{ imported: ImportCounts; raw_summary: ImportCounts }>(`/api/bible/${projectId}/import-file`, { method: "POST", body: formData });
  },
  parseDocument: (projectId: number, content: string) => request<ImportPreviewData>(`/api/bible/${projectId}/parse-document`, { method: "POST", body: JSON.stringify({ content }) }),
  parseFile: (projectId: number, file: File) => {
    const formData = new FormData();
    formData.append("file", file);
    return request<ImportPreviewData>(`/api/bible/${projectId}/parse-file`, { method: "POST", body: formData });
  },
  scanFolder: (projectId: number, folderPath: string, overwrite: boolean = false) => request<{
    total_files: number; extracted_files: number; failed_files: number; merged_chars: number;
    imported: Record<string, number>;
    imported_items: Record<string, { name?: string; title?: string; role?: string; category?: string; type?: string; order?: number; level?: string; description?: string; source_character?: string; target_character?: string; relation_type?: string; species?: string }[]>;
    extracted_file_list: { path: string; chars: number }[];
    failed: { path: string; error: string }[];
  }>(`/api/bible/${projectId}/scan-folder`, { method: "POST", body: JSON.stringify({ folder_path: folderPath, overwrite }) }),

  // Genre context
  getGenreContext: (projectId: number) => request<GenreContext>("/api/generation/genre-context", { method: "POST", body: JSON.stringify({ project_id: projectId }) }),

  // Consistency dashboard
  getConsistencyDashboard: (projectId: number) => request<{ stats: any; recent_state_changes: any[]; unresolved_foreshadows: any[]; overdue_foreshadows: any[]; recent_events: any[]; conflicts: any[] }>(`/api/bible/${projectId}/consistency-dashboard`),

  // Generation
  generateWorld: (projectId: number, requirements: string, style: string) => request<{ created: number; items: Partial<WorldSetting>[]; warning?: string }>("/api/generation/world/generate", { method: "POST", body: JSON.stringify({ project_id: projectId, requirements, style }) }, GEN_TIMEOUT),
  generateCharacters: (projectId: number, protagonistCount: number, supportingCount: number, antagonistCount: number, style: string) => request<{ created: number; items: Partial<Character>[] }>("/api/generation/characters/generate", { method: "POST", body: JSON.stringify({ project_id: projectId, protagonist_count: protagonistCount, supporting_count: supportingCount, antagonist_count: antagonistCount, style }) }, GEN_TIMEOUT),
  importWorld: (projectId: number, items: any[]) => request<{ created: number; items: any[] }>(`/api/generation/world/import`, { method: "POST", body: JSON.stringify({ project_id: projectId, items }) }),
  importCharacters: (projectId: number, items: any[]) => request<{ created: number; items: any[] }>(`/api/generation/characters/import`, { method: "POST", body: JSON.stringify({ project_id: projectId, items }) }),
  generateVolumes: (projectId: number, count: number, customPrompt: string) => request<{ created: number; items: Partial<Outline>[] }>("/api/generation/volumes/generate", { method: "POST", body: JSON.stringify({ project_id: projectId, count, custom_prompt: customPrompt }) }, GEN_TIMEOUT),
  generateArcs: (projectId: number, parentId: number, count: number, customPrompt: string) => request<{ created: number; items: Partial<Outline>[] }>("/api/generation/arcs/generate", { method: "POST", body: JSON.stringify({ project_id: projectId, parent_id: parentId, count, custom_prompt: customPrompt }) }, GEN_TIMEOUT),
  generateChapters: (projectId: number, parentId: number, count: number, customPrompt: string) => request<{ created: number; items: Partial<Outline>[]; warning?: string }>("/api/generation/chapters/generate", { method: "POST", body: JSON.stringify({ project_id: projectId, parent_id: parentId, count, custom_prompt: customPrompt }) }, GEN_TIMEOUT),
  generateChaptersByVolume: (projectId: number, volumeId: number, count: number, customPrompt: string) => request<{ created: number; items: Partial<Outline>[]; warning?: string }>("/api/generation/chapters/generate-by-volume", { method: "POST", body: JSON.stringify({ project_id: projectId, volume_id: volumeId, count, custom_prompt: customPrompt }) }, GEN_TIMEOUT),

  // 流式生成（SSE）：生成一条推送一条，支持中断
  generateVolumesStream: (projectId: number, count: number, customPrompt: string) => {
    const params = new URLSearchParams({
      project_id: String(projectId), count: String(count), custom_prompt: customPrompt || "",
    });
    return new EventSource(`${API_BASE}/api/generation/volumes/generate/stream?${params.toString()}`);
  },
  generateArcsStream: (projectId: number, parentId: number, count: number, customPrompt: string) => {
    const params = new URLSearchParams({
      project_id: String(projectId), parent_id: String(parentId),
      count: String(count), custom_prompt: customPrompt || "",
    });
    return new EventSource(`${API_BASE}/api/generation/arcs/generate/stream?${params.toString()}`);
  },
  generateChaptersStream: (projectId: number, parentId: number, count: number, customPrompt: string) => {
    const params = new URLSearchParams({
      project_id: String(projectId), parent_id: String(parentId),
      count: String(count), custom_prompt: customPrompt || "",
    });
    return new EventSource(`${API_BASE}/api/generation/chapters/generate/stream?${params.toString()}`);
  },
  generateChaptersByVolumeStream: (projectId: number, volumeId: number, count: number, customPrompt: string) => {
    const params = new URLSearchParams({
      project_id: String(projectId), volume_id: String(volumeId),
      count: String(count), custom_prompt: customPrompt || "",
    });
    return new EventSource(`${API_BASE}/api/generation/chapters/generate-by-volume/stream?${params.toString()}`);
  },
  generateWorldStream: (projectId: number, requirements: string, style: string) => {
    const params = new URLSearchParams({
      project_id: String(projectId), requirements: requirements || "", style: style || "",
    });
    return new EventSource(`${API_BASE}/api/generation/world/generate/stream?${params.toString()}`);
  },
  generateCharactersStream: (projectId: number, protagonistCount: number, supportingCount: number, antagonistCount: number, style: string) => {
    const params = new URLSearchParams({
      project_id: String(projectId), protagonist_count: String(protagonistCount),
      supporting_count: String(supportingCount), antagonist_count: String(antagonistCount),
      style: style || "",
    });
    return new EventSource(`${API_BASE}/api/generation/characters/generate/stream?${params.toString()}`);
  },
  generateChapterBrief: (projectId: number, chapter: number, title: string) => request<ChapterBrief>("/api/generation/chapter/brief", { method: "POST", body: JSON.stringify({ project_id: projectId, chapter, title }) }),
  saveChapterBrief: (projectId: number, chapter: number, title: string, brief: any, brief_text: string, context_stats: Record<string, number>) => request<{ saved: boolean }>("/api/generation/chapter/brief/save", { method: "POST", body: JSON.stringify({ project_id: projectId, chapter, title, brief, brief_text, context_stats }) }),
  getChapterBrief: (projectId: number, chapter: number) => request<ChapterBrief>(`/api/generation/chapter/brief?project_id=${projectId}&chapter=${chapter}`),
  reviewChapter: (projectId: number, chapter: number) => request<ReviewResult>("/api/generation/chapter/review", { method: "POST", body: JSON.stringify({ project_id: projectId, chapter }) }, GEN_TIMEOUT),
  commitChapter: (projectId: number, chapter: number) => request<ChapterCommitResult>("/api/generation/chapter/commit", { method: "POST", body: JSON.stringify({ project_id: projectId, chapter }) }, GEN_TIMEOUT),
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
    }, GEN_TIMEOUT),
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

  // 交互式创作（无大纲直接生成章节）
  interactiveGenerateChapter: (projectId: number, chapterNumber: number, userDirection: string, customPrompt: string) =>
    request<{ chapter: number; title: string; content: string; word_count: number; suggested_next: string; brief: string }>(
      "/api/generation/interactive/generate-chapter",
      { method: "POST", body: JSON.stringify({ project_id: projectId, chapter_number: chapterNumber, user_direction: userDirection, custom_prompt: customPrompt }) },
      GEN_TIMEOUT,
    ),

  // 交互式聊天创作（一问一答）
  interactiveChat: (projectId: number, message: string, history: ChatHistoryMsg[], mode: "qa" | "free") =>
    request<InteractiveChatResponse>(
      "/api/generation/interactive/chat",
      { method: "POST", body: JSON.stringify({ project_id: projectId, message, history, mode }) },
      GEN_TIMEOUT,
    ),

  // 交互式聊天创作（流式 SSE）
  interactiveChatStream: async (projectId: number, message: string, history: ChatHistoryMsg[], mode: "qa" | "free", signal?: AbortSignal, useWorkflow: boolean = false, numVariants: number = 1) => {
    const res = await fetch(`${API_BASE}/api/generation/interactive/chat/stream`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ project_id: projectId, message, history, mode, use_workflow: useWorkflow, num_variants: numVariants }),
      signal,
    });
    if (!res.ok) {
      const text = await res.text().catch(() => "Unknown error");
      throw new Error(extractErrorMessage(res.status, text));
    }
    return res;
  },

  // 交互式创作：抽卡模式，用户选中第几版后继续 润色→审校→人审（SSE 流式）
  interactiveVariantResume: async (projectId: number, threadId: string, selectedIndex: number, signal?: AbortSignal) => {
    const res = await fetch(`${API_BASE}/api/generation/interactive/variant/resume`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ project_id: projectId, thread_id: threadId, selected_index: selectedIndex }),
      signal,
    });
    if (!res.ok) {
      const text = await res.text().catch(() => "Unknown error");
      throw new Error(extractErrorMessage(res.status, text));
    }
    return res;
  },

  // 交互式创作：人审决策恢复（SSE 流式）
  interactiveResume: async (projectId: number, threadId: string, decision: "approve" | "rewrite" | "polish", feedback: string = "", deepPolish: boolean = false, signal?: AbortSignal) => {
    const res = await fetch(`${API_BASE}/api/generation/interactive/chat/resume`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ project_id: projectId, thread_id: threadId, decision, feedback, deep_polish: deepPolish }),
      signal,
    });
    if (!res.ok) {
      const text = await res.text().catch(() => "Unknown error");
      throw new Error(extractErrorMessage(res.status, text));
    }
    return res;
  },

  // 批量生成（SSE 流式）：逐章推送进度
  bookRunStream: async (
    projectId: number,
    startChapter: number,
    endChapter: number,
    onChapterStart: (ch: number) => void,
    onChapterDone: (ch: number, status: string, error?: string) => void,
    onDone: (total: number, completed: number, failed: number) => void,
    onError: (error: string) => void,
    signal?: AbortSignal,
  ) => {
    const res = await fetch(`${API_BASE}/api/generation/book/run/stream`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ project_id: projectId, start_chapter: startChapter, end_chapter: endChapter }),
      signal,
    });
    if (!res.ok) {
      const text = await res.text().catch(() => "Unknown error");
      throw new Error(extractErrorMessage(res.status, text));
    }
    const reader = res.body?.getReader();
    if (!reader) return;
    const decoder = new TextDecoder();
    let buffer = "";
    let currentEvent = "";
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
          if (currentEvent === "chapter_start") {
            onChapterStart(data.chapter);
          } else if (currentEvent === "chapter_done") {
            onChapterDone(data.chapter, data.status, data.error);
          } else if (currentEvent === "done") {
            onDone(data.total, data.completed, data.failed);
          } else if (currentEvent === "error") {
            onError(data.error);
          }
        }
      }
    }
  },

  // Chapters
  listChapters: (projectId: number) => request<ChapterListItem[]>(`/api/chapters/list?project_id=${projectId}`),
  getChapterText: (projectId: number, chapter: number) => request<ChapterText>(`/api/chapters/${chapter}/text?project_id=${projectId}`),
  saveChapterText: (projectId: number, chapter: number, title: string, content: string) => request<void>(`/api/chapters/${chapter}/text?project_id=${projectId}`, { method: "PUT", body: JSON.stringify({ title, content }) }),

  // AI 味检测与去味
  checkAiStyle: (text: string, projectId?: number) => request<AiStyleReport>("/api/audit/ai-style/check", { method: "POST", body: JSON.stringify({ text, project_id: projectId }) }),
  /** 深度检测：roberta 中文模型判别 AI 概率（最准，CPU 推理较慢） */
  checkAiStyleDeep: (text: string) => request<DeepAiStyleReport>("/api/audit/ai-style/check-deep", { method: "POST", body: JSON.stringify({ text }) }),
  getAiModelStatus: () => request<AiModelStatus>("/api/audit/ai-style/model-status"),
  downloadAiModelStream: (
    onFile: (file: string, index: number, total: number) => void,
    onDone: (ok: boolean) => void,
    onError: (message: string) => void,
  ): AbortController => {
    const controller = new AbortController();
    fetch("/api/audit/ai-style/model-download", { method: "POST", signal: controller.signal })
      .then(async (res) => {
        if (!res.ok) {
          const t = await res.text().catch(() => "");
          throw new Error(extractErrorMessage(res.status, t));
        }
        const reader = res.body?.getReader();
        const decoder = new TextDecoder();
        if (!reader) return;
        let buffer = "";
        let currentEvent = "";
        while (true) {
          const { done, value } = await reader.read();
          if (done) break;
          buffer += decoder.decode(value, { stream: true });
          const lines = buffer.split("\n");
          buffer = lines.pop() || "";
          for (const line of lines) {
            if (line.startsWith("event: ")) currentEvent = line.slice(7).trim();
            else if (line.startsWith("data: ")) {
              try {
                const data = JSON.parse(line.slice(6));
                if (currentEvent === "file") onFile(data.file || "", data.index || 0, data.total || 0);
                else if (currentEvent === "done") onDone(!!data.ok);
                else if (currentEvent === "error") onError(data.message || "下载失败");
              } catch { /* ignore malformed */ }
            }
          }
        }
      })
      .catch((e: any) => {
        if (e?.name === "AbortError") return; // 用户主动中断
        onError(e?.message || "请求失败");
      });
    return controller;
  },
  checkChapterAiStyle: (projectId: number, chapter: number) => request<AiStyleReport>("/api/audit/ai-style/check-chapter", { method: "POST", body: JSON.stringify({ project_id: projectId, chapter }) }),
  repairAiStyleRule: (text: string, projectId?: number) => request<AiStyleRepairResult>("/api/audit/ai-style/repair-rule", { method: "POST", body: JSON.stringify({ text, project_id: projectId }) }),
  /** 误判白名单：列出/添加/撤销某项目标记为误判的词 */
  listAiIgnoreWords: (projectId: number) => request<{ words: Record<string, string> }>(`/api/audit/ai-style/ignore-words?project_id=${projectId}`),
  addAiIgnoreWord: (projectId: number, word: string) => request<{ added: boolean; word: string }>("/api/audit/ai-style/ignore-words", { method: "POST", body: JSON.stringify({ project_id: projectId, word }) }),
  removeAiIgnoreWord: (projectId: number, word: string) => request<{ removed: boolean; word: string }>(`/api/audit/ai-style/ignore-words/${projectId}/${encodeURIComponent(word)}`, { method: "DELETE" }),
  /** LLM 流式润色（SSE）。返回 AbortController 用于中断。 */
  repairAiStyleStream: (
    text: string,
    onChunk: (delta: string) => void,
    onRoundStart: (round: number) => void,
    onRoundDone: (after: AiStyleReport) => void,
    onDone: (result: AiStyleRepairResult) => void,
    onError: (message: string) => void,
  ): AbortController => {
    const controller = new AbortController();
    fetch("/api/audit/ai-style/repair", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ text }),
      signal: controller.signal,
    })
      .then(async (res) => {
        if (!res.ok) {
          const t = await res.text().catch(() => "");
          throw new Error(extractErrorMessage(res.status, t));
        }
        const reader = res.body?.getReader();
        const decoder = new TextDecoder();
        if (!reader) return;
        let buffer = "";
        let currentEvent = "";
        while (true) {
          const { done, value } = await reader.read();
          if (done) break;
          buffer += decoder.decode(value, { stream: true });
          const lines = buffer.split("\n");
          buffer = lines.pop() || "";
          for (const line of lines) {
            if (line.startsWith("event: ")) currentEvent = line.slice(7).trim();
            else if (line.startsWith("data: ")) {
              try {
                const data = JSON.parse(line.slice(6));
                if (currentEvent === "chunk") onChunk(data.text || "");
                else if (currentEvent === "round_start") onRoundStart(data.round || 1);
                else if (currentEvent === "round_done") onRoundDone(data.after);
                else if (currentEvent === "done") onDone(data as AiStyleRepairResult);
                else if (currentEvent === "error") onError(data.message || "润色失败");
              } catch { /* ignore malformed */ }
            }
          }
        }
      })
      .catch((e: any) => {
        if (e?.name === "AbortError") return; // 用户主动中断
        onError(e?.message || "请求失败");
      });
    return controller;
  },
  // ── 叙事线系统 ─────────────────────────────
  storylineMeta: () => request<StorylineMeta>("/api/storylines/meta"),
  listStorylines: (projectId: number, params?: { tag?: string; status?: string; volume?: string; search?: string }) => {
    const qs = new URLSearchParams();
    if (params?.tag) qs.set("tag", params.tag);
    if (params?.status) qs.set("status", params.status);
    if (params?.volume) qs.set("volume", params.volume);
    if (params?.search) qs.set("search", params.search);
    return request<{ items: Storyline[] }>(`/api/storylines/${projectId}/storylines?${qs.toString()}`);
  },
  createStoryline: (projectId: number, data: Partial<Storyline>) =>
    request<Storyline>(`/api/storylines/${projectId}/storylines`, { method: "POST", body: JSON.stringify(data) }),
  updateStoryline: (projectId: number, id: number, data: Partial<Storyline>) =>
    request<Storyline>(`/api/storylines/${projectId}/storylines/${id}`, { method: "PUT", body: JSON.stringify(data) }),
  deleteStoryline: (projectId: number, id: number) =>
    request<void>(`/api/storylines/${projectId}/storylines/${id}`, { method: "DELETE" }),
  getStorylineDetail: (projectId: number, id: number) =>
    request<StorylineDetail>(`/api/storylines/${projectId}/storylines/${id}/detail`),
  createStorylineNode: (projectId: number, lineId: number, data: Partial<StorylineNode>) =>
    request<StorylineNode>(`/api/storylines/${projectId}/storylines/${lineId}/nodes`, { method: "POST", body: JSON.stringify(data) }),
  deleteStorylineNode: (nodeId: number) =>
    request<void>(`/api/storylines/storyline-nodes/${nodeId}`, { method: "DELETE" }),
  createStorylineRelation: (projectId: number, data: Partial<StorylineRelation>) =>
    request<StorylineRelation>(`/api/storylines/${projectId}/storylines/relations`, { method: "POST", body: JSON.stringify(data) }),
  deleteStorylineRelation: (relId: number) =>
    request<void>(`/api/storylines/storyline-relations/${relId}`, { method: "DELETE" }),
  /** 双通道健康度扫描（SSE），返回 AbortController 可中断 */
  scanStorylines: (
    projectId: number,
    chapter: number | null,
    onLineResult: (d: any) => void,
    onAlerts: (d: { items: ScanAlert[] }) => void,
    onDone: () => void,
    onError: (msg: string) => void,
  ): AbortController => {
    const controller = new AbortController();
    fetch("/api/storylines/" + projectId + "/storylines/scan", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ chapter, start_chapter: 0, end_chapter: 0 }),
      signal: controller.signal,
    })
      .then(async (res) => {
        if (!res.ok) {
          const t = await res.text().catch(() => "");
          throw new Error(extractErrorMessage(res.status, t));
        }
        const reader = res.body?.getReader();
        const decoder = new TextDecoder();
        if (!reader) return;
        let buffer = "", currentEvent = "";
        while (true) {
          const { done, value } = await reader.read();
          if (done) break;
          buffer += decoder.decode(value, { stream: true });
          const lines = buffer.split("\n");
          buffer = lines.pop() || "";
          for (const line of lines) {
            if (line.startsWith("event: ")) currentEvent = line.slice(7).trim();
            else if (line.startsWith("data: ")) {
              try {
                const d = JSON.parse(line.slice(6));
                if (currentEvent === "line_result") onLineResult(d);
                else if (currentEvent === "alerts") onAlerts(d);
                else if (currentEvent === "done") onDone();
                else if (currentEvent === "error") onError(d.message || "扫描失败");
              } catch { /* ignore */ }
            }
          }
        }
      })
      .catch((e: any) => { if (e?.name !== "AbortError") onError(e?.message || "扫描失败"); });
    return controller;
  },

  deleteChapter: (projectId: number, chapter: number) => request<void>(`/api/chapters/${chapter}?project_id=${projectId}`, { method: "DELETE" }),
  exportTxt: (projectId: number) => `${API_BASE}/api/chapters/export/txt?project_id=${projectId}`,
  exportBible: (projectId: number) =>
    request<any>(`/api/bible/${projectId}/export`),
  generateStream: (projectId: number, chapter: number, title: string, threadId?: string) => {
    const params = new URLSearchParams({ project_id: String(projectId), chapter: String(chapter), title });
    if (threadId) params.append("thread_id", threadId);
    return new EventSource(`${API_BASE}/api/chapters/generate/stream?${params.toString()}`);
  },
  resumeStream: (projectId: number, threadId: string, decision: string, feedback?: string) => {
    const params = new URLSearchParams({ project_id: String(projectId), thread_id: threadId, decision });
    if (feedback && feedback.trim()) params.append("feedback", feedback.trim());
    return new EventSource(`${API_BASE}/api/chapters/resume/stream?${params.toString()}`);
  },
  cancelChapter: (projectId: number, threadId: string) =>
    request<{ cancelled: boolean }>(`/api/chapters/cancel?project_id=${projectId}&thread_id=${threadId}`, { method: "POST" }),

  // Chat
  listChatSessions: (projectId: number) => request<ChatSession[]>(`/api/chat/sessions?project_id=${projectId}`),
  getChatMessages: (projectId: number, sessionId: string) =>
    request<ChatMessageItem[]>(`/api/chat/sessions/${sessionId}/messages?project_id=${projectId}`),
  deleteChatSession: (projectId: number, sessionId: string) =>
    request<void>(`/api/chat/sessions/${sessionId}?project_id=${projectId}`, { method: "DELETE" }),
  getChatSessionStatus: (sessionId: string) =>
    request<{ session_id: string; busy: boolean; steer_pending: number; created_at: string; updated_at: string }>(
      `/api/chat/sessions/${sessionId}/status`
    ),

  // Interactive 创作聊天记录（独立 session_type='interactive'，与 AI 对话隔离）
  getInteractiveMessages: (projectId: number) =>
    request<{ id: string; role: string; content: string; created_at: string }[]>(`/api/chat/interactive/messages?project_id=${projectId}`),
  saveInteractiveMessages: (projectId: number, messages: Record<string, any>[]) =>
    request<{ saved: boolean; count: number }>("/api/chat/interactive/messages", {
      method: "POST",
      body: JSON.stringify({ project_id: projectId, messages }),
    }),

  sendChatMessage: (payload: ChatSendPayload, onChunk: (event: ChatChunkEvent) => void, onAction: (event: ChatActionEvent) => void, onReasoning?: (event: ChatChunkEvent) => void) => {
    return new Promise<void>((resolve, reject) => {
      fetch("/api/chat/messages", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          ...payload,
          object_id: String(payload.object_id),
          title: payload.title || `${payload.object_type || "global"}-${payload.object_id || "project"}`,
        }),
      })
        .then(async (res) => {
          if (!res.ok) {
            const text = await res.text().catch(() => "Unknown error");
            throw new Error(extractErrorMessage(res.status, text));
          }
          const reader = res.body?.getReader();
          const decoder = new TextDecoder();
          if (!reader) {
            resolve();
            return;
          }
          let buffer = "";
          let currentEvent = "";
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
                const data = line.slice(6);
                if (data === "{}") continue;
                try {
                  const parsed = JSON.parse(data);
                  if (currentEvent === "chunk") onChunk(parsed as ChatChunkEvent);
                  else if (currentEvent === "action") onAction(parsed as ChatActionEvent);
                  else if (currentEvent === "reasoning" && onReasoning) onReasoning(parsed as ChatChunkEvent);
                } catch {
                  // ignore malformed
                }
              }
            }
          }
          resolve();
        })
        .catch(reject);
    });
  },

  // Planning
  runPlanning: (projectId: number, volume: string, chapterCount: number, threadId?: string, customPrompt?: string, targetVolumes?: number, goldenFinger?: string, constitution?: string) => request<PlanningResult>("/api/planning/run", { method: "POST", body: JSON.stringify({ project_id: projectId, volume, chapter_count: chapterCount, thread_id: threadId || crypto.randomUUID(), custom_prompt: customPrompt || "", target_volumes: targetVolumes || 0, golden_finger: goldenFinger || "", constitution: constitution || "" }) }),
  runPlanningStream: (projectId: number, volume: string, chapterCount: number, threadId?: string, customPrompt?: string, targetVolumes?: number, goldenFinger?: string, constitution?: string, protagonist?: string) => {
    const tid = threadId || crypto.randomUUID();
    const params = new URLSearchParams({
      project_id: String(projectId),
      volume,
      chapter_count: String(chapterCount),
      thread_id: tid,
      custom_prompt: customPrompt || "",
      target_volumes: String(targetVolumes || 0),
      golden_finger: goldenFinger || "",
      constitution: constitution || "",
      protagonist: protagonist || "",
    });
    return new EventSource(`${API_BASE}/api/planning/run/stream?${params.toString()}`);
  },
  resumePlanning: (projectId: number, threadId: string, approved: boolean, edits?: string) => request<PlanningResult>("/api/planning/resume", { method: "POST", body: JSON.stringify({ project_id: projectId, thread_id: threadId, approved, edits: edits || "" }) }, GEN_TIMEOUT),
  detectPlanningIssues: (projectId: number, result: PlanningResult) => request<{ issues: PlanningIssue[] }>("/api/planning/detect", { method: "POST", body: JSON.stringify({ project_id: projectId, result }) }),

  // Config
  getLLMConfig: () => request<LLMConfig>("/api/config/llm"),
  updateLLMConfig: (data: Partial<LLMConfig>) => request<{ saved: boolean; context_length?: number }>("/api/config/llm", { method: "PUT", body: JSON.stringify(data) }),
  testLLMConfig: () => request<{ ok: boolean; response: string; context_length?: number }>("/api/config/llm/test", { method: "POST", body: JSON.stringify({}) }),

  // Embedding config
  getEmbeddingConfig: () => request<EmbeddingConfig>("/api/config/embedding"),
  updateEmbeddingConfig: (data: Partial<EmbeddingConfig>) => request<{ saved: boolean }>("/api/config/embedding", { method: "PUT", body: JSON.stringify(data) }),
  testEmbeddingConfig: () => request<{ ok: boolean; dimensions?: number }>("/api/config/embedding/test", { method: "POST", body: JSON.stringify({}) }),

  // Per-agent LLM config
  listAgentLLMConfigs: () => request<Record<string, AgentLLMConfig>>("/api/config/agent-llm"),
  updateAgentLLMConfig: (role: string, data: Partial<LLMConfig>) => request<{ saved: boolean; context_length?: number }>(`/api/config/agent-llm/${role}`, { method: "PUT", body: JSON.stringify(data) }),
  resetAgentLLMConfig: (role: string) => request<{ saved: boolean; message: string }>(`/api/config/agent-llm/${role}`, { method: "DELETE" }),

  // Reference files
  listReferences: (projectId: number) => request<{ filename: string; size: number; content_preview: string }[]>(`/api/bible/${projectId}/references`),
  uploadReference: (projectId: number, file: File) => {
    const formData = new FormData();
    formData.append("file", file);
    return request<{ filename: string; original_name: string; size: number; char_count: number; content_preview: string }>(`/api/bible/${projectId}/references`, { method: "POST", body: formData });
  },
  getReference: (projectId: number, filename: string) => request<{ filename: string; content: string; size: number }>(`/api/bible/${projectId}/references/${encodeURIComponent(filename)}`),
  deleteReference: (projectId: number, filename: string) => request<{ deleted: boolean }>(`/api/bible/${projectId}/references/${encodeURIComponent(filename)}`, { method: "DELETE" }),

  // Bible: red lines（红线/创作禁忌）
  listRedLines: (projectId: number) => request<RedLine[]>(`/api/bible/${projectId}/red-lines`),
  createRedLine: (projectId: number, data: Partial<RedLine>) => request<RedLine>(`/api/bible/${projectId}/red-lines`, { method: "POST", body: JSON.stringify(data) }),
  updateRedLine: (projectId: number, id: number, data: Partial<RedLine>) => request<RedLine>(`/api/bible/${projectId}/red-lines/${id}`, { method: "PUT", body: JSON.stringify(data) }),
  deleteRedLine: (projectId: number, id: number) => request<void>(`/api/bible/${projectId}/red-lines/${id}`, { method: "DELETE" }),

  // Bible: gags（梗：笑点/桥段/彩蛋）
  listGags: (projectId: number) => request<Gag[]>(`/api/bible/${projectId}/gags`),
  createGag: (projectId: number, data: Partial<Gag>) => request<Gag>(`/api/bible/${projectId}/gags`, { method: "POST", body: JSON.stringify(data) }),
  updateGag: (projectId: number, id: number, data: Partial<Gag>) => request<Gag>(`/api/bible/${projectId}/gags/${id}`, { method: "PUT", body: JSON.stringify(data) }),
  deleteGag: (projectId: number, id: number) => request<void>(`/api/bible/${projectId}/gags/${id}`, { method: "DELETE" }),

  // Reference: folder import（文件夹批量导入章节）
  importFolder: (projectId: number, folderPath: string) =>
    request<{ imported_count: number; imported: ImportedChapter[]; failed_count: number; failed: { filename: string; error: string }[] }>(`/api/references/import-folder`, {
      method: "POST",
      body: JSON.stringify({ project_id: projectId, folder_path: folderPath }),
    }),
  listImportedChapters: (projectId: number) =>
    request<ImportedChapter[]>(`/api/references/imported-chapters/${projectId}`),
  deleteImportedChapter: (id: number) =>
    request<{ deleted: boolean }>(`/api/references/imported-chapters/${id}`, { method: "DELETE" }),
  getImportedChapter: (projectId: number, chapterNum: number) =>
    request<ImportedChapterDetail>(`/api/references/imported-chapters/${projectId}/chapter/${chapterNum}`),
};
