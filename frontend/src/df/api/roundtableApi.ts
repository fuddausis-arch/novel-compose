/**
 * 圆桌讨论后端 API 封装。
 *
 * 对接后端 novel_agent/roundtable/routes.py（前缀 /api/roundtable）。
 * - REST 调用：create/list/get/start/stop/pause/resume/inject/delete/transcript
 * - SSE 流：组件内直接 new EventSource(`/api/roundtable/${id}/stream`)，
 *   用 addEventListener 监听具体事件类型（rt_token/rt_turn_start/...）
 *
 * 后端事件结构见 novel_agent/roundtable/runner.py 的 emit_event 调用。
 */

// ============ 类型定义 ============

export type RoundtableStrategy = "round_robin" | "moderator_decides";

export type RoundtableStatus = "waiting" | "discussing" | "paused" | "ended";

/** 创建会话时的席位输入（对齐后端 SeatConfig） */
export interface RoundtableSeatInput {
  role_name: string;
  system_prompt: string;
  temperature: number;
  model_name?: string | null;
  is_moderator?: boolean;
}

/** 会话详情中的席位信息（对齐后端 Seat.to_dict） */
export interface RoundtableSeatInfo {
  seat_id: string;
  role_name: string;
  system_prompt: string;
  temperature: number;
  model_name: string | null;
  allowed_tools: string[] | null;
  is_moderator: boolean;
  status: "idle" | "speaking" | "thinking" | "done";
}

/** 单条讨论记录（对齐后端 TranscriptEntry.to_dict） */
export interface TranscriptEntry {
  speaker_seat_id: string;
  speaker_name: string;
  content: string;
  round_number: number;
  timestamp: string;
  entry_type: "statement" | "moderator_note" | "summary" | "conclusion";
}

/** 会话摘要（对齐后端 get_summary） */
export interface RoundtableSummary {
  session_id: string;
  topic: string;
  status: RoundtableStatus;
  seat_count: number;
  current_round: number;
  max_rounds: number;
  current_speaker: string | null;
  transcript_count: number;
  created_at: string;
  ended_at: string | null;
  strategy: RoundtableStrategy;
}

/** 会话详情（对齐后端 to_dict + 附加字段） */
export interface RoundtableDetail extends RoundtableSummary {
  seats: RoundtableSeatInfo[];
  transcript: TranscriptEntry[];
  active_turn: {
    seat_id: string;
    speaker_name: string;
    content: string;
    round: number;
  } | null;
  shared_memory: {
    conclusions: Array<{ content: string; source: string; timestamp: string }>;
    consensus: string[];
    controversies: string[];
    summaries: Array<{ round: number; content: string; timestamp: string }>;
    structured_conclusion?: Record<string, unknown> | null;
  };
  compressor: { enabled: boolean; window_size: number; summary_interval: number };
}

/** SSE 事件联合类型（对齐后端 runner.py 的 emit_event 调用） */
export type RoundtableEvent =
  | { type: "rt_started"; roundtable_id: string; topic: string; seats: RoundtableSeatInfo[]; max_rounds: number; strategy: string }
  | { type: "rt_turn_start"; roundtable_id: string; seat_id: string; speaker_name: string; round: number; is_moderator_thinking?: boolean }
  | { type: "rt_token"; roundtable_id: string; seat_id: string; content: string }
  | { type: "rt_turn_end"; roundtable_id: string; seat_id: string; speaker_name: string; round: number; full_content: string; interrupted?: boolean }
  | { type: "rt_round_end"; roundtable_id: string; round: number }
  | { type: "rt_ended"; roundtable_id: string; total_rounds: number; transcript_count: number }
  | { type: "rt_paused"; roundtable_id: string; round: number }
  | { type: "rt_resumed"; roundtable_id: string; round: number }
  | { type: "rt_seat_added"; roundtable_id: string; seat: RoundtableSeatInfo }
  | { type: "rt_seat_removed"; roundtable_id: string; seat_id: string; role_name: string }
  | { type: "rt_deleted"; roundtable_id: string }
  | { type: "speaker_selected"; roundtable_id: string; seat_id: string; speaker_name: string; round: number; reason: string }
  | { type: "moderator_decision"; roundtable_id: string; decision: Record<string, unknown> }
  | { type: "roundtable_summary"; roundtable_id: string; round: number; content: string; source: string }
  | { type: "roundtable_conclusion"; roundtable_id: string; content: string; source: string; total_rounds: number; structured?: Record<string, unknown> | null }
  | { type: "ping" };

/** 终止信号：以下事件类型出现后，后端会关闭 SSE 流，前端也应清理连接 */
export const TERMINAL_EVENT_TYPES = new Set(["rt_ended", "rt_deleted"]);

// ============ REST 调用 ============

const API_BASE = "";

function extractError(status: number, text: string): string {
  if (!text) return `请求失败（HTTP ${status}）`;
  try {
    const parsed = JSON.parse(text);
    if (parsed.detail) return String(parsed.detail);
    if (parsed.message) return String(parsed.message);
  } catch {
    // 非 JSON
  }
  return text;
}

async function request<T>(path: string, options: RequestInit = {}): Promise<T> {
  const res = await fetch(`${API_BASE}${path}`, {
    headers: { "Content-Type": "application/json" },
    ...options,
  });
  if (!res.ok) {
    const text = await res.text().catch(() => "Unknown error");
    throw new Error(extractError(res.status, text));
  }
  if (res.status === 204) return undefined as T;
  return res.json();
}

export interface CreateRoundtablePayload {
  topic: string;
  seats: RoundtableSeatInput[];
  max_rounds: number;
  strategy: RoundtableStrategy;
  compressor?: { enabled: boolean; window_size: number; summary_interval: number } | null;
}

export const roundtableApi = {
  create: (data: CreateRoundtablePayload) =>
    request<{ success: boolean; session: RoundtableSummary }>("/api/roundtable", {
      method: "POST",
      body: JSON.stringify(data),
    }),

  list: () =>
    request<{ roundtables: RoundtableSummary[]; total: number }>("/api/roundtable"),

  get: (sessionId: string) =>
    request<RoundtableDetail>(`/api/roundtable/${sessionId}`),

  start: (sessionId: string) =>
    request<{ success: boolean; message: string }>(`/api/roundtable/${sessionId}/start`, { method: "POST" }),

  stop: (sessionId: string) =>
    request<{ success: boolean; message: string }>(`/api/roundtable/${sessionId}/stop`, { method: "POST" }),

  pause: (sessionId: string) =>
    request<{ success: boolean; message: string }>(`/api/roundtable/${sessionId}/pause`, { method: "POST" }),

  resume: (sessionId: string) =>
    request<{ success: boolean; message: string }>(`/api/roundtable/${sessionId}/resume`, { method: "POST" }),

  inject: (sessionId: string, content: string) =>
    request<{ success: boolean; message: string }>(`/api/roundtable/${sessionId}/inject`, {
      method: "POST",
      body: JSON.stringify({ content }),
    }),

  delete: (sessionId: string) =>
    request<{ success: boolean; message: string }>(`/api/roundtable/${sessionId}`, { method: "DELETE" }),

  transcript: (sessionId: string) =>
    request<{ transcript: TranscriptEntry[]; total: number; current_round: number }>(
      `/api/roundtable/${sessionId}/transcript`,
    ),
};

// ============ SSE 流封装 ============

/**
 * 建立 SSE 连接，返回 EventSource 与一个清理函数。
 *
 * 调用方通过 onEvent 接收所有已解析的事件（rt_token/rt_turn_start/...）。
 * 收到 rt_ended 或 rt_deleted 后会自动 close 连接。
 *
 * 注意：建立 SSE 必须在 POST /start 之前完成，否则会丢失 rt_started 等首批事件。
 */
export function openRoundtableStream(
  sessionId: string,
  onEvent: (event: RoundtableEvent) => void,
  onError?: (err: Event) => void,
): EventSource {
  const es = new EventSource(`/api/roundtable/${sessionId}/stream`);

  // 监听所有事件类型，解析后统一交给 onEvent
  const EVENT_TYPES = [
    "rt_started",
    "rt_turn_start",
    "rt_token",
    "rt_turn_end",
    "rt_round_end",
    "rt_ended",
    "rt_paused",
    "rt_resumed",
    "rt_seat_added",
    "rt_seat_removed",
    "rt_deleted",
    "speaker_selected",
    "moderator_decision",
    "roundtable_summary",
    "roundtable_conclusion",
    "ping",
  ];

  for (const etype of EVENT_TYPES) {
    es.addEventListener(etype, (raw: MessageEvent) => {
      try {
        const data = raw.data ? JSON.parse(raw.data) : { type: etype };
        onEvent({ ...data, type: etype } as RoundtableEvent);
      } catch {
        // 非 JSON（如 ping 的 "{}" 解析失败时兜底）
        onEvent({ type: etype } as RoundtableEvent);
      }
      if (TERMINAL_EVENT_TYPES.has(etype)) {
        es.close();
      }
    });
  }

  if (onError) {
    es.onerror = (err) => {
      // EventSource 会自动重连；若会话已结束则后端返回 404，这里直接关闭
      if (es.readyState === EventSource.CLOSED) return;
      onError(err);
    };
  }

  return es;
}
