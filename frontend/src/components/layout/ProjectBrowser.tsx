import { useState } from "react";
import { useNavigate } from "react-router-dom";
import { useAppStore } from "@/store";
import { api } from "@/api";
import { bumpDataVersion } from "@/store/slices/dataVersion";
import { useToast } from "@/hooks/useToast";
import { useConfirmDialog } from "@/hooks/useConfirmDialog";
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
  const { showSuccess, showError } = useToast();
  const { confirm: confirmDelete, dialog: deleteDialog } = useConfirmDialog();
  const [expanded, setExpanded] = useState<Record<CategoryKey, boolean>>({
    outline: true,
    characters: false,
    world: false,
    foreshadows: false,
    factions: false,
  });
  // 章节批量删除模式
  const [selectMode, setSelectMode] = useState(false);
  const [selected, setSelected] = useState<Set<number>>(new Set());
  const [deleting, setDeleting] = useState(false);

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

  const toggleSelect = (chapter: number) => {
    setSelected((prev) => {
      const next = new Set(prev);
      if (next.has(chapter)) next.delete(chapter);
      else next.add(chapter);
      return next;
    });
  };

  const toggleSelectAll = () => {
    if (selected.size === chapters.length) setSelected(new Set());
    else setSelected(new Set(chapters.map((c) => c.chapter)));
  };

  const handleBatchDelete = async () => {
    if (!projectId || selected.size === 0) return;
    const ok = await confirmDelete({
      title: "批量删除章节",
      description: `将删除 ${selected.size} 章正文及其摘要、出场记录等关联数据，此操作不可恢复。`,
      confirmText: "确认删除",
      cancelText: "取消",
      variant: "danger",
    });
    if (!ok) return;
    setDeleting(true);
    try {
      const ids = Array.from(selected).sort((a, b) => a - b);
      const r = await api.batchDeleteChapters(projectId, ids);
      setSelected(new Set());
      setSelectMode(false);
      await Promise.all([useAppStore.getState().refreshChapters(), useAppStore.getState().refreshAssets()]);
      bumpDataVersion("chapters");
      bumpDataVersion("bible");
      showSuccess(
        r.deleted_count > 0
          ? `已删除 ${r.deleted_count} 章` + (r.failed.length > 0 ? `，失败 ${r.failed.length} 章` : "")
          : "没有章节被删除",
      );
    } catch (e: any) {
      showError("批量删除失败：" + e.message);
    } finally {
      setDeleting(false);
    }
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
                <>
                  <div className="flex items-center gap-1 px-2 py-1">
                    <button
                      type="button"
                      onClick={() => { setSelectMode((v) => !v); setSelected(new Set()); }}
                      className="rounded px-1.5 py-0.5 text-[10px] text-muted hover:bg-foreground/5 hover:text-foreground"
                    >
                      {selectMode ? "退出批量" : "批量删除"}
                    </button>
                    {selectMode && (
                      <>
                        <button
                          type="button"
                          onClick={toggleSelectAll}
                          className="rounded px-1.5 py-0.5 text-[10px] text-muted hover:bg-foreground/5 hover:text-foreground"
                        >
                          {selected.size === chapters.length ? "取消全选" : "全选"}
                        </button>
                        {selected.size > 0 && (
                          <button
                            type="button"
                            onClick={() => void handleBatchDelete()}
                            disabled={deleting}
                            className="rounded px-1.5 py-0.5 text-[10px] text-danger hover:bg-danger/10 disabled:opacity-50"
                          >
                            {deleting ? "删除中…" : `删除选中(${selected.size})`}
                          </button>
                        )}
                      </>
                    )}
                  </div>
                  {chapters.map((chapter) => (
                    <TreeItem
                      key={chapter.chapter}
                      label={
                        selectMode ? (
                          <span className="flex items-center gap-1.5">
                            <input
                              type="checkbox"
                              checked={selected.has(chapter.chapter)}
                              onChange={() => toggleSelect(chapter.chapter)}
                              onClick={(e) => e.stopPropagation()}
                              className="h-3 w-3 rounded border-border-strong"
                            />
                            <span className="truncate">{chapter.title || `第${chapter.chapter}章`}</span>
                          </span>
                        ) : (
                          chapter.title || `第${chapter.chapter}章`
                        )
                      }
                      depth={1}
                      onClick={
                        selectMode
                          ? () => toggleSelect(chapter.chapter)
                          : onOpenChapter
                            ? () => onOpenChapter(chapter.chapter, chapter.title)
                            : undefined
                      }
                    />
                  ))}
                </>
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
      {deleteDialog}
    </div>
  );
}
