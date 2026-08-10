import { useState } from "react";
import { LayoutGrid, List } from "lucide-react";

import { Button } from "@/components/ui/button";
import { cn } from "@/lib/utils";
import { useAppStore } from "@/store";
import type { AssetNavType } from "./AssetTypeNav";
import type { Character, Faction, Foreshadow, Monster, WorldSetting } from "@/types";

type AssetItem = Character | WorldSetting | Foreshadow | Faction | Monster;

const TYPE_META: Record<AssetNavType, { label: string }> = {
  characters: { label: "角色" },
  world: { label: "世界设定" },
  foreshadows: { label: "伏笔" },
  factions: { label: "势力" },
  monsters: { label: "怪物" },
  instances: { label: "副本" },
  redLines: { label: "红线" },
  gags: { label: "梗管理" },
  importFolder: { label: "导入文件夹" },
};

function getAssetItemTitle(item: AssetItem, fallbackLabel: string): string {
  if ("name" in item && item.name) return item.name;
  if ("title" in item && item.title) return item.title;
  return `${fallbackLabel} #${item.id}`;
}

function getAssetItemSubtitle(item: AssetItem): string {
  if ("description" in item && item.description) return item.description;
  if ("content" in item && item.content) return item.content;
  if ("species" in item && item.species) return item.species;
  if ("role" in item && item.role) return item.role;
  return "";
}

export interface AssetCardsProps {
  type: AssetNavType;
}

export function AssetCards({ type }: AssetCardsProps) {
  const [view, setView] = useState<"grid" | "list">("grid");
  const meta = TYPE_META[type];

  const items = useAppStore((s) => {
    switch (type) {
      case "characters":
        return s.characters;
      case "world":
        return s.worldSettings;
      case "foreshadows":
        return s.foreshadows;
      case "factions":
        return s.factions;
      case "monsters":
        return s.monsters;
      default:
        return [];
    }
  });

  return (
    <div className="flex flex-1 flex-col overflow-hidden bg-background">
      <header className="flex items-center justify-between border-b border-border px-6 py-4">
        <h2 className="text-lg font-semibold text-foreground">{meta.label}</h2>
        <div className="flex items-center gap-1 rounded-lg border border-border bg-surface p-1">
          <Button
            variant="ghost"
            size="sm"
            className={cn("h-7 px-2", view === "grid" && "bg-foreground/10")}
            onClick={() => setView("grid")}
            aria-label="卡片视图"
          >
            <LayoutGrid className="h-4 w-4" />
          </Button>
          <Button
            variant="ghost"
            size="sm"
            className={cn("h-7 px-2", view === "list" && "bg-foreground/10")}
            onClick={() => setView("list")}
            aria-label="列表视图"
          >
            <List className="h-4 w-4" />
          </Button>
        </div>
      </header>

      <div className="flex-1 overflow-y-auto p-6">
        <div
          className={cn(
            "gap-4",
            view === "grid"
              ? "grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3"
              : "flex flex-col"
          )}
        >
          {items.map((item) => (
            <div
              key={item.id}
              className={cn(
                "rounded-xl border border-border bg-surface-elevated p-4 transition-all hover:border-border-strong hover:shadow",
                view === "list" && "flex items-center justify-between gap-4"
              )}
            >
              <h3 className="font-semibold text-foreground truncate">
                {getAssetItemTitle(item as AssetItem, meta.label)}
              </h3>
              {view === "grid" && (
                <p className="mt-1 text-sm text-muted line-clamp-2">
                  {getAssetItemSubtitle(item as AssetItem) || "暂无描述"}
                </p>
              )}
            </div>
          ))}

          <button className="flex min-h-[120px] flex-col items-center justify-center gap-2 rounded-xl border border-dashed border-border bg-transparent p-4 text-muted transition-colors hover:border-border-strong hover:bg-foreground/5">
            <span className="text-2xl leading-none">+</span>
            <span className="text-sm font-medium">添加</span>
          </button>
        </div>
      </div>
    </div>
  );
}
