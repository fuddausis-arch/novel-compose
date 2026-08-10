// 百科卡页：五类实体卡片浏览 + 出场场景索引（可视化融合 P5）。
// 数据走后端 /api/encyclopedia/{project_id}，点击卡片复用 EntityCardDrawer 看全字段详情。

import { useCallback, useEffect, useState } from "react";
import { Loader2 } from "lucide-react";
import { EntityCardDrawer, type EntityCardType } from "@/components/entity/EntityCardDrawer";
import { EntityCard } from "@/components/entity/entity-card";
import { ENTITY_TYPE_META, FORESHADOW_STATUS_LABEL } from "@/components/entity/entity-meta";
import { Badge } from "@/components/ui/badge";
import { ScrollArea } from "@/components/ui/scroll-area";
import { useCurrentProject } from "@/hooks/useCurrentProject";
import { cn } from "@/lib/utils";

// ==================== 类型定义 ====================

interface EntityItem {
  entity_type: EntityCardType;
  id: number;
  name: string;
  summary?: string;
  appearance_chapters?: number[];
  appearance_count?: number;
  role?: string;
  importance?: string;
  tier?: string;
  type?: string;
  rank?: string;
  layer?: string;
  parent_name?: string;
  status?: string;
  foreshadow_id?: string;
  plant_chapter?: number;
  planned_resolve_chapter?: number;
}

interface EncyclopediaData {
  characters: EntityItem[];
  factions: EntityItem[];
  monsters: EntityItem[];
  locations: EntityItem[];
  foreshadows: EntityItem[];
  counts: Record<string, number>;
}

type SectionKey = "characters" | "factions" | "monsters" | "locations" | "foreshadows";

/** 分类 Tab 元信息：由公共 ENTITY_TYPE_META 派生 */
const SECTION_META: { key: SectionKey; entityType: EntityCardType; label: string; icon: React.ReactNode; badge: string }[] = (
  [
    ["characters", "character"],
    ["factions", "faction"],
    ["monsters", "monster"],
    ["locations", "location"],
    ["foreshadows", "foreshadow"],
  ] as const
).map(([key, entityType]) => ({
  key,
  entityType,
  label: ENTITY_TYPE_META[entityType].label,
  icon: ENTITY_TYPE_META[entityType].icon,
  badge: ENTITY_TYPE_META[entityType].badge,
}));

// 各实体类型 → 实体卡片抽屉的 entityId（character/faction/monster/location 按名字，foreshadow 按 foreshadow_id）
function entityIdFor(item: EntityItem): string {
  if (item.entity_type === "foreshadow") return item.foreshadow_id || item.name;
  return item.name;
}

// ==================== 主视图 ====================

export function EncyclopediaView() {
  const { projectId } = useCurrentProject();
  const [data, setData] = useState<EncyclopediaData | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [activeTab, setActiveTab] = useState<keyof EncyclopediaData>("characters");
  const [drawer, setDrawer] = useState<{ entityType: EntityCardType; entityId: string } | null>(null);

  const load = useCallback(async () => {
    if (!projectId) return;
    setLoading(true);
    setError(null);
    try {
      const res = await fetch(`/api/encyclopedia/${projectId}`);
      if (!res.ok) {
        const body = await res.json().catch(() => null);
        throw new Error(body?.detail || `HTTP ${res.status}`);
      }
      setData((await res.json()) as EncyclopediaData);
    } catch (e: any) {
      setError(e.message || "加载失败");
      setData(null);
    } finally {
      setLoading(false);
    }
  }, [projectId]);

  useEffect(() => {
    void load();
  }, [load]);

  const openEntity = (item: EntityItem) => {
    if (!projectId) return;
    setDrawer({ entityType: item.entity_type, entityId: entityIdFor(item) });
  };

  if (loading) {
    return (
      <div className="flex h-full items-center justify-center text-muted" role="status">
        <Loader2 size={20} className="mr-2 animate-spin" aria-hidden="true" />
        加载百科卡...
      </div>
    );
  }

  if (error) {
    return (
      <div className="flex h-full flex-col items-center justify-center gap-2 text-muted">
        <p className="text-sm">{error}</p>
        <button type="button" onClick={load} className="cursor-pointer text-xs text-primary hover:underline">
          重试
        </button>
      </div>
    );
  }

  const items = data ? (data[activeTab] as EntityItem[] | undefined) ?? [] : [];

  return (
    <div className="flex h-full flex-col">
      {/* 顶部：分类 Tab + 统计 */}
      <div className="flex flex-wrap items-center gap-2 border-b border-border bg-surface px-4 py-3">
        <h2 className="text-sm font-semibold text-foreground">百科卡</h2>
        <span className="text-[11px] text-muted">点击卡片查看完整详情 · 别名可修正可回滚</span>
        <div className="ml-auto flex flex-wrap gap-1">
          {SECTION_META.map((sec) => (
            <button
              key={sec.key}
              type="button"
              onClick={() => setActiveTab(sec.key)}
              className={cn(
                "flex cursor-pointer items-center gap-1 rounded-lg px-2.5 py-1 text-xs font-medium transition-colors",
                activeTab === sec.key
                  ? "bg-primary text-primary-foreground"
                  : "text-muted hover:bg-surface-hover hover:text-foreground",
              )}
            >
              {sec.icon}
              {sec.label}
              <span className="text-[10px] opacity-70">{data?.counts?.[sec.key] ?? 0}</span>
            </button>
          ))}
        </div>
      </div>

      {/* 实体卡片网格 */}
      <ScrollArea className="flex-1">
        {items.length === 0 ? (
          <div className="flex h-full items-center justify-center text-sm text-muted">
            暂无{SECTION_META.find((m) => m.key === activeTab)?.label}，可先到「资产」页创建
          </div>
        ) : (
          <div className="grid grid-cols-1 gap-3 p-4 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4">
            {items.map((item) => {
              const meta = SECTION_META.find((m) => m.entityType === item.entity_type);
              return (
                <EntityCard
                  key={item.id}
                  onClick={() => openEntity(item)}
                  title={item.name}
                  titleClassName="min-w-0 flex-1 truncate font-semibold"
                  leadingIcon={meta?.icon}
                  badge={
                    item.appearance_count !== undefined &&
                    item.entity_type !== "foreshadow" &&
                    item.entity_type !== "location" ? (
                      <Badge className="shrink-0 px-1.5 py-0 text-[9px]">
                        {item.appearance_count > 0 ? `出场${item.appearance_count}章` : "未出场"}
                      </Badge>
                    ) : undefined
                  }
                  description={item.summary}
                  descriptionClassName="line-clamp-2 text-xs leading-relaxed whitespace-normal"
                  className="gap-1.5 rounded-lg bg-surface-elevated p-3 hover:border-primary/40 hover:bg-surface-hover"
                  contentClassName="p-0 gap-1.5"
                  headerClassName="items-center gap-1.5"
                >
                  <div className="flex flex-wrap items-center gap-1">
                    {item.role && <Badge className="bg-secondary px-1.5 py-0 text-[9px] text-muted">{item.role}</Badge>}
                    {item.importance && <Badge className="bg-secondary px-1.5 py-0 text-[9px] text-muted">{item.importance}</Badge>}
                    {item.tier && <Badge className="bg-secondary px-1.5 py-0 text-[9px] text-muted">{item.tier}</Badge>}
                    {item.type && <Badge className="bg-secondary px-1.5 py-0 text-[9px] text-muted">{item.type}</Badge>}
                    {item.layer && item.layer !== "surface" && <Badge className="bg-secondary px-1.5 py-0 text-[9px] text-muted">{item.layer}</Badge>}
                    {item.parent_name && <Badge className="bg-secondary px-1.5 py-0 text-[9px] text-muted">父：{item.parent_name}</Badge>}
                    {item.status && (
                      <Badge className={`px-1.5 py-0 text-[9px] ${FORESHADOW_STATUS_LABEL[item.status]?.cls ?? "bg-secondary text-muted"}`}>
                        {FORESHADOW_STATUS_LABEL[item.status]?.text ?? item.status}
                      </Badge>
                    )}
                  </div>
                  {item.appearance_chapters && item.appearance_chapters.length > 0 && (
                    <div className="flex flex-wrap gap-1">
                      {item.appearance_chapters.slice(0, 12).map((ch) => (
                        <span key={ch} className="inline-flex items-center rounded bg-surface-hover px-1 py-0.5 text-[9px] text-muted">
                          第{ch}章
                        </span>
                      ))}
                      {item.appearance_chapters.length > 12 && (
                        <span className="text-[9px] text-muted">+{item.appearance_chapters.length - 12}</span>
                      )}
                    </div>
                  )}
                </EntityCard>
              );
            })}
          </div>
        )}
      </ScrollArea>

      {/* 实体卡片抽屉（复用 P2 组件） */}
      {drawer && projectId && (
        <EntityCardDrawer
          open={drawer !== null}
          onClose={() => setDrawer(null)}
          projectId={projectId}
          entityType={drawer.entityType}
          entityId={drawer.entityId}
        />
      )}
    </div>
  );
}
