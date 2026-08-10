export type AssetType = "character" | "foreshadow" | "outline" | "chapter" | "faction" | "factionRelationship" | "characterRelationship" | "monster" | "instance";
export type Tab = "dashboard" | "planning" | "world" | "characters" | "outlines-volume" | "outlines-arc" | "outlines-chapter" | "asset" | "chapter" | "summaries" | "import" | "export" | "factions" | "relationships" | "monsters" | "settings";

export interface Project {
  id: number;
  title: string;
  genre: string;
  summary: string;
  style: string;
  constitution?: string;
  target_audience?: string;
  central_concept?: string;
  word_count_target?: number;
  target_volumes?: number;
  golden_finger?: string;
  protagonist?: string;
  created_at: string;
  updated_at: string;
}

export interface GoldenFinger {
  name: string;
  type: string;
  core_ability: string;
  limitation: string;
  growth: string;
  origin: string;
}

export interface GenreTemplate {
  key: string;
  title: string;
  description: string;
}

export interface WorldSetting {
  id: number;
  project_id: number;
  category: string;
  title: string;
  content: string;
  order: number;
}

export interface Character {
  id: number;
  project_id: number;
  name: string;
  role: string;
  importance?: string;
  age: string;
  gender: string;
  appearance: string;
  personality: string;
  motivation: string;
  current_location: string;
  current_emotion: string;
  known_info: string;
  background: string;
  arc: string;
  relationships: string;
  secrets: string;
  core_contradiction?: string;
  sensory_memories?: string;
  absolute_taboos?: string;
  language_style?: string;
  combat_style?: string;
  growth_curve?: string;
  emotional_anchor?: string;
}

export interface Instance {
  id: number;
  project_id: number;
  name: string;
  instance_type: string;
  related_volume: number;
  chapter_range: string;
  objective: string;
  mechanism: string;
  tone: string;
  difficulty: string;
  rewards: string;
  cost: string;
  description: string;
  order: number;
}

export interface Foreshadow {
  id: number;
  project_id: number;
  foreshadow_id: string;
  tier: string;
  description: string;
  plant_chapter: number;
  planned_resolve_chapter: number;
  status: string;
  depends_on: string;
}

export interface Faction {
  id: number;
  project_id: number;
  name: string;
  alias: string;
  type: string;
  tier?: string;
  alignment: string;
  description: string;
  history: string;
  goals: string;
  hierarchy: string;
  territories: string;
  resources: string;
  created_at: string;
  updated_at: string;
}

export interface FactionRelationship {
  id: number;
  project_id: number;
  source_faction_id: number;
  target_faction_id: number;
  relation_type: string;
  strength: number;
  description: string;
  since_chapter: number;
  status: string;
}

export interface CharacterRelationship {
  id: number;
  project_id: number;
  source_character: string;
  target_character: string;
  relation_type: string;
  relation_subtype: string;
  strength: number;
  description: string;
  since_chapter: number;
  status: string;
  is_bidirectional: boolean;
}

export interface Monster {
  id: number;
  project_id: number;
  name: string;
  alias: string;
  species: string;
  rank: string;
  tier?: string;
  attributes: string;
  skills: string;
  drops: string;
  habitats: string;
  behavior: string;
  weaknesses: string;
  lore: string;
  first_appearance: number;
  created_at: string;
  updated_at: string;
}

export type EntityType = "character" | "faction" | "monster";
export type AppearanceRole = "lead" | "participant" | "mention" | "background";

export interface EntityAppearance {
  id: number;
  project_id: number;
  entity_type: EntityType;
  entity_id: string;
  chapter: number;
  role_in_chapter: AppearanceRole;
  context_snippet: string;
  created_at: string;
  updated_at: string;
}

export interface Outline {
  id: number;
  project_id: number;
  parent_id: number | null;
  order: number;
  title: string;
  summary: string;
  level: "volume" | "arc" | "chapter";
  act: string;
  strand: "quest" | "fire" | "constellation" | "";
  required_beats: string;
  owed_debts: string;
  required_hooks: string;
  character_constraints: string;
  phase: "opening" | "shangjia" | "regular";
  planned_chapters?: number;
}

export interface StateChange {
  id: number;
  project_id: number;
  chapter: number;
  entity_type: string;
  entity_id: string;
  field: string;
  old_value: string;
  new_value: string;
  created_at: string;
}

export interface TruthEvent {
  id: number;
  project_id: number;
  chapter: number;
  event_type: string;
  entity_id: string;
  payload: Record<string, unknown>;
  timestamp: string;
}

export interface RelationshipChange {
  id: number;
  project_id: number;
  chapter: number;
  entity_type: string;
  source_id: string;
  target_id: string;
  field: string;
  old_value: string;
  new_value: string;
  reason: string;
  created_at: string;
}

export interface ChapterCommit {
  id: number;
  project_id: number;
  chapter: number;
  status: "draft" | "committed";
  summary: string;
  word_count: number;
  committed_at: string | null;
}

export type PlotDebtStatus = "open" | "resolved" | "abandoned";

export interface PlotDebt {
  id: number;
  debt_type: string;
  description: string;
  pressure: number;
  term: string;
  status: PlotDebtStatus;
  created_chapter: number;
  resolved_chapter: number;
}

export interface ReviewIssue {
  severity: "critical" | "high" | "medium" | "low";
  category: "setting" | "timeline" | "continuity" | "character" | "logic";
  location: string;
  description: string;
  evidence: string;
  fix_hint: string;
  blocking: boolean;
}

export interface ChapterBrief {
  chapter: number;
  title: string;
  brief: {
    opening: string;
    story: string;
    characters: string;
    craft: string;
    ending: string;
  };
  brief_text: string;
  context_stats: Record<string, number>;
}

export interface ReviewResult {
  chapter: number;
  issues: ReviewIssue[];
  issues_count: number;
  blocking_count: number;
  has_blocking: boolean;
  dimension_results: { dimension: string; conclusion: string }[];
  summary: string;
}

export interface ChapterCommitResult {
  chapter: number;
  committed: boolean;
  summary: string;
  deltas: number;
  relationships: number;
  events: number;
  foreshadow_updates: number;
  new_characters: number;
  new_factions: number;
  new_monsters: number;
  new_world_settings: number;
  archived: boolean;
  validation_issues?: { severity: string; message: string }[];
}

export interface LLMConfig {
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

export interface AgentLLMConfig {
  enabled: boolean;
  base_url: string;
  api_key: string;
  model: string;
  temperature: number;
  max_tokens: number;
  timeout: number;
  context_length?: number;
}

export interface EmbeddingConfig {
  api_key: string;
  base_url: string;
  model: string;
}

export interface ChapterListItem {
  chapter: number;
  title: string;
  text_preview: string;
}

export interface ChapterText {
  chapter: number;
  text: string;
}

// ── AI 味检测与去味（audit/ai-style）─────────────────────────

export interface AiStyleHit {
  level?: string;
  pattern?: string;
  word?: string;
  count?: number;
  sentence?: string;
  matched?: string;
  paragraph?: string;
  snippet?: string;
  issue: string;
  fix: string;
}

export interface AiStyleReport {
  overall_score: number;      // 综合分 0-100（越高越自然）
  rule_score: number;         // 规则层分
  stat_score: number;         // 统计层分
  ai_rate: number;            // AI 率 %
  pass_line: number;          // 达标线（AI 率上限 %）
  passed: boolean;            // AI 率 ≤ 达标线
  verdict_hint: string;       // 给作者的判定提示（含人工判断建议）
  dimensions: Record<string, number>;  // 7 个统计信号 0-100
  ai_level: string;           // 自然 / 轻度AI味 / 明显AI味
  word_hits: AiStyleHit[];
  sentence_hits: AiStyleHit[];
  paragraph_hits: AiStyleHit[];
  stat_hits: AiStyleHit[];
  total_hits: number;
  suggestions: string[];
  chars: number;
  summary: string;
}

export interface AiStyleRepairResult {
  repaired_text: string;
  before: AiStyleReport;
  after: AiStyleReport;
  score_delta: number;
  passed: boolean;
  rounds?: number;
  method?: "rule" | "llm";
}

/** 深度检测报告（roberta 中文模型） */
export interface DeepAiStyleReport {
  available: boolean;
  ai_probability: number | null;   // 0-1，越高越像 AI
  verdict: string;                 // AI / Mixed / Human / unavailable
  ai_level: string;                // 明显AI味 / 疑似AI味 / 自然 / 模型未就绪
  segments: { text: string; ai_probability: number; chars: number }[];
  summary: string;
  model: string;
  error: string | null;
}

/** 深度检测模型就绪状态 */
export interface AiModelStatus {
  ready: boolean;                  // 深度模型是否可用
  source: string | null;           // finetuned（微调版）/ zhv3（原版）/ null
  dirs: { name: string; ready: boolean }[];
}

export interface PipelineNodeEvent {
  node: string;
  output: Record<string, unknown>;
}

// ── 叙事线系统 ─────────────────────────────
export interface Storyline {
  id: number;
  project_id: number;
  name: string;
  line_type: string;
  tags: string[];
  status: string;
  progress: number;
  summary: string;
  notes: string;
  planned_resolve_chapter: number;
  volume: string;
  last_active_chapter: number;
  node_count: number;
  relation_count: number;
}

export interface StorylineNode {
  id: number;
  storyline_id: number;
  node_type: string;
  foreshadow_id: string;
  chapter: number;
  title: string;
  description: string;
  order_index: number;
}

export interface StorylineRelation {
  id: number;
  project_id: number;
  source_storyline_id: number;
  target_storyline_id: number;
  relation_type: string;
  chapter: number;
  description: string;
}

export interface StorylineDetail {
  line: Storyline;
  nodes: StorylineNode[];
  relations: StorylineRelation[];
}

export interface StorylineMeta {
  tags: string[];
  statuses: string[];
  relation_types: string[];
  node_types: string[];
}

export interface ScanAlert {
  type: string;
  severity: string;
  storyline_id?: number;
  foreshadow_id?: string;
  chapter?: number;
  message: string;
}

export interface Summary {
  chapter: number;
  title: string;
  core_events: string;
  word_count: number;
}

export interface GenreReference {
  关键词: string;
  核心摘要: string;
  详细展开: string;
}

export interface GenreContext {
  genre: string;
  canonical_genre: string;
  template_text: string;
  references: GenreReference[];
}

export interface CentralConcept {
  core_hook?: string;
  protagonist_goal?: string;
  taboos?: string[];
}

export interface PlannedVolume {
  name: string;
  theme?: string;
  chapters: number;
  summary?: string;
  climax?: string;
  end_hook?: string;
  strand_ratio?: { quest?: number; fire?: number; constellation?: number };
}

export interface VolumePlan {
  central_concept?: CentralConcept;
  volumes?: PlannedVolume[];
}

export interface PlannedCharacter {
  name: string;
  role: string;
  personality: string;
  motivation?: string;
}

export interface PlannedWorldSetting {
  category: string;
  title: string;
  content: string;
}

export interface PlannedSettings {
  characters: PlannedCharacter[];
  world_settings: PlannedWorldSetting[];
}

export interface PlannedChapter {
  chapter: number;
  title: string;
  summary: string;
  foreshadows?: PlannedForeshadow[];
}

export interface PlannedForeshadow {
  id: string;
  description: string;
  plant_chapter: number;
  resolve_chapter: number;
}

export interface PlannedOutline {
  chapters: PlannedChapter[];
}

export interface PlanningResult {
  thread_id: string;
  status: string;
  volume_plan?: VolumePlan;
  settings?: PlannedSettings;
  outline?: PlannedOutline;
  errors?: string[];
}

export interface PlanningIssue {
  type: string;
  severity: "error" | "warning" | "info";
  message: string;
}

export interface GoldenFinger {
  name: string;
  type: string;
  core_ability: string;
  limitation: string;
  growth: string;
  origin: string;
}

export interface Protagonist {
  name: string;
  identity: string;
  core_contradiction: string;
  sensory_memories: string;
  absolute_taboos: string;
  motivation: string;
  initial_state: string;
}

// 交互式聊天创作
export interface ChatHistoryMsg {
  role: "user" | "assistant";
  content: string;
  msg_type: "chat" | "chapter";
  chapter?: number | null;
  title?: string | null;
  brief?: string | null;
  suggested_next?: string | null;
}

export interface AuditIssue {
  dimension?: string;
  severity?: string;
  message?: string;
  location?: string;
}

export interface AuditReport {
  passed?: boolean;
  overall_score?: number;
  summary?: string;
  issues?: AuditIssue[];
  suggestions?: string[];
  user_perspective?: { score?: number; passed?: boolean; issues?: string[]; summary?: string };
  expert_perspective?: { score?: number; passed?: boolean; issues?: string[]; summary?: string };
  editor_perspective?: { score?: number; passed?: boolean; issues?: string[]; summary?: string };
}

export type InteractiveMode = "qa" | "free";

/**
 * 交互创作消息的显式状态机阶段。
 * 作为单一真相源，布尔标志（reviewPending/committing/awaitingVariant 等）
 * 由此派生，guard 逻辑统一用 phase 判断。
 *
 * 状态流转：
 *   drafting -> awaiting_variant -> under_review -> committing -> committed
 *                                     ↑                |
 *                                     └── rewrite/polish ┘（循环）
 *   任意阶段 -> error
 */
export type MessagePhase =
  | "drafting"          // 正在生成初稿
  | "awaiting_variant"  // 抽卡：等待用户选版本
  | "under_review"      // 人审：等待用户决策（通过/重写/润色）
  | "committing"        // 正在处理人审决策（提交/重写/润色中）
  | "committed"         // 已提交到圣经
  | "error";            // 出错

export interface ChatMessage {
  role: "user" | "assistant";
  content: string;
  msg_type: "chat" | "chapter";
  chapter?: number | null;
  title?: string | null;
  word_count?: number | null;
  brief?: string | null;
  suggested_next?: string | null;
  // 前端专用：章节正文是否展开
  expanded?: boolean;
  // 前端专用：是否已提交（更新圣经数据）
  committed?: boolean;
  committing?: boolean;
  commitResult?: string;
  // AI 工作室模式：质检+人审状态
  threadId?: string | null;
  auditReport?: AuditReport | null;
  reviewPending?: boolean;
  polished?: boolean;
  polishIssues?: string[];
  commitDetail?: any;
  isDraft?: boolean;
  // 重写输入框状态（提升到消息对象，避免组件重渲染丢失）
  showRewriteInput?: boolean;
  rewriteFeedback?: string;
  // 深度润色开关
  deepPolish?: boolean;
  // present_options：AI 给的选项（持久化到消息，刷新不丢）
  options?: { label: string; value: string }[];
  // 用户选中的选项 value（高亮显示用）
  selectedOption?: string | null;
  // 抽卡模式：N 个候选版本（等待用户选 1）
  variants?: VariantOption[];
  // 抽卡模式：是否正在等待用户选择版本
  awaitingVariant?: boolean;
  // 显式状态机阶段（单一真相源，布尔标志由此派生）
  phase?: MessagePhase;
}

export interface VariantOption {
  index: number;
  title: string;
  content: string;
  word_count: number;
}

export interface InteractiveChatResponse {
  type: "chapter" | "chat";
  message: string;
  chapter?: number | null;
  title?: string | null;
  content?: string | null;
  word_count?: number | null;
  suggested_next?: string | null;
  brief?: string | null;
}

export interface ImportCounts {
  world_settings: number;
  factions: number;
  faction_relationships: number;
  character_relationships: number;
  characters: number;
  foreshadows: number;
  outlines: number;
  monsters: number;
  instances: number;
}

export interface ImportPreviewData {
  world_settings: Partial<WorldSetting>[];
  factions: Partial<Faction>[];
  faction_relationships: Partial<FactionRelationship>[];
  character_relationships: Partial<CharacterRelationship>[];
  characters: Partial<Character>[];
  foreshadows: Partial<Foreshadow>[];
  outlines: Partial<Outline>[];
  monsters: Partial<Monster>[];
  instances?: Partial<Instance>[];
  golden_finger?: GoldenFinger | null;
  appearances?: Partial<EntityAppearance>[];
}

export type ImportPreviewEntity =
  | Partial<Character>
  | Partial<Faction>
  | Partial<Monster>
  | Partial<Instance>
  | Partial<FactionRelationship>
  | Partial<CharacterRelationship>
  | Partial<WorldSetting>
  | Partial<Foreshadow>
  | Partial<Outline>;

export interface SuggestionItem {
  type: "plot" | "monster" | "faction" | "relationship" | "world" | "character";
  title: string;
  summary: string;
  payload: Record<string, unknown>;
}

export interface AiSuggestion {
  id: number;
  project_id: number;
  context_type: string;
  context_id: string;
  suggest_type: string;
  prompt: string;
  raw_response: string;
  adopted_items: SuggestionItem[];
  status: string;
  created_at: string;
}

// 红线（创作禁忌/硬性约束）
export interface RedLine {
  id: number;
  project_id: number;
  content: string;
  scope: "project" | "chapter";
  chapter_num?: number | null;
  severity: "hard" | "soft";
  created_at?: string;
  updated_at?: string;
}

// 梗（笑点/桥段/彩蛋）
export type GagCategory = "笑点" | "桥段" | "彩蛋";

export interface Gag {
  id: number;
  project_id: number;
  name: string;
  description: string;
  category: GagCategory;
  status: string;
  first_chapter?: number | null;
  usage_notes?: string;
  created_at?: string;
  updated_at?: string;
}

// 文件夹导入的章节
export interface ImportedChapter {
  id: number;
  project_id: number;
  chapter_order: number;
  title: string;
  source_filename: string;
  meta_info?: string;
  chapter_outline?: string;
  detail_outline?: string;
  pleasure_hooks?: string;
  shell_annotation?: string;
  raw_content?: string;
  created_at?: string;
}

export interface ImportedChapterDetail {
  id: number;
  project_id: number;
  chapter_order: number;
  title: string;
  source_filename: string;
  meta_info: string;
  chapter_outline?: string;
  detail_outline?: string;
  pleasure_hooks?: string;
  shell_annotation?: string;
  raw_content?: string;
  created_at?: string;
}
