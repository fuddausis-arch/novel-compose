/**
 * DeterminFlow 融合对话页 API 层
 *
 * 对接本项目后端（与 DeterminFlow 后端不同，勿照搬其调用层）：
 * - 聊天：/api/chat/*（SSE 流式，POST /messages）
 * - 预设短语：/api/preset-phrases/*
 * - 模型：/api/config/llm（对话实际使用全局 LLM 配置）+ /api/models/*
 * - 提示词预览：/api/prompts/{agent_type}/preview
 * - 工作空间：/api/workspace/*
 */

// ---------- 类型定义 ----------

export interface DFChatSession {
  id: string;
  project_id: number;
  session_type: string; // "object" | "global" | "interactive"
  object_type: string; // chapter|outline|character|...|"chat"|""
  object_id: string;
  title: string;
  created_at: string | null;
  updated_at: string | null;
}

export interface DFChatAction {
  type: string;
  status?: string;
  result?: unknown;
  error?: string;
  [key: string]: unknown;
}

export interface DFChatMessage {
  id: string;
  session_id: string;
  role: "user" | "assistant" | "system";
  content: string;
  actions: DFChatAction[];
  created_at: string;
}

/** 发送消息所需的会话定位四元组（后端按此 get_or_create 会话） */
export interface ChatTarget {
  session_type: string;
  object_type: string;
  object_id: string;
  title: string;
}

export interface PresetPhrase {
  id: string;
  category: string;
  text: string;
  shortcut: string;
}

export interface ModelProvider {
  name: string;
  base_url: string;
  api_key: string; // 脱敏后的 key
  priority: number;
  is_default: boolean;
}

export interface DiscoveredModel {
  id: string;
  context_length: number;
  owned_by: string;
}

export interface LLMConfigInfo {
  base_url: string;
  api_key: string;
  model: string;
  temperature: number;
  max_tokens: number;
  timeout: number;
  vision_enabled: boolean;
  context_length?: number;
  top_p: number;
  frequency_penalty: number;
  presence_penalty: number;
}

export interface PromptPreview {
  agent_type: string;
  prompt: string;
  estimated_tokens: number;
  section_count: number;
  enabled_count: number;
}

export interface WorkspaceEntry {
  name: string;
  type: "dir" | "file";
  size: number;
  ext?: string;
}

// ---------- 基础请求封装（与 src/api.ts 同风格的错误提取） ----------

function extractErrorMessage(status: number, text: string): string {
  if (!text) return `请求失败（HTTP ${status}）`;
  try {
    const parsed = JSON.parse(text);
    if (parsed.detail) return String(parsed.detail);
    if (parsed.message) return String(parsed.message);
  } catch {
    // 非 JSON 响应，返回原文
  }
  return text;
}

async function request<T>(path: string, options: RequestInit = {}): Promise<T> {
  const isFormData = options.body instanceof FormData;
  const res = await fetch(path, {
    headers: isFormData ? undefined : { "Content-Type": "application/json" },
    ...options,
  });
  if (!res.ok) {
    const text = await res.text().catch(() => "Unknown error");
    throw new Error(extractErrorMessage(res.status, text));
  }
  return res.json();
}

// ---------- 聊天会话 ----------

export function listChatSessions(projectId: number) {
  return request<DFChatSession[]>(`/api/chat/sessions?project_id=${projectId}`);
}

export function getChatMessages(projectId: number, sessionId: string) {
  return request<DFChatMessage[]>(
    `/api/chat/sessions/${sessionId}/messages?project_id=${projectId}`
  );
}

export function deleteChatSession(projectId: number, sessionId: string) {
  return request<{ deleted: boolean }>(
    `/api/chat/sessions/${sessionId}?project_id=${projectId}`,
    { method: "DELETE" }
  );
}

export function getChatSessionStatus(sessionId: string) {
  return request<{ session_id: string; busy: boolean; steer_pending: number }>(
    `/api/chat/sessions/${sessionId}/status`
  );
}

export interface ChatStreamHandlers {
  onChunk: (content: string) => void;
  onReasoning: (content: string) => void;
  onAction: (action: DFChatAction) => void;
  /** 会话正忙，消息已注入进行中的回合（后端 steer 语义） */
  onSteered: () => void;
}

/**
 * 发送聊天消息（SSE 流式）。
 * 注意：后端在会话 busy 时返回普通 JSON {steered:true}，而非 SSE 流。
 * 必须传 AbortSignal 以支持前端中断（断开后后端会保存已生成内容）。
 */
export async function sendChatMessageStream(
  projectId: number,
  target: ChatTarget,
  message: string,
  handlers: ChatStreamHandlers,
  signal: AbortSignal
): Promise<void> {
  const res = await fetch("/api/chat/messages", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      project_id: projectId,
      message,
      session_type: target.session_type,
      object_type: target.object_type,
      object_id: target.object_id,
      title: target.title,
    }),
    signal,
  });
  if (!res.ok) {
    const text = await res.text().catch(() => "Unknown error");
    throw new Error(extractErrorMessage(res.status, text));
  }
  // busy 分支：后端返回 JSON 而非 SSE
  const contentType = res.headers.get("content-type") || "";
  if (contentType.includes("application/json")) {
    const data = (await res.json().catch(() => ({}))) as { steered?: boolean };
    if (data.steered) handlers.onSteered();
    return;
  }
  const reader = res.body?.getReader();
  if (!reader) return;
  const decoder = new TextDecoder();
  let buffer = "";
  let currentEvent = "";
  let streamError: string | null = null;
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
        if (dataStr === "{}") continue;
        let parsed: { content?: string; error?: string } & DFChatAction;
        try {
          parsed = JSON.parse(dataStr);
        } catch {
          continue; // 忽略无法解析的行
        }
        if (currentEvent === "chunk") handlers.onChunk(parsed.content || "");
        else if (currentEvent === "reasoning") handlers.onReasoning(parsed.content || "");
        else if (currentEvent === "action") handlers.onAction(parsed);
        else if (currentEvent === "error") streamError = parsed.error || "对话流中断";
      }
    }
  }
  if (streamError) throw new Error(streamError);
}

// ---------- 预设短语 ----------

export async function listPresetPhrases(): Promise<PresetPhrase[]> {
  const data = await request<{ phrases: PresetPhrase[] }>("/api/preset-phrases");
  return data.phrases || [];
}

export async function createPresetPhrase(input: Omit<PresetPhrase, "id">) {
  const data = await request<{ phrase: PresetPhrase }>("/api/preset-phrases", {
    method: "POST",
    body: JSON.stringify(input),
  });
  return data.phrase;
}

export async function updatePresetPhrase(id: string, input: Partial<Omit<PresetPhrase, "id">>) {
  const data = await request<{ phrase: PresetPhrase }>(`/api/preset-phrases/${id}`, {
    method: "PUT",
    body: JSON.stringify(input),
  });
  return data.phrase;
}

export function deletePresetPhrase(id: string) {
  return request<{ deleted: boolean }>(`/api/preset-phrases/${id}`, { method: "DELETE" });
}

// ---------- 模型配置 ----------

export function getLLMConfig() {
  return request<LLMConfigInfo>("/api/config/llm");
}

export function updateLLMConfig(data: { model: string; base_url?: string }) {
  return request<{ saved: boolean; context_length?: number }>("/api/config/llm", {
    method: "PUT",
    body: JSON.stringify(data),
  });
}

export async function listModelProviders(): Promise<ModelProvider[]> {
  const data = await request<{ providers: ModelProvider[] }>("/api/models/providers");
  return data.providers || [];
}

export async function discoverModels(provider: string): Promise<DiscoveredModel[]> {
  const data = await request<{ models: DiscoveredModel[] }>(
    `/api/models/discover?provider=${encodeURIComponent(provider)}`
  );
  return data.models || [];
}

export async function getModelPresets(): Promise<Record<string, { base_url: string; context_length: number }>> {
  const data = await request<{ presets: Record<string, { base_url: string; context_length: number }> }>(
    "/api/models/presets"
  );
  return data.presets || {};
}

// ---------- 提示词预览 ----------

export function getPromptPreview(agentType: string) {
  return request<PromptPreview>(`/api/prompts/${encodeURIComponent(agentType)}/preview`);
}

// ---------- 工作空间 ----------

export async function listWorkspaceFiles(projectId: number, subpath: string) {
  const params = new URLSearchParams({ project_id: String(projectId), subpath });
  const data = await request<{ files: WorkspaceEntry[]; path: string }>(
    `/api/workspace/files?${params.toString()}`
  );
  return data.files || [];
}

export function readWorkspaceFile(projectId: number, path: string) {
  const params = new URLSearchParams({ project_id: String(projectId) });
  return request<{ filename: string; path: string; content: string; size: number }>(
    `/api/workspace/files/${encodeURIComponent(path)}?${params.toString()}`
  );
}

export function uploadChatAttachment(projectId: number, sessionId: string, file: File) {
  const formData = new FormData();
  formData.append("file", file);
  const params = new URLSearchParams({ project_id: String(projectId), session_id: sessionId });
  return request<{ status: string; filename: string; size: number }>(
    `/api/workspace/attachments?${params.toString()}`,
    { method: "POST", body: formData }
  );
}

// ---------- 本地工具函数 ----------

/**
 * 本地 token 粗估（后端无 token 统计端点）：
 * CJK 字符按 1 token 计，其余按 4 字符/token 计。
 */
export function estimateTokens(text: string): number {
  if (!text) return 0;
  let cjk = 0;
  let other = 0;
  for (const ch of text) {
    if (/[㐀-鿿豈-﫿　-〿＀-￯]/.test(ch)) cjk += 1;
    else other += 1;
  }
  return Math.ceil(cjk + other / 4);
}

export function formatTokens(n: number): string {
  if (n >= 1_000_000) return `${(n / 1_000_000).toFixed(1)}M`;
  if (n >= 1_000) return `${(n / 1_000).toFixed(1)}K`;
  return String(n);
}

/** 相对时间（会话列表用） */
export function formatRelativeTime(iso: string | null): string {
  if (!iso) return "";
  const time = new Date(iso).getTime();
  if (Number.isNaN(time)) return "";
  const diff = Date.now() - time;
  const minute = 60_000;
  const hour = 60 * minute;
  const day = 24 * hour;
  if (diff < minute) return "刚刚";
  if (diff < hour) return `${Math.floor(diff / minute)} 分钟前`;
  if (diff < day) return `${Math.floor(diff / hour)} 小时前`;
  if (diff < 7 * day) return `${Math.floor(diff / day)} 天前`;
  return new Date(time).toLocaleDateString("zh-CN");
}
