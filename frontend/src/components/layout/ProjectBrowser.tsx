import { useState } from "react";
import { useNavigate } from "react-router-dom";
import { useAppStore } from "@/store";
import { TreeItem } from "@/components/ui/tree";

export interface ProjectBrowserProps {
  onOpenChapter?: (chapterId: number, title: string) => void;
}

const CATEGORIES = [
  { key: "outline", label: "章节", icon: "📄" },
  { key: "characters", label: "角色", icon: "👤" },
  { key: "world", label: "世界设定", icon: "🌍" },
  { key: "foreshadows", label: "伏笔", icon: "🪝" },
  { key: "factions", label: "势力 / 怪物", icon: "🏰" },
] as const;

type CategoryKey = (typeof CATEGORIES)[number]["key"];

export function ProjectBrowser({ onOpenChapter }: ProjectBrowserProps) {
  const navigate = useNavigate();
  const [expanded, setExpanded] = useState<Record<CategoryKey, boolean>>({
    outline: true,
    characters: false,
    world: false,
    foreshadows: false,
    factions: false,
  });

  const chapters = useAppStore((s) => s.chapters);
  const characters = useAppStore((s) => s.characters);
  const worldSettings = useAppStore((s) => s.worldSettings);
  const foreshadows = useAppStore((s) => s.foreshadows);
  const factions = useAppStore((s) => s.factions);
  const currentProject = useAppStore((s) => s.currentProject);
  const projectId = currentProject?.id;

  const toggle = (key: CategoryKey) => {
    setExpanded((prev) => ({ ...prev, [key]: !prev[key] }));
  };

  const goToAssets = () => {
    if (projectId) navigate(`/projects/${projectId}/assets`);
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
              {chapters.length === 0 ? (
                <TreeItem label="暂无章节，请到大纲页生成" depth={1} />
              ) : (
                chapters.map((chapter) => (
                  <TreeItem
                    key={chapter.chapter}
                    label={chapter.title || `第${chapter.chapter}章`}
                    depth={1}
                    onClick={
                      onOpenChapter
                        ? () => onOpenChapter(chapter.chapter, chapter.title)
                        : undefined
                    }
                  />
                ))
              )}
            </div>
          )}

          {expanded[category.key] && category.key === "characters" && (
            <div className="mt-0.5">
              {characters.length === 0 ? (
                <TreeItem label="暂无角色，请到资产页添加" depth={1} />
              ) : (
                characters.map((character) => (
                  <TreeItem
                    key={character.id}
                    label={character.name || `角色 #${character.id}`}
                    depth={1}
                    onClick={goToAssets}
                  />
                ))
              )}
            </div>
          )}

          {expanded[category.key] && category.key === "world" && (
            <div className="mt-0.5">
              {worldSettings.length === 0 ? (
                <TreeItem label="暂无世界设定，请到资产页添加" depth={1} />
              ) : (
                worldSettings.map((w) => (
                  <TreeItem
                    key={w.id}
                    label={w.title || `设定 #${w.id}`}
                    depth={1}
                    onClick={goToAssets}
                  />
                ))
              )}
            </div>
          )}

          {expanded[category.key] && category.key === "foreshadows" && (
            <div className="mt-0.5">
              {foreshadows.length === 0 ? (
                <TreeItem label="暂无伏笔，请到资产页添加" depth={1} />
              ) : (
                foreshadows.map((f) => (
                  <TreeItem
                    key={f.id}
                    label={`${f.foreshadow_id}${f.description ? ` · ${f.description.slice(0, 12)}` : ""}`}
                    depth={1}
                    onClick={goToAssets}
                  />
                ))
              )}
            </div>
          )}

          {expanded[category.key] && category.key === "factions" && (
            <div className="mt-0.5">
              {factions.length === 0 ? (
                <TreeItem label="暂无势力，请到资产页添加" depth={1} />
              ) : (
                factions.map((f) => (
                  <TreeItem
                    key={f.id}
                    label={f.name || `势力 #${f.id}`}
                    depth={1}
                    onClick={goToAssets}
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
