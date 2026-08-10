/** 聊天子系统：写作页侧边聊天面板组件。
 *
 * 组件层级：
 *   ChatPanel（外壳：展开/收起 + 会话切换）
 *     ├── ChatMessage（单条消息：头像 + 内容 + 动作徽章）
 *     │     └── ChatActionBadge（动作状态徽章：重写/反馈/生成等）
 *     └── ChatInput（输入框 + 发送按钮）
 *
 * 依赖：
 *   - useChat hook（@/hooks/useChat）：SSE 流式对话逻辑
 *   - chat types（@/types/chat）：消息/动作/会话类型
 */
export { ChatPanel } from "./chat-panel";
export { ChatMessage } from "./chat-message";
export { ChatInput } from "./chat-input";
export { ChatActionBadge } from "./chat-action-badge";
