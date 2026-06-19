export type AssetType = "character" | "foreshadow" | "outline" | "chapter" | "faction" | "factionRelationship" | "characterRelationship" | "monster";
export type Tab = "dashboard" | "planning" | "world" | "characters" | "outlines-volume" | "outlines-arc" | "outlines-chapter" | "asset" | "chapter" | "summaries" | "import" | "export" | "factions" | "relationships" | "monsters" | "settings";

export interface Project {
  id: number;
  title: string;
  genre: string;
  summary: string;
  style: string;
  created_at: string;
  updated_at: string;
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

export interface ChapterCommit {
  id: number;
  project_id: number;
  chapter: number;
  status: "draft" | "committed";
  summary: string;
  word_count: number;
  committed_at: string | null;
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

export interface LLMConfig {
  base_url: string;
  api_key: string;
  model: string;
  temperature: number;
  max_tokens: number;
  timeout: number;
  vision_enabled: boolean;
  context_length?: number;
}

export interface ChapterListItem {
  chapter: number;
  text_preview: string;
}

export interface ChapterText {
  chapter: number;
  text: string;
}

export interface PipelineNodeEvent {
  node: string;
  output: Record<string, unknown>;
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

export interface VolumePlan {
  volumes?: { name: string; chapters: number }[];
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

export interface ImportPreviewData {
  world_settings: Partial<WorldSetting>[];
  factions: Partial<Faction>[];
  faction_relationships: Partial<FactionRelationship>[];
  character_relationships: Partial<CharacterRelationship>[];
  characters: Partial<Character>[];
  foreshadows: Partial<Foreshadow>[];
  outlines: Partial<Outline>[];
  monsters: Partial<Monster>[];
  appearances?: Partial<EntityAppearance>[];
}

export type ImportPreviewEntity =
  | Partial<Character>
  | Partial<Faction>
  | Partial<Monster>
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
