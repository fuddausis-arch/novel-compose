import { useEffect, useState } from "react";
import { LayoutGrid, List, Loader2 } from "lucide-react";

import { Button } from "@/components/ui/button";
import { cn } from "@/lib/utils";
import { useAppStore } from "@/store";
import { api } from "@/api";
import type { AssetNavType } from "./AssetTypeNav";
import type { Character, Faction, Foreshadow, Monster, WorldSetting } from "@/types";

type AssetItem = Character | WorldSetting | Foreshadow | Faction | Monster;

// 模块级稳定引用：避免 default 分支每次渲染新建空数组，
// 导致 zustand useSyncExternalStore 判定快照恒变 → 无限重渲染崩溃
const EMPTY_ITEMS: AssetItem[] = [];

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
  // P0-4 扩充
  locations: { label: "地点" },
  emotionArcs: { label: "情感弧线" },
  pleasureBeats: { label: "爽点" },
  memoryRefinements: { label: "记忆精炼" },
  nameOverrides: { label: "命名覆盖" },
  events: { label: "事件流" },
};

// P0-4：新增资产类型走 API 拉取（只读列表，覆盖 42 表透明诉求）
const EXTRA_LOADERS: Partial<Record<AssetNavType, (projectId: number) => Promise<any[]>>> = {
  locations: (pid) => api.listLocations(pid),
  emotionArcs: (pid) => api.listEmotionArcs(pid),
  pleasureBeats: (pid) => api.listPleasureBeats(pid),
  memoryRefinements: (pid) => api.listMemoryRefinements(pid).then((r) => r.items),
  nameOverrides: (pid) => api.listNameOverrides(pid),
  events: (pid) => api.listEvents(pid),
};

function getAssetItemTitle(item: any, fallbackLabel: string): string {
  if (item.character_name) return `${item.character_name} · 第${item.chapter}章`;
  if (item.canonical_name) return item.canonical_name;
  if ("name" in item && item.name) return item.name;
  if ("title" in item && item.title) return item.title;
  if (item.entity_id) return item.entity_id;
  return `${fallbackLabel} #${item.id}`;
}

function getAssetItemSubtitle(item: any): string {
  if (item.emotion_before !== undefined) {
    const change = `${item.emotion_before || "?"} → ${item.emotion_after || "?"}`;
    return item.event ? `${change}（${item.event}）` : change;
  }
  if (item.beat_type) {
    return `第${item.chapter}章 ${item.beat_type}（强度${item.intensity}/10）${item.delivered ? " · 已交付" : " · 未交付"}`;
  }
  if (item.alias) return `${item.alias} → ${item.canonical_name}`;
  if (item.event_type) return `第${item.chapter}章 [${item.event_type}] ${item.entity_id}`;
  if (item.new_value !== undefined && item.new_value !== null) return item.new_value;
  if (item.description) return item.description;
  if (item.content) return item.content;
  if (item.species) return item.species;
  if (item.role) return item.role;
  if (item.parent_name) return `上级：${item.parent_name}`;
  return "";
}

export interface AssetCardsProps {
  type: AssetNavType;
  projectId?: number;
}

export function AssetCards({ type, projectId }: AssetCardsProps) {
  const [view, setView] = useState<"grid" | "list">("grid");
  const [extraItems, setExtraItems] = useState<any[]>([]);
  const [loading, setLoading] = useState(false);
  const meta = TYPE_META[type];

  const storeItems = useAppStore((s) => {
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
        return EMPTY_ITEMS;
    }
  });

  // 新增类型：进入 tab 时按需拉取只读列表
  useEffect(() => {
    const loader = EXTRA_LOADERS[type];
    if (!loader || !projectId) {
      setExtraItems([]);
      return;
    }
    let cancelled = false;
    setLoading(true);
    loader(projectId)
      .then((data) => {
        if (!cancelled) setExtraItems(data || []);
      })
      .catch(() => {
        if (!cancelled) setExtraItems([]);
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [type, projectId]);

  const isExtra = type in EXTRA_LOADERS;
  const items: any[] = isExtra ? extraItems : storeItems;

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
        {loading ? (
          <div className="flex items-center justify-center py-16 text-muted">
            <Loader2 className="h-4 w-4 animate-spin mr-2" /> 加载中…
          </div>
        ) : items.length === 0 ? (
          <div className="py-16 text-center text-sm text-muted">暂无{meta.label}数据</div>
        ) : (
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
                  {getAssetItemTitle(item, meta.label)}
                </h3>
                {view === "grid" && (
                  <p className="mt-1 text-sm text-muted line-clamp-2">
                    {getAssetItemSubtitle(item) || "暂无描述"}
                  </p>
                )}
              </div>
            ))}
          </div>
        )}
      </div>
    </div>
  );
}
