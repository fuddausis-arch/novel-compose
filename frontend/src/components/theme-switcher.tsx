import { useState, useRef, useEffect } from "react";
import { Sun, Moon, BookOpen, Check } from "lucide-react";
import { Button } from "@/components/ui/button";
import { cn } from "@/lib/utils";
import { THEMES, type ThemeKey } from "@/lib/theme";
import { useTheme } from "@/hooks/useTheme";

const ICONS: Record<ThemeKey, typeof Sun> = {
  "light-glass": Sun,
  "warm-paper": BookOpen,
  "dark-ai": Moon,
};

export function ThemeSwitcher() {
  const { theme, setTheme, mounted } = useTheme();
  const [open, setOpen] = useState(false);
  const ref = useRef<HTMLDivElement>(null);

  useEffect(() => {
    function handleClickOutside(e: MouseEvent) {
      if (ref.current && !ref.current.contains(e.target as Node)) {
        setOpen(false);
      }
    }
    document.addEventListener("mousedown", handleClickOutside);
    return () => document.removeEventListener("mousedown", handleClickOutside);
  }, []);

  if (!mounted) return null;

  const ActiveIcon = ICONS[theme];

  return (
    <div className="relative" ref={ref}>
      <Button
        variant="ghost"
        size="sm"
        onClick={() => setOpen(!open)}
        className="gap-1.5"
        aria-label="切换主题"
      >
        <ActiveIcon className="h-4 w-4" />
        <span className="hidden sm:inline text-xs">主题</span>
      </Button>

      {open && (
        <div
          className="absolute right-0 top-full mt-2 w-56 rounded-xl border border-border bg-surface p-2 shadow-lg z-50"
          style={{
            animation: "themeDropdownIn 150ms ease-out forwards",
          }}
        >
          <div className="text-xs font-medium text-muted px-2 py-1.5">选择主题</div>
          {THEMES.map((t) => {
            const Icon = ICONS[t.key];
            const active = theme === t.key;
            return (
              <button
                key={t.key}
                onClick={() => {
                  setTheme(t.key);
                  setOpen(false);
                }}
                className={cn(
                  "w-full flex items-center gap-3 px-2 py-2 rounded-lg text-left transition-colors",
                  active ? "bg-primary/10 text-primary" : "hover:bg-foreground/5 text-foreground"
                )}
              >
                <div
                  className={cn(
                    "w-8 h-8 rounded-lg flex items-center justify-center border",
                    active ? "border-primary bg-primary/10" : "border-border bg-surface-elevated"
                  )}
                >
                  <Icon className="h-4 w-4" />
                </div>
                <div className="flex-1 min-w-0">
                  <div className="text-sm font-medium">{t.label}</div>
                  <div className="text-xs text-muted truncate">{t.description}</div>
                </div>
                {active && <Check className="h-4 w-4 text-primary" />}
              </button>
            );
          })}
        </div>
      )}
    </div>
  );
}
