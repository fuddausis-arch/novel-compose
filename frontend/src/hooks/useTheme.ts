import { useEffect, useState, useCallback } from "react";
import { type ThemeKey, DEFAULT_THEME, STORAGE_KEY, isValidTheme } from "@/lib/theme";

export function useTheme() {
  const [theme, setThemeState] = useState<ThemeKey>(() => {
    if (typeof window === "undefined") return DEFAULT_THEME;
    const saved = localStorage.getItem(STORAGE_KEY);
    return saved && isValidTheme(saved) ? saved : DEFAULT_THEME;
  });

  const [mounted, setMounted] = useState(false);

  useEffect(() => {
    setMounted(true);
  }, []);

  const setTheme = useCallback((newTheme: ThemeKey) => {
    setThemeState(newTheme);
    localStorage.setItem(STORAGE_KEY, newTheme);
    document.documentElement.setAttribute("data-theme", newTheme);
  }, []);

  useEffect(() => {
    document.documentElement.setAttribute("data-theme", theme);
  }, [theme]);

  return { theme, setTheme, mounted };
}
