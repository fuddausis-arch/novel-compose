/** 圆桌讨论预设数据：席位配色、小说场景席位预设与讨论模板（纯前端配置，后端引擎待接入） */

/** 讨论调度策略：固定轮询 / 智能主持 */
export type RoundtableStrategy = "round_robin" | "moderator_decides";

/** 单个席位配置 */
export interface RoundtableSeat {
  role_name: string;
  system_prompt: string;
  temperature: number;
  is_moderator: boolean;
}

/** 讨论模板：一键填充主题 + 策略 + 席位组合 */
export interface RoundtableTemplate {
  name: string;
  topic: string;
  strategy: RoundtableStrategy;
  seats: RoundtableSeat[];
}

/** 席位配色环（按席位下标取色，对齐 DF 圆桌调色板） */
const SEAT_COLORS = [
  { dot: "bg-indigo-500", text: "text-indigo-400", border: "border-indigo-500/30", bg: "bg-indigo-500/5" },
  { dot: "bg-purple-500", text: "text-purple-400", border: "border-purple-500/30", bg: "bg-purple-500/5" },
  { dot: "bg-cyan-500", text: "text-cyan-400", border: "border-cyan-500/30", bg: "bg-cyan-500/5" },
  { dot: "bg-emerald-500", text: "text-emerald-400", border: "border-emerald-500/30", bg: "bg-emerald-500/5" },
  { dot: "bg-amber-400", text: "text-amber-400", border: "border-amber-400/30", bg: "bg-amber-400/5" },
  { dot: "bg-rose-400", text: "text-rose-400", border: "border-rose-400/30", bg: "bg-rose-400/5" },
] as const;

/** 按席位下标取配色 */
export function getSeatColor(index: number) {
  return SEAT_COLORS[index % SEAT_COLORS.length];
}

/** 席位数量下限（少于 2 席无法构成讨论） */
export const MIN_SEATS = 2;
/** 席位数量上限（对齐 DF 圆桌） */
export const MAX_SEATS = 6;
/** 讨论轮次上限 */
export const MAX_ROUNDS = 20;

/** 小说场景席位预设：作者 / 编辑 / 读者 / 评论家 / 设定顾问 */
export const SEAT_PRESETS = [
  {
    key: "author",
    role_name: "作者",
    system_prompt:
      "你是本书的作者，提出剧情构想并拍板决策。关注故事整体节奏、爽点密度与商业吸引力，对每个提议给出明确的取舍理由。",
    temperature: 0.7,
  },
  {
    key: "editor",
    role_name: "编辑",
    system_prompt:
      "你是资深网文编辑，关注市场风向、读者留存与章节钩子。从商业化角度审视剧情决策，尖锐指出可能的弃书点。",
    temperature: 0.6,
  },
  {
    key: "reader",
    role_name: "读者",
    system_prompt:
      "你是目标读者代表，以普通读者视角给出最直观的阅读感受：哪里爽、哪里闷、哪里看不懂，直言不讳。",
    temperature: 0.9,
  },
  {
    key: "critic",
    role_name: "评论家",
    system_prompt:
      "你是苛刻的文学评论家，关注人物弧光、主题深度与叙事逻辑，会尖锐指出剧情的漏洞与套路化问题。",
    temperature: 0.7,
  },
  {
    key: "setting_advisor",
    role_name: "设定顾问",
    system_prompt:
      "你是世界观设定顾问，负责维护设定一致性。任何违背世界观的提议都会被你指出，并给出符合设定的替代方案。",
    temperature: 0.3,
  },
] as const;

/** 席位预设 key 类型 */
export type SeatPresetKey = (typeof SEAT_PRESETS)[number]["key"];

/** 由预设 key 生成席位配置（可指定是否为主持人），每次返回全新对象避免共享引用 */
export function presetSeat(key: SeatPresetKey, isModerator = false): RoundtableSeat {
  const preset = SEAT_PRESETS.find((p) => p.key === key)!;
  return {
    role_name: preset.role_name,
    system_prompt: preset.system_prompt,
    temperature: preset.temperature,
    is_moderator: isModerator,
  };
}

/** 讨论模板预设（小说创作场景） */
export const ROUNDTABLE_TEMPLATES: RoundtableTemplate[] = [
  {
    name: "章节走向讨论",
    topic: "下一章剧情走向：高潮点安排与章末钩子设计",
    strategy: "round_robin",
    seats: [presetSeat("author"), presetSeat("editor"), presetSeat("reader")],
  },
  {
    name: "角色弧线规划",
    topic: "主角成长弧线：本卷的心态转变与关键事件安排",
    strategy: "round_robin",
    seats: [presetSeat("author"), presetSeat("editor"), presetSeat("critic")],
  },
  {
    name: "伏笔布局讨论",
    topic: "核心伏笔的埋设位置与回收节奏规划",
    strategy: "moderator_decides",
    seats: [presetSeat("author", true), presetSeat("setting_advisor"), presetSeat("editor")],
  },
  {
    name: "设定冲突裁决",
    topic: "新剧情与世界观设定的冲突裁决",
    strategy: "moderator_decides",
    seats: [presetSeat("setting_advisor", true), presetSeat("author"), presetSeat("critic")],
  },
];

/** 空白新席位 */
export function blankSeat(): RoundtableSeat {
  return { role_name: "", system_prompt: "", temperature: 0.7, is_moderator: false };
}

/** 克隆席位数组（避免模板与页面状态共享引用） */
export function cloneSeats(seats: RoundtableSeat[]): RoundtableSeat[] {
  return seats.map((s) => ({ ...s }));
}
