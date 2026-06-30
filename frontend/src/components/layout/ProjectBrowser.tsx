import { useState } from "react";
import { useAppStore } from "@/store";
import { TreeItem } from "@/components/ui/tree";

const CATEGORIES = [
  { key: "outline", label: "大纲", icon: "📁" },
  { key: "characters", label: "角色", icon: "👤" },
  { key: "world", label: "世界设定", icon: "🌍" },
  { key: "foreshadows", label: "伏笔", icon: "🪝" },
  { key: "factions", label: "势力 / 怪物", icon: "🏰" },
] as const;

type CategoryKey = (typeof CATEGORIES)[number]["key"];

export function ProjectBrowser() {
  const [expanded, setExpanded] = useState<Record<CategoryKey, boolean>>({
    outline: true,
    characters: false,
    world: false,
    foreshadows: false,
    factions: false,
  });

  const outlines = useAppStore((s) => s.outlines);
  const characters = useAppStore((s) => s.characters);

  const toggle = (key: CategoryKey) => {
    setExpanded((prev) => ({ ...prev, [key]: !prev[key] }));
  };

  return (
    <div className="flex flex-col gap-1 p-3">
      <div className="px-2 pb-1 text-[10px] uppercase tracking-wider text-muted font-semibold">
        项目浏览器
      </div>

      {CATEGORIES.map((category) => (
        <div key={category.key}>
          <TreeItem
            label={
              <span className="flex items-center gap-1.5">
                <span>{category.icon}</span>
                <span>{category.label}</span>
              </span>
            }
            expanded={expanded[category.key]}
            onToggle={() => toggle(category.key)}
            onClick={() => toggle(category.key)}
          />

          {expanded[category.key] && category.key === "outline" && (
            <div className="mt-0.5">
              {outlines.length === 0 ? (
                <TreeItem label="暂无大纲" depth={1} />
              ) : (
                outlines.map((outline) => (
                  <TreeItem
                    key={outline.id}
                    label={outline.title || `大纲 #${outline.id}`}
                    depth={1}
                  />
                ))
              )}
            </div>
          )}

          {expanded[category.key] && category.key === "characters" && (
            <div className="mt-0.5">
              {characters.length === 0 ? (
                <TreeItem label="暂无角色" depth={1} />
              ) : (
                characters.map((character) => (
                  <TreeItem
                    key={character.id}
                    label={character.name || `角色 #${character.id}`}
                    depth={1}
                  />
                ))
              )}
            </div>
          )}
        </div>
      ))}
    </div>
  );
}
