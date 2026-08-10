import { useCallback, useEffect, useState } from "react";
import { BookMarked, ChevronRight, Crown, Loader2, MapPin, RotateCcw, User, Users, X } from "lucide-react";
import { Badge } from "@/components/ui/badge";
import { useToast } from "@/hooks/useToast";
import { cn } from "@/lib/utils";
import { ENTITY_TYPE_META, FORESHADOW_STATUS_LABEL } from "./entity-meta";

// ==================== 类型定义 ====================

export type EntityCardType = "character" | "faction" | "monster" | "foreshadow" | "location";

export interface EntityCardData {
  entity_type: EntityCardType;
  entity_id: string;
  entity: Record<string, any>;
  relations: any[];
  appearances: { chapter: number; role_in_chapter: string; context_snippet: string }[];
  foreshadows?: { foreshadow_id: string; tier: string; status: string; description: string; plant_chapter: number }[];
  children?: any[];
  // 命名权威（P4）：已合并别名 + 安全别名候选
  name_overrides?: { id: number; alias: string; note: string }[];
  alias_candidates?: string[];
}

interface EntityCardDrawerProps {
  open: boolean;
  onClose: () => void;
  projectId: number;
  entityType: EntityCardType;
  entityId: string;
  onJumpToChapter?: (chapter: number) => void;
}

// ==================== 辅助组件 ====================

/** 字段展示行（标题 + 值） */
function Field({ label, value, emptyText = "—" }: { label: string; value?: string | number | null; emptyText?: string }) {
  if (!value) return null;
  return (
    <div className="space-y-0.5">
      <div className="text-[10px] font-medium uppercase tracking-wide text-muted">{label}</div>
      <div className="whitespace-pre-wrap text-xs leading-relaxed text-foreground">{String(value) || emptyText}</div>
    </div>
  );
}

/** 出场章节标记 */
function ChapterMark({ chapter, role, onJump }: { chapter: number; role?: string; onJump?: (ch: number) => void }) {
  return (
    <button
      type="button"
      onClick={() => onJump?.(chapter)}
      className="inline-flex cursor-pointer items-center gap-1 rounded-md border border-border bg-surface-hover px-1.5 py-0.5 text-[10px] text-muted transition-colors hover:border-primary/50 hover:text-primary"
      title={role ? `第${chapter}章 · ${role}` : `第${chapter}章`}
    >
      <ChevronRight size={9} aria-hidden="true" />
      第{chapter}章
      {role && <span className="text-muted">· {role}</span>}
    </button>
  );
}

/** 关系条目 */
function RelationRow({ rel, type }: { rel: any; type: EntityCardType }) {
  if (type === "location") {
    return (
      <li className="flex items-center gap-1.5 rounded-md px-2 py-1 text-xs hover:bg-surface-hover">
        <span className="text-cyan-500">{rel.source}</span>
        <span className="text-[10px] text-muted">—{rel.relation_type}→</span>
        <span className="text-cyan-500">{rel.target}</span>
        {rel.distance && <span className="text-[10px] text-muted">({rel.distance})</span>}
      </li>
    );
  }
  return (
    <li className="flex items-center gap-1.5 rounded-md px-2 py-1 text-xs hover:bg-surface-hover">
      <span className="font-medium text-foreground">{rel.source}</span>
      <span className="text-[10px] text-muted">—{rel.relation_type}→</span>
      <span className="font-medium text-foreground">{rel.target}</span>
      {rel.strength ? <span className="text-[10px] text-muted">强度{rel.strength}</span> : null}
      {rel.status === "inactive" && <Badge className="px-1.5 py-0 text-[9px]">已失效</Badge>}
      {rel.description && <span className="ml-1 truncate text-[10px] text-muted">{rel.description}</span>}
    </li>
  );
}

// ==================== 卡片主体 ====================

/** 别名修正区（命名权威 P4）：安全候选合并 + "我的修正"回滚 */
function AliasSection({
  candidates,
  overrides,
  onMerge,
  onRollback,
  busy,
}: {
  candidates: string[];
  overrides: { id: number; alias: string; note: string }[];
  onMerge: (alias: string) => void;
  onRollback: (overrideId: number) => void;
  busy: boolean;
}) {
  if (candidates.length === 0 && overrides.length === 0) return null;
  return (
    <div className="space-y-2 rounded-lg border border-border bg-surface/50 p-2.5">
      <div className="flex items-center gap-1 text-[10px] font-medium uppercase tracking-wide text-muted">
        <User size={10} aria-hidden="true" /> 别名修正
      </div>

      {overrides.length > 0 && (
        <div>
          <div className="mb-1 text-[10px] text-muted">已合并（可回滚）</div>
          <ul className="space-y-1">
            {overrides.map((o) => (
              <li key={o.id} className="flex items-center gap-1.5">
                <Badge className="bg-cyan-100 px-1.5 py-0 text-[10px] text-cyan-700 dark:bg-cyan-950/50 dark:text-cyan-400">
                  {o.alias}
                </Badge>
                {o.note && <span className="truncate text-[10px] text-muted">{o.note}</span>}
                <button
                  type="button"
                  onClick={() => onRollback(o.id)}
                  disabled={busy}
                  className="ml-auto flex cursor-pointer items-center gap-0.5 rounded px-1 py-0.5 text-[10px] text-muted transition-colors hover:bg-surface-hover hover:text-foreground disabled:opacity-50"
                  title="回滚该别名合并"
                >
                  <RotateCcw size={9} aria-hidden="true" /> 回滚
                </button>
              </li>
            ))}
          </ul>
        </div>
      )}

      {candidates.length > 0 && (
        <div>
          <div className="mb-1 text-[10px] text-muted">安全别名候选（确认是同一人则合并）</div>
          <div className="flex flex-wrap gap-1">
            {candidates.map((alias) => (
              <button
                key={alias}
                type="button"
                onClick={() => onMerge(alias)}
                disabled={busy}
                className="inline-flex cursor-pointer items-center gap-1 rounded-md border border-border bg-surface-hover px-1.5 py-0.5 text-[10px] text-muted transition-colors hover:border-primary/50 hover:text-primary disabled:opacity-50"
                title={`将「${alias}」合并到规范名`}
              >
                + {alias}
              </button>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}

function CharacterCardBody({ data, onJump, onMergeAlias, onRollbackAlias, aliasBusy }: {
  data: EntityCardData;
  onJump?: (ch: number) => void;
  onMergeAlias: (alias: string) => void;
  onRollbackAlias: (overrideId: number) => void;
  aliasBusy: boolean;
}) {
  const e = data.entity;
  return (
    <div className="space-y-3">
      <div className="flex items-center gap-2">
        <Badge className={e.role === "主角" ? "bg-primary-muted text-primary" : "bg-secondary text-muted"}>
          {e.role || "角色"}
        </Badge>
        {e.importance && <Badge className="bg-secondary text-muted">{e.importance}</Badge>}
        {e.current_emotion && <Badge className="bg-pink-100 text-pink-700 dark:bg-pink-950/50 dark:text-pink-400">心情：{e.current_emotion}</Badge>}
      </div>
      <div className="grid grid-cols-2 gap-2">
        <Field label="年龄" value={e.age} />
        <Field label="性别" value={e.gender} />
      </div>
      <Field label="当前所在" value={e.current_location} />
      <Field label="外貌" value={e.appearance} />
      <Field label="性格" value={e.personality} />
      <Field label="动机" value={e.motivation} />
      <Field label="背景" value={e.background} />
      <Field label="核心矛盾" value={e.core_contradiction} />
      <Field label="绝对禁忌" value={e.absolute_taboos} />
      <Field label="角色弧线" value={e.arc} />
      <Field label="秘密" value={e.secrets} />
      <Field label="语言风格" value={e.language_style} />
      <Field label="战斗风格" value={e.combat_style} />

      <AliasSection
        candidates={data.alias_candidates ?? []}
        overrides={data.name_overrides ?? []}
        onMerge={onMergeAlias}
        onRollback={onRollbackAlias}
        busy={aliasBusy}
      />

      {data.relations && data.relations.length > 0 && (
        <div>
          <div className="mb-1 flex items-center gap-1 text-[10px] font-medium uppercase tracking-wide text-muted">
            <Users size={10} aria-hidden="true" /> 关系（{data.relations.length}）
          </div>
          <ul className="space-y-0.5">
            {data.relations.map((r) => <RelationRow key={r.id} rel={r} type="character" />)}
          </ul>
        </div>
      )}

      {data.foreshadows && data.foreshadows.length > 0 && (
        <div>
          <div className="mb-1 flex items-center gap-1 text-[10px] font-medium uppercase tracking-wide text-muted">
            <BookMarked size={10} aria-hidden="true" /> 相关伏笔（{data.foreshadows.length}）
          </div>
          <ul className="space-y-0.5">
            {data.foreshadows.map((f, i) => (
              <li key={i} className="flex items-center gap-1.5 px-2 py-1 text-xs">
                <span className="font-medium text-foreground">{f.foreshadow_id}</span>
                <Badge className={`px-1.5 py-0 text-[9px] ${FORESHADOW_STATUS_LABEL[f.status]?.cls ?? ""}`}>
                  {FORESHADOW_STATUS_LABEL[f.status]?.text ?? f.status}
                </Badge>
                <span className="truncate text-[10px] text-muted">{f.description}</span>
              </li>
            ))}
          </ul>
        </div>
      )}

      {data.appearances && data.appearances.length > 0 && (
        <div>
          <div className="mb-1 text-[10px] font-medium uppercase tracking-wide text-muted">
            出场章节（{data.appearances.length}）
          </div>
          <div className="flex flex-wrap gap-1">
            {data.appearances.map((a, i) => (
              <ChapterMark key={i} chapter={a.chapter} role={a.role_in_chapter} onJump={onJump} />
            ))}
          </div>
        </div>
      )}
    </div>
  );
}

function FactionCardBody({ data }: { data: EntityCardData }) {
  const e = data.entity;
  return (
    <div className="space-y-3">
      <div className="flex items-center gap-2">
        {e.tier && <Badge className="bg-purple-100 text-purple-700 dark:bg-purple-950/50 dark:text-purple-400">{e.tier}</Badge>}
        {e.alignment && <Badge className="bg-secondary text-muted">{e.alignment}</Badge>}
      </div>
      <Field label="别名" value={e.alias} />
      <Field label="类型" value={e.type} />
      <Field label="描述" value={e.description} />
      <Field label="历史" value={e.history} />
      <Field label="目标" value={e.goals} />
      <Field label="组织架构" value={e.hierarchy} />
      <Field label="领地" value={e.territories} />
      <Field label="资源" value={e.resources} />
      {data.relations && data.relations.length > 0 && (
        <div>
          <div className="mb-1 text-[10px] font-medium uppercase tracking-wide text-muted">势力关系（{data.relations.length}）</div>
          <ul className="space-y-0.5">
            {data.relations.map((r) => <RelationRow key={r.id} rel={r} type="faction" />)}
          </ul>
        </div>
      )}
    </div>
  );
}

function MonsterCardBody({ data, onJump }: { data: EntityCardData; onJump?: (ch: number) => void }) {
  const e = data.entity;
  return (
    <div className="space-y-3">
      <div className="flex items-center gap-2">
        {e.tier && <Badge className="bg-red-100 text-red-700 dark:bg-red-950/50 dark:text-red-400">{e.tier}</Badge>}
        {e.species && <Badge className="bg-secondary text-muted">{e.species}</Badge>}
      </div>
      <Field label="别名" value={e.alias} />
      <Field label="等级" value={e.rank} />
      <Field label="属性" value={e.attributes} />
      <Field label="技能" value={e.skills} />
      <Field label="弱点" value={e.weaknesses} />
      <Field label="栖息地" value={e.habitats} />
      <Field label="行为模式" value={e.behavior} />
      <Field label="掉落" value={e.drops} />
      <Field label="背景故事" value={e.lore} />
      {e.first_appearance > 0 && (
        <div>
          <div className="mb-1 text-[10px] font-medium uppercase tracking-wide text-muted">首次出场</div>
          <ChapterMark chapter={e.first_appearance} onJump={onJump} />
        </div>
      )}
      {data.appearances && data.appearances.length > 0 && (
        <div>
          <div className="mb-1 text-[10px] font-medium uppercase tracking-wide text-muted">出场章节（{data.appearances.length}）</div>
          <div className="flex flex-wrap gap-1">
            {data.appearances.map((a, i) => (
              <ChapterMark key={i} chapter={a.chapter} role={a.role_in_chapter} onJump={onJump} />
            ))}
          </div>
        </div>
      )}
    </div>
  );
}

function ForeshadowCardBody({ data }: { data: EntityCardData }) {
  const e = data.entity;
  return (
    <div className="space-y-3">
      <div className="flex items-center gap-2">
        <Badge className={`px-2 py-0.5 text-[10px] ${FORESHADOW_STATUS_LABEL[e.status]?.cls ?? ""}`}>
          {FORESHADOW_STATUS_LABEL[e.status]?.text ?? e.status}
        </Badge>
        {e.tier && <Badge className="bg-secondary text-muted">{e.tier === "short" ? "短伏笔" : e.tier === "medium" ? "中伏笔" : "长伏笔"}</Badge>}
      </div>
      <Field label="描述" value={e.description} />
      <div className="grid grid-cols-2 gap-2">
        <div>
          <div className="mb-1 text-[10px] font-medium uppercase tracking-wide text-muted">埋设章节</div>
          {e.plant_chapter > 0 ? <ChapterMark chapter={e.plant_chapter} /> : <span className="text-xs text-muted">未指定</span>}
        </div>
        <div>
          <div className="mb-1 text-[10px] font-medium uppercase tracking-wide text-muted">计划回收章节</div>
          {e.planned_resolve_chapter > 0 ? <ChapterMark chapter={e.planned_resolve_chapter} /> : <span className="text-xs text-muted">未指定</span>}
        </div>
      </div>
      <Field label="依赖伏笔" value={e.depends_on} />
    </div>
  );
}

function LocationCardBody({ data, onJump }: { data: EntityCardData; onJump?: (ch: number) => void }) {
  const e = data.entity;
  const unlocked = e.unlocked_chapter || 0;
  return (
    <div className="space-y-3">
      <div className="flex flex-wrap items-center gap-2">
        {e.tier && <Badge className="bg-cyan-100 text-cyan-700 dark:bg-cyan-950/50 dark:text-cyan-400">{e.tier}</Badge>}
        {e.layer && <Badge className="bg-secondary text-muted">{e.layer}</Badge>}
        {e.importance && <Badge className="bg-secondary text-muted">{e.importance}</Badge>}
        {unlocked > 0 ? (
          <Badge className="bg-emerald-100 text-emerald-700 dark:bg-emerald-950/50 dark:text-emerald-400">
            第{unlocked}章解锁
          </Badge>
        ) : (
          <Badge className="bg-secondary text-muted">未解锁</Badge>
        )}
      </div>
      <Field label="城主/掌管者" value={e.ruler} />
      <Field label="剧情作用" value={e.plot_role} />
      <Field label="描述" value={e.description} />
      <div className="grid grid-cols-2 gap-2">
        <Field label="上级地点" value={e.parent_name} />
        <Field label="坐标" value={e.coord_x !== null && e.coord_y !== null ? `(${e.coord_x}, ${e.coord_y})` : null} />
      </div>

      {data.children && data.children.length > 0 && (
        <div>
          <div className="mb-1 text-[10px] font-medium uppercase tracking-wide text-muted">子地点（{data.children.length}）</div>
          <div className="flex flex-wrap gap-1">
            {data.children.map((c) => (
              <span key={c.id} className="inline-flex items-center gap-1 rounded-md bg-surface-hover px-1.5 py-0.5 text-[10px] text-muted">
                <MapPin size={9} aria-hidden="true" /> {c.name}
              </span>
            ))}
          </div>
        </div>
      )}

      {data.relations && data.relations.length > 0 && (
        <div>
          <div className="mb-1 text-[10px] font-medium uppercase tracking-wide text-muted">地点关系（{data.relations.length}）</div>
          <ul className="space-y-0.5">
            {data.relations.map((r) => <RelationRow key={r.id} rel={r} type="location" />)}
          </ul>
        </div>
      )}
      {onJump && <span className="hidden" />}
    </div>
  );
}

function CardBody({ data, onJump, onMergeAlias, onRollbackAlias, aliasBusy }: {
  data: EntityCardData;
  onJump?: (ch: number) => void;
  onMergeAlias: (alias: string) => void;
  onRollbackAlias: (overrideId: number) => void;
  aliasBusy: boolean;
}) {
  switch (data.entity_type) {
    case "character":
      return <CharacterCardBody data={data} onJump={onJump} onMergeAlias={onMergeAlias} onRollbackAlias={onRollbackAlias} aliasBusy={aliasBusy} />;
    case "faction": return <FactionCardBody data={data} />;
    case "monster": return <MonsterCardBody data={data} onJump={onJump} />;
    case "foreshadow": return <ForeshadowCardBody data={data} />;
    case "location": return <LocationCardBody data={data} onJump={onJump} />;
    default: return null;
  }
}

// ==================== 抽屉主组件 ====================

export function EntityCardDrawer({ open, onClose, projectId, entityType, entityId, onJumpToChapter }: EntityCardDrawerProps) {
  const [data, setData] = useState<EntityCardData | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [aliasBusy, setAliasBusy] = useState(false);
  const { showError } = useToast();

  const meta = ENTITY_TYPE_META[entityType];

  const load = useCallback(async () => {
    if (!open || !entityId) return;
    setLoading(true);
    setError(null);
    try {
      const res = await fetch(`/api/entity-cards/${projectId}/${entityType}/${encodeURIComponent(entityId)}`);
      if (!res.ok) {
        const body = await res.json().catch(() => null);
        throw new Error(body?.detail || `HTTP ${res.status}`);
      }
      setData((await res.json()) as EntityCardData);
    } catch (e: any) {
      setError(e.message || "加载失败");
      setData(null);
    } finally {
      setLoading(false);
    }
  }, [open, projectId, entityType, entityId]);

  /** 合并别名：alias 归并到规范名 canonical_name 下 */
  const handleMergeAlias = useCallback(async (alias: string) => {
    if (!data || aliasBusy) return;
    setAliasBusy(true);
    try {
      const res = await fetch(`/api/bible/${projectId}/name-overrides`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ entity_type: "character", canonical_name: entityId, alias }),
      });
      if (!res.ok) {
        const body = await res.json().catch(() => null);
        throw new Error(body?.detail || `HTTP ${res.status}`);
      }
      const created = (await res.json()) as { id: number; alias: string; note: string };
      setData({
        ...data,
        name_overrides: [...(data.name_overrides ?? []), created],
        alias_candidates: (data.alias_candidates ?? []).filter((a) => a !== alias),
      });
    } catch (e: any) {
      showError("合并失败：" + (e.message || "未知错误"));
    } finally {
      setAliasBusy(false);
    }
  }, [data, aliasBusy, projectId, entityId, showError]);

  /** 回滚合并：删除别名修正记录 */
  const handleRollbackAlias = useCallback(async (overrideId: number) => {
    if (!data || aliasBusy) return;
    setAliasBusy(true);
    try {
      const res = await fetch(`/api/bible/${projectId}/name-overrides/${overrideId}`, { method: "DELETE" });
      if (!res.ok) {
        const body = await res.json().catch(() => null);
        throw new Error(body?.detail || `HTTP ${res.status}`);
      }
      const removed = (data.name_overrides ?? []).find((o) => o.id === overrideId);
      setData({
        ...data,
        name_overrides: (data.name_overrides ?? []).filter((o) => o.id !== overrideId),
        alias_candidates: removed ? [...(data.alias_candidates ?? []), removed.alias].sort() : data.alias_candidates,
      });
    } catch (e: any) {
      showError("回滚失败：" + (e.message || "未知错误"));
    } finally {
      setAliasBusy(false);
    }
  }, [data, aliasBusy, projectId, showError]);

  useEffect(() => {
    if (open) void load();
    else setData(null);
  }, [open, load]);

  useEffect(() => {
    if (!open) return;
    const handler = (e: KeyboardEvent) => {
      if (e.key === "Escape") onClose();
    };
    window.addEventListener("keydown", handler);
    return () => window.removeEventListener("keydown", handler);
  }, [open, onClose]);

  if (!open) return null;

  return (
    <div className="fixed inset-0 z-50 flex justify-end" role="dialog" aria-label={`${meta.label}详情`}>
      {/* 遮罩 */}
      <div
        className="absolute inset-0 bg-foreground/40 backdrop-blur-[2px]"
        onClick={onClose}
        aria-hidden="true"
      />
      {/* 抽屉 */}
      <div className="relative flex h-full w-full max-w-md flex-col border-l border-border bg-surface-elevated shadow-2xl animate-in slide-in-from-right duration-200">
        {/* 头部 */}
        <div className="flex items-center gap-2 border-b border-border px-4 py-3">
          <span className={cn("flex h-7 w-7 items-center justify-center rounded-lg bg-surface-hover", meta.color)}>
            {meta.icon}
          </span>
          <div className="min-w-0 flex-1">
            <h3 className="truncate text-sm font-semibold text-foreground">{entityId}</h3>
            <span className="text-[10px] text-muted">{meta.label}卡片</span>
          </div>
          <button
            type="button"
            onClick={onClose}
            aria-label="关闭"
            className="flex h-7 w-7 cursor-pointer items-center justify-center rounded-md text-muted transition-colors hover:bg-surface-hover hover:text-foreground"
          >
            <X size={16} aria-hidden="true" />
          </button>
        </div>

        {/* 内容 */}
        <div className="flex-1 overflow-y-auto p-4">
          {loading ? (
            <div className="flex items-center justify-center py-16 text-muted">
              <Loader2 size={18} className="mr-2 animate-spin" aria-hidden="true" />
              加载中...
            </div>
          ) : error ? (
            <div className="flex flex-col items-center gap-2 py-16 text-muted">
              <Crown size={24} className="opacity-40" aria-hidden="true" />
              <p className="text-sm">{error}</p>
              <button type="button" onClick={load} className="cursor-pointer text-xs text-primary hover:underline">
                重试
              </button>
            </div>
          ) : data ? (
            <CardBody
              data={data}
              onJump={onJumpToChapter}
              onMergeAlias={handleMergeAlias}
              onRollbackAlias={handleRollbackAlias}
              aliasBusy={aliasBusy}
            />
          ) : null}
        </div>
      </div>
    </div>
  );
}
