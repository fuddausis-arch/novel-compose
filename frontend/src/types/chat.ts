export type ChatSessionType = "object" | "global";
export type ChatObjectType = "chapter" | "outline" | "character" | "monster" | "world" | "faction" | "relationship";
export type ChatRole = "user" | "assistant" | "system";

export interface ChatAction {
  type: string;
  [key: string]: unknown;
}

export interface ChatMessageItem {
  id: string;
  session_id: string;
  role: ChatRole;
  content: string;
  actions: ChatAction[];
  created_at: string;
}

export interface ChatSession {
  id: string;
  project_id: number;
  session_type: ChatSessionType;
  object_type: ChatObjectType | "";
  object_id: string;
  title: string;
  created_at: string;
  updated_at: string;
}

export interface ChatSendPayload {
  project_id: number;
  message: string;
  session_type: ChatSessionType;
  object_type: ChatObjectType | "";
  object_id: string | number;
  title?: string;
}

export interface ChatChunkEvent {
  content: string;
}

export interface ChatActionEvent extends ChatAction {
  status?: "dispatched" | "done" | "failed";
  result?: unknown;
  error?: string;
}
