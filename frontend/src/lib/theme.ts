export type ThemeKey = "light-glass" | "warm-paper" | "dark-ai";

export interface ThemeOption {
  key: ThemeKey;
  label: string;
  icon: "sun" | "book-open" | "moon";
  description: string;
}

export const THEMES: ThemeOption[] = [
  {
    key: "light-glass",
    label: "精致浅色",
    icon: "sun",
    description: "浅灰玻璃风，默认",
  },
  {
    key: "warm-paper",
    label: "温暖纸墨",
    icon: "book-open",
    description: "米白护眼写作风",
  },
  {
    key: "dark-ai",
    label: "深色 AI",
    icon: "moon",
    description: "深色科技指挥风",
  },
];

export const STORAGE_KEY = "novel-agent-theme";
export const DEFAULT_THEME: ThemeKey = "light-glass";

export function isValidTheme(value: string): value is ThemeKey {
  return THEMES.some((t) => t.key === value);
}
