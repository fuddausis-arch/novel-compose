import { useCallback, useEffect, useMemo, useState } from "react";
import { Activity, Heart, Link2, MapPin, RefreshCw, Sparkles, User, Users } from "lucide-react";
import { useAppStore } from "@/store";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { useToast } from "@/hooks/useToast";

// ==================== 类型定义 ====================

interface TimelineChapter {
  chapter: number;
  title: string;
  time_location: string;
  core_events: string;
  chapter_hook: string;
  word_count: number;
}

interface TimelineLaneItem {
  chapter: number;
  [key: string]: any;
}

interface TimelineData {
  project_id: number;
  chapters: TimelineChapter[];
  chapter_range: [number, number];
  lanes: {
    characters: TimelineLaneItem[];
    relationships: TimelineLaneItem[];
    foreshadows: TimelineLaneItem[];
    states: TimelineLaneItem[];
    emotions: TimelineLaneItem[];
  };
  events: { chapter: number; type: string; entity_id: string; detail: string; payload: any }[];
  counts: {
    characters: number;
    relationships: number;
    foreshadows: number;
    states: number;
    emotions: number;
    events: number;
  };
}

// 泳道标签颜色映射
const LANE_COLORS: Record<string, { dot: string; badge: string }> = {
  characters: { dot: "bg-blue-500", badge: "text-blue-600 bg-blue-50 dark:text-blue-400 dark:bg-blue-950/40" },
  relationships: { dot: "bg-purple-500", badge: "text-purple-600 bg-purple-50 dark:text-purple-400 dark:bg-purple-950/40" },
  foreshadows: { dot: "bg-amber-500", badge: "text-amber-600 bg-amber-50 dark:text-amber-400 dark:bg-amber-950/40" },
  states: { dot: "bg-cyan-500", badge: "text-cyan-600 bg-cyan-50 dark:text-cyan-400 dark:bg-cyan-950/40" },
  emotions: { dot: "bg-pink-500", badge: "text-pink-600 bg-pink-50 dark:text-pink-400 dark:bg-pink-950/40" },
};

const EMOTION_LABEL_STYLE: Record<string, string> = {
  danger: "text-danger bg-danger/10",
  sad: "text-indigo-600 bg-indigo-50 dark:text-indigo-400 dark:bg-indigo-950/40",
  happy: "text-emerald-600 bg-emerald-50 dark:text-emerald-400 dark:bg-emerald-950/40",
  tense: "text-amber-600 bg-amber-50 dark:text-amber-400 dark:bg-amber-950/40",
  calm: "text-slate-500 bg-slate-100 dark:text-slate-400 dark:bg-slate-800/50",
  fear: "text-purple-600 bg-purple-50 dark:text-purple-400 dark:bg-purple-950/40",
  shock: "text-orange-600 bg-orange-50 dark:text-orange-400 dark:bg-orange-950/40",
  puzzle: "text-cyan-600 bg-cyan-50 dark:text-cyan-400 dark:bg-cyan-950/40",
  hate: "text-rose-600 bg-rose-50 dark:text-rose-400 dark:bg-rose-950/40",
  love: "text-pink-600 bg-pink-50 dark:text-pink-400 dark:bg-pink-950/40",
  neutral: "text-muted bg-surface-hover",
};

// 泳道配置
const LANE_META: { key: keyof TimelineData["lanes"]; label: string; icon: React.ReactNode; desc: string }[] = [
  { key: "characters", label: "角色出场", icon: <User size={12} aria-hidden="true" />, desc: "实体在章节中的出现与角色定位" },
  { key: "relationships", label: "关系变更", icon: <Link2 size={12} aria-hidden="true" />, desc: "角色/势力间关系的建立与变化" },
  { key: "foreshadows", label: "伏笔动态", icon: <Sparkles size={12} aria-hidden="true" />, desc: "伏笔埋设、推进与回收" },
  { key: "states", label: "状态变更", icon: <Activity size={12} aria-hidden="true" />, desc: "角色/地点/势力字段状态变化" },
  { key: "emotions", label: "情感弧线", icon: <Heart size={12} aria-hidden="true" />, desc: "角色情绪起伏与心理转变" },
];

// ==================== 组件 ====================

function EmptyTimeline() {
  return (
    <div className="flex flex-col items-center justify-center gap-2 py-16 text-muted">
      <MapPin size={32} aria-hidden="true" />
      <p className="text-sm">暂无时间线数据</p>
      <p className="text-xs">生成章节并提交后，角色出场、关系变化、伏笔动态等事件会自动汇聚到这里</p>
    </div>
  );
}

/** 单条事件行 */
function TimelineEventRow({ lane, item }: { lane: keyof TimelineData["lanes"]; item: TimelineLaneItem }) {
  const color = LANE_COLORS[lane] ?? LANE_COLORS.characters;

  const renderContent = () => {
    switch (lane) {
      case "characters":
        return (
          <span>
            <span className="font-medium text-foreground">{item.entity}</span>
            <span className="ml-1.5 rounded border border-border-strong bg-secondary px-1.5 py-0 text-[10px] text-muted">{item.role}</span>
            {item.snippet && <span className="ml-2 text-xs text-muted">{item.snippet}</span>}
          </span>
        );
      case "relationships":
        return (
          <span>
            <span className="font-medium text-foreground">{item.source}</span>
            <span className="mx-1 text-muted">—</span>
            <span className="font-medium text-foreground">{item.target}</span>
            <span className="ml-1.5 text-xs text-muted">[{item.field}]</span>
            {item.new_value && <span className="ml-1.5 text-xs text-emerald-500">→ {item.new_value}</span>}
            {item.reason && <span className="ml-2 text-xs text-muted">{item.reason}</span>}
          </span>
        );
      case "foreshadows":
        return (
          <span>
            <span className="font-medium text-foreground">{item.foreshadow_id}</span>
            {item.tier && <span className="ml-1.5 rounded border border-border-strong bg-secondary px-1.5 py-0 text-[10px] text-muted">{item.tier}</span>}
            <Badge
              className={`ml-1.5 px-1.5 py-0 text-[10px] ${
                item.event === "resolved" ? "bg-emerald-100 text-emerald-700 dark:bg-emerald-950/50 dark:text-emerald-400"
                : item.event === "planted" ? "bg-amber-100 text-amber-700 dark:bg-amber-950/50 dark:text-amber-400"
                : "bg-cyan-100 text-cyan-700 dark:bg-cyan-950/50 dark:text-cyan-400"
              }`}
            >
              {item.event === "resolved" ? "回收" : item.event === "planted" ? "埋设" : "推进"}
            </Badge>
            {item.description && <span className="ml-2 text-xs text-muted">{item.description}</span>}
          </span>
        );
      case "states":
        return (
          <span>
            <span className="font-medium text-foreground">{item.entity_type}·{item.entity_id}</span>
            <span className="ml-1.5 text-xs text-muted">{item.field}</span>
            {item.old_value && <span className="ml-1.5 text-xs text-muted line-through">{item.old_value}</span>}
            {item.new_value && <span className="ml-1.5 text-xs text-emerald-500">→ {item.new_value}</span>}
          </span>
        );
      case "emotions":
        return (
          <span className="flex items-center gap-1.5">
            <span className="font-medium text-foreground">{item.character}</span>
            {item.emotion_before && <span className="text-xs text-muted">{item.emotion_before}</span>}
            <span className="text-xs text-muted">→</span>
            {item.emotion_after && (
              <Badge className={`px-1.5 py-0 text-[10px] ${EMOTION_LABEL_STYLE[item.label] ?? EMOTION_LABEL_STYLE.neutral}`}>
                {item.emotion_after}
              </Badge>
            )}
            {item.event && <span className="ml-1.5 text-xs text-muted">{item.event}</span>}
          </span>
        );
      default:
        return null;
    }
  };

  return (
    <li className="group flex items-start gap-2 rounded-md px-2 py-1 transition-colors hover:bg-surface-hover">
      <span className={`mt-1.5 h-2 w-2 shrink-0 rounded-full ${color.dot}`} aria-hidden="true" />
      <span className="min-w-0 flex-1 text-xs leading-relaxed">{renderContent()}</span>
      <span className="shrink-0 text-[10px] text-muted">第{item.chapter}章</span>
    </li>
  );
}

/** 单条泳道 */
function Lane({
  laneKey,
  items,
  expanded,
  onToggle,
}: {
  laneKey: keyof TimelineData["lanes"];
  items: TimelineLaneItem[];
  expanded: boolean;
  onToggle: () => void;
}) {
  const meta = LANE_META.find((m) => m.key === laneKey)!;
  const color = LANE_COLORS[laneKey];

  return (
    <div className="overflow-hidden rounded-lg border border-border bg-surface-elevated">
      <button
        type="button"
        onClick={onToggle}
        className="flex w-full cursor-pointer items-center gap-2 px-3 py-2 text-left transition-colors hover:bg-surface-hover"
      >
        <span className={`flex h-5 w-5 items-center justify-center rounded ${color.badge}`}>
          {meta.icon}
        </span>
        <span className="text-xs font-semibold text-foreground">{meta.label}</span>
        <span className="rounded-full bg-surface-hover px-1.5 py-0.5 text-[10px] text-muted">{items.length}</span>
        <span className="min-w-0 flex-1 truncate text-[11px] text-muted">{meta.desc}</span>
        <span className="text-xs text-muted">{expanded ? "收起" : "展开"}</span>
      </button>
      {expanded && (
        <div className="border-t border-border">
          {items.length === 0 ? (
            <p className="px-3 py-3 text-xs text-muted">暂无记录</p>
          ) : (
            <ul className="max-h-64 space-y-0.5 overflow-y-auto p-1.5">
              {items.map((item, i) => (
                <TimelineEventRow key={`${laneKey}-${item.chapter}-${i}`} lane={laneKey} item={item} />
              ))}
            </ul>
          )}
        </div>
      )}
    </div>
  );
}

/** 章节轴 */
function ChapterAxis({ chapters, onJump }: { chapters: TimelineChapter[]; onJump?: (ch: number) => void }) {
  if (chapters.length === 0) return null;
  return (
    <div className="flex flex-wrap gap-1.5">
      {chapters.map((c) => (
        <button
          key={c.chapter}
          type="button"
          onClick={() => onJump?.(c.chapter)}
          title={c.title || `第${c.chapter}章`}
          className="group cursor-pointer rounded-md border border-border bg-surface-elevated px-2 py-1 text-center transition-colors hover:border-primary/50 hover:bg-surface-hover"
        >
          <div className="text-[10px] font-bold text-foreground">第{c.chapter}章</div>
          {c.title && <div className="max-w-[80px] truncate text-[10px] text-muted group-hover:text-foreground">{c.title}</div>}
          {c.word_count > 0 && <div className="text-[9px] text-muted">{c.word_count}字</div>}
        </button>
      ))}
    </div>
  );
}

// ==================== 主视图 ====================

export function TimelineView() {
  const project = useAppStore((s) => s.currentProject);
  const { showError } = useToast();

  const [data, setData] = useState<TimelineData | null>(null);
  const [loading, setLoading] = useState(true);
  const [expanded, setExpanded] = useState<Record<string, boolean>>({
    characters: true,
    relationships: false,
    foreshadows: true,
    states: false,
    emotions: false,
  });
  const [filterChapter, setFilterChapter] = useState<number | null>(null);

  const load = useCallback(async () => {
    if (!project) return;
    setLoading(true);
    try {
      const res = await fetch(`/api/timeline/${project.id}`);
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      const json = (await res.json()) as TimelineData;
      setData(json);
    } catch (e: any) {
      showError("加载时间线失败：" + e.message);
    } finally {
      setLoading(false);
    }
  }, [project, showError]);

  useEffect(() => {
    void load();
  }, [load]);

  const filtered = useMemo(() => {
    if (!data || filterChapter === null) return data;
    return {
      ...data,
      lanes: {
        characters: data.lanes.characters.filter((i) => i.chapter === filterChapter),
        relationships: data.lanes.relationships.filter((i) => i.chapter === filterChapter),
        foreshadows: data.lanes.foreshadows.filter((i) => i.chapter === filterChapter),
        states: data.lanes.states.filter((i) => i.chapter === filterChapter),
        emotions: data.lanes.emotions.filter((i) => i.chapter === filterChapter),
      },
      events: data.events.filter((i) => i.chapter === filterChapter),
    };
  }, [data, filterChapter]);

  if (!project) {
    return <div className="flex h-full items-center justify-center text-muted">请先选择一个项目</div>;
  }

  const toggleLane = (key: string) => setExpanded((prev) => ({ ...prev, [key]: !prev[key] }));

  return (
    <div className="space-y-6 p-6">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold">故事时间线</h1>
          <p className="mt-1 text-sm text-muted">按章节聚合角色出场、关系变化、伏笔动态、状态变更与情感弧线</p>
        </div>
        <Button variant="outline" onClick={load} disabled={loading}>
          <RefreshCw size={14} className={`mr-1.5 ${loading ? "animate-spin" : ""}`} aria-hidden="true" />
          刷新
        </Button>
      </div>

      {loading && !data ? (
        <div className="flex items-center justify-center py-20 text-muted">
          <RefreshCw size={16} className="mr-2 animate-spin" aria-hidden="true" />
          正在加载时间线...
        </div>
      ) : !data ? (
        <Card>
          <CardContent className="py-8">
            <EmptyTimeline />
          </CardContent>
        </Card>
      ) : (
        <>
          {/* 章节轴 */}
          <Card>
            <CardHeader className="pb-2">
              <CardTitle className="flex items-center gap-2 text-sm">
                <Users size={14} aria-hidden="true" />
                章节导航
                {filterChapter !== null && (
                  <button
                    type="button"
                    onClick={() => setFilterChapter(null)}
                    className="cursor-pointer text-xs text-primary hover:underline"
                  >
                    清除筛选（当前：第{filterChapter}章）
                  </button>
                )}
              </CardTitle>
            </CardHeader>
            <CardContent>
              <ChapterAxis chapters={data.chapters} onJump={setFilterChapter} />
              {data.chapters.length === 0 && (
                <p className="text-xs text-muted">暂无章节摘要数据，章节提交后会自动生成摘要</p>
              )}
            </CardContent>
          </Card>

          {/* 事件概览 */}
          <Card>
            <CardHeader className="pb-2">
              <CardTitle className="text-sm">事件概览</CardTitle>
            </CardHeader>
            <CardContent>
              <div className="grid grid-cols-3 gap-3 sm:grid-cols-6">
                {[
                  { label: "角色出场", value: data.counts.characters, color: "text-blue-500" },
                  { label: "关系变更", value: data.counts.relationships, color: "text-purple-500" },
                  { label: "伏笔动态", value: data.counts.foreshadows, color: "text-amber-500" },
                  { label: "状态变更", value: data.counts.states, color: "text-cyan-500" },
                  { label: "情感弧线", value: data.counts.emotions, color: "text-pink-500" },
                  { label: "通用事件", value: data.counts.events, color: "text-muted" },
                ].map((s) => (
                  <div key={s.label} className="rounded-lg border border-border bg-surface p-3 text-center">
                    <div className={`text-xl font-bold ${s.color}`}>{s.value}</div>
                    <div className="mt-0.5 text-[11px] text-muted">{s.label}</div>
                  </div>
                ))}
              </div>
            </CardContent>
          </Card>

          {/* 泳道 */}
          <div className="space-y-2">
            {LANE_META.map((meta) => (
              <Lane
                key={meta.key}
                laneKey={meta.key}
                items={filtered?.lanes[meta.key] ?? []}
                expanded={expanded[meta.key]}
                onToggle={() => toggleLane(meta.key)}
              />
            ))}
          </div>
        </>
      )}
    </div>
  );
}
