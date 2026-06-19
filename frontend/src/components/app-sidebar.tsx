import { useState } from "react";
import { Globe, LayoutDashboard, List, Route, ScrollText, Users, Download, FileText, Search, ChevronDown, Shield, Network, Skull, Settings, Trash2 } from "lucide-react";
import type { Project, Character, Foreshadow, Outline, WorldSetting, ChapterListItem, ChapterText, AssetType, Faction, FactionRelationship, CharacterRelationship, Monster } from "@/types";
import { CreateProjectDialog } from "@/components/create-project-dialog";
import { SidebarSection, SidebarGroup, SidebarItem, VirtualList } from "@/components/sidebar";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { ConfirmDialog } from "@/components/confirm-dialog";
import { api } from "@/api";
import { useToast } from "@/hooks/useToast";

type Tab = "dashboard" | "planning" | "world" | "characters" | "outlines-volume" | "outlines-arc" | "outlines-chapter" | "asset" | "chapter" | "summaries" | "import" | "export" | "factions" | "relationships" | "monsters" | "settings";

interface AppSidebarProps {
  projects: Project[];
  currentProject: Project | null;
  projectSearch: string;
  setProjectSearch: (v: string) => void;
  onSelectProject: (id: number) => void;
  onCreateProject: (title: string, genre: string, summary: string, templateKey: string) => void;
  onDeleteProject: () => void;
  activeTab: Tab;
  setActiveTab: (tab: Tab) => void;
  selectedAsset: { type: AssetType; id: string } | null;
  onSelectAsset: (type: AssetType, id: string, data?: Character | Foreshadow | Outline | ChapterText | Faction | FactionRelationship | CharacterRelationship | Monster) => void;
  onCreateAsset: (type: AssetType) => void;
  characters: Character[];
  foreshadows: Foreshadow[];
  outlines: Outline[];
  chapters: ChapterListItem[];
  worldSettings: WorldSetting[];
  factions: Faction[];
  factionRelationships: FactionRelationship[];
  characterRelationships: CharacterRelationship[];
  monsters: Monster[];
}

export function AppSidebar({
  projects,
  currentProject,
  projectSearch,
  setProjectSearch,
  onSelectProject,
  onCreateProject,
  onDeleteProject,
  activeTab,
  setActiveTab,
  selectedAsset,
  onSelectAsset,
  onCreateAsset,
  characters,
  foreshadows,
  outlines,
  chapters,
  worldSettings,
  factions,
  factionRelationships,
  characterRelationships,
  monsters,
}: AppSidebarProps) {
  const { showError, showSuccess } = useToast();
  const [deleteDialogOpen, setDeleteDialogOpen] = useState(false);
  const [outlinesOpen, setOutlinesOpen] = useState(true);
  const [batchDeleteOpen, setBatchDeleteOpen] = useState(false);
  const [selectedIds, setSelectedIds] = useState<Set<number>>(new Set());

  const toggleSelect = (id: number) => {
    setSelectedIds((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  };

  const handleBatchDelete = async () => {
    try {
      const ids = Array.from(selectedIds);
      const r = await api.batchDeleteProjects(ids);
      showSuccess(`已删除 ${r.count} 个项目`);
      setBatchDeleteOpen(false);
      setSelectedIds(new Set());
      window.location.reload();
    } catch (e: any) {
      showError("批量删除失败：" + e.message);
    }
  };

  const selectChapter = async (chapter: number) => {
    try {
      if (!currentProject) return;
      const ct = await api.getChapterText(currentProject.id, chapter);
      onSelectAsset("chapter", String(chapter), ct);
    } catch (e: any) {
      showError("加载章节失败：" + e.message);
    }
  };

  return (
    <div className="w-full h-full flex flex-col gap-3">
      <Card className="flex flex-col h-full overflow-hidden">
        <CardHeader className="pb-2">
          <div className="flex items-center justify-between">
            <CardTitle className="text-sm font-bold">项目</CardTitle>
            <CreateProjectDialog onCreate={onCreateProject} />
          </div>
        </CardHeader>
        <CardContent className="flex-1 overflow-y-auto p-0 px-3 space-y-2">
          <div className="relative">
            <Search className="absolute left-3 top-1/2 -translate-y-1/2 h-3.5 w-3.5 text-muted" />
            <input
              type="text"
              placeholder="搜索项目…"
              value={projectSearch}
              onChange={(e) => setProjectSearch(e.target.value)}
              className="w-full h-9 pl-8 pr-3 rounded-xl border border-border-strong bg-surface text-sm text-foreground placeholder:text-muted focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary/50"
            />
          </div>

          <div className="flex gap-1">
            <div className="relative flex-1">
              <select
                value={currentProject ? String(currentProject.id) : ""}
                onChange={(e) => onSelectProject(Number(e.target.value))}
                className="w-full h-10 appearance-none rounded-xl border border-border-strong bg-surface px-3 pr-8 text-sm text-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary/50 cursor-pointer hover:border-border transition-colors"
              >
                <option value="">选择项目</option>
                {projects
                  .filter((p) => p.title.toLowerCase().includes(projectSearch.toLowerCase()))
                  .slice(0, 100)
                  .map((p) => (
                    <option key={p.id} value={p.id}>{p.title}</option>
                  ))}
                {projects.filter((p) => p.title.toLowerCase().includes(projectSearch.toLowerCase())).length > 100 && (
                  <option value="" disabled>…还有更多项目，请使用搜索</option>
                )}
              </select>
              <ChevronDown className="absolute right-3 top-1/2 -translate-y-1/2 h-3.5 w-3.5 text-muted pointer-events-none" />
            </div>
            <Button
              size="sm"
              variant="ghost"
              className="h-10 px-2 shrink-0"
              title="批量管理项目"
              onClick={() => setBatchDeleteOpen(!batchDeleteOpen)}
            >
              <Trash2 className="h-4 w-4" />
            </Button>
          </div>

          {batchDeleteOpen && (
            <div className="space-y-2">
              <div className="flex items-center justify-between text-xs text-muted">
                <span>勾选要删除的项目</span>
                <button
                  className="text-primary hover:underline"
                  onClick={() => {
                    const filtered = projects.filter((p) => p.title.toLowerCase().includes(projectSearch.toLowerCase()));
                    if (selectedIds.size === filtered.length) {
                      setSelectedIds(new Set());
                    } else {
                      setSelectedIds(new Set(filtered.map((p) => p.id)));
                    }
                  }}
                >
                  {selectedIds.size > 0 ? "取消全选" : "全选"}
                </button>
              </div>
              <div className="max-h-48 overflow-y-auto space-y-1 rounded-xl border border-border p-1">
                {projects
                  .filter((p) => p.title.toLowerCase().includes(projectSearch.toLowerCase()))
                  .slice(0, 200)
                  .map((p) => (
                    <label key={p.id} className="flex items-center gap-2 px-2 py-1.5 rounded-lg hover:bg-foreground/5 cursor-pointer">
                      <input
                        type="checkbox"
                        checked={selectedIds.has(p.id)}
                        onChange={() => toggleSelect(p.id)}
                        className="h-4 w-4 accent-primary"
                      />
                      <span className="text-sm truncate">{p.title}</span>
                    </label>
                  ))}
              </div>
              {selectedIds.size > 0 && (
                <Button variant="danger" size="sm" className="w-full" onClick={handleBatchDelete}>
                  删除选中 {selectedIds.size} 个项目
                </Button>
              )}
            </div>
          )}

          {currentProject && (
            <div className="mt-4 space-y-1">
              <SidebarSection title="工作台" icon={<LayoutDashboard className="h-3.5 w-3.5" />} active={activeTab === "dashboard"} onClick={() => setActiveTab("dashboard")} />
              <SidebarSection title="卷级规划" icon={<Route className="h-3.5 w-3.5" />} active={activeTab === "planning"} onClick={() => setActiveTab("planning")} />

              <div className="pt-3 pb-1 text-xs font-semibold text-muted uppercase tracking-wider flex items-center justify-between">
                世界
                <span className="text-[10px]">{worldSettings.length + factions.length + factionRelationships.length}</span>
              </div>
              <SidebarSection title="世界观设定" icon={<Globe className="h-3.5 w-3.5" />} active={activeTab === "world"} onClick={() => setActiveTab("world")} />
              <SidebarSection title="势力组织" icon={<Shield className="h-3.5 w-3.5" />} active={activeTab === "factions"} onClick={() => setActiveTab("factions")} />

              <div className="pt-3 pb-1 text-xs font-semibold text-muted uppercase tracking-wider flex items-center justify-between">
                人物
                <span className="text-[10px]">{characters.length + characterRelationships.length}</span>
              </div>
              <SidebarSection title="角色" icon={<Users className="h-3.5 w-3.5" />} active={activeTab === "characters"} onClick={() => setActiveTab("characters")} />
              <SidebarSection title="关系网" icon={<Network className="h-3.5 w-3.5" />} active={activeTab === "relationships"} onClick={() => setActiveTab("relationships")} />

              <div className="pt-3 pb-1 text-xs font-semibold text-muted uppercase tracking-wider flex items-center justify-between">
                生物/物品
                <span className="text-[10px]">{monsters.length}</span>
              </div>
              <SidebarSection title="怪物图鉴" icon={<Skull className="h-3.5 w-3.5" />} active={activeTab === "monsters"} onClick={() => setActiveTab("monsters")} />

              <div className="mt-1">
                <button
                  onClick={() => setOutlinesOpen(!outlinesOpen)}
                  className="w-full flex items-center justify-between px-3 py-2 rounded-xl text-sm font-medium text-muted hover:bg-foreground/5 hover:text-foreground transition-all"
                >
                  <span className="flex items-center gap-2.5">
                    <List className="h-3.5 w-3.5" />
                    大纲
                  </span>
                  {outlinesOpen ? <ChevronDown className="h-3.5 w-3.5" /> : <ChevronDown className="h-3.5 w-3.5 -rotate-90" />}
                </button>
                {outlinesOpen && (
                  <div className="ml-6 mt-1 space-y-1 border-l border-border pl-2">
                    <SidebarSection title="大纲（卷）" icon={<span className="h-1.5 w-1.5 rounded-full bg-current" />} active={activeTab === "outlines-volume"} onClick={() => setActiveTab("outlines-volume")} />
                    <SidebarSection title="细纲" icon={<span className="h-1.5 w-1.5 rounded-full bg-current" />} active={activeTab === "outlines-arc"} onClick={() => setActiveTab("outlines-arc")} />
                    <SidebarSection title="章纲" icon={<span className="h-1.5 w-1.5 rounded-full bg-current" />} active={activeTab === "outlines-chapter"} onClick={() => setActiveTab("outlines-chapter")} />
                  </div>
                )}
              </div>
              <SidebarSection title="章节摘要" icon={<ScrollText className="h-3.5 w-3.5" />} active={activeTab === "summaries"} onClick={() => setActiveTab("summaries")} />
              <SidebarSection title="导入设定" icon={<FileText className="h-3.5 w-3.5" />} active={activeTab === "import"} onClick={() => setActiveTab("import")} />
              <SidebarSection title="导出" icon={<Download className="h-3.5 w-3.5" />} active={activeTab === "export"} onClick={() => setActiveTab("export")} />
              <SidebarSection title="设置" icon={<Settings className="h-3.5 w-3.5" />} active={activeTab === "settings"} onClick={() => setActiveTab("settings")} />

              <div className="pt-3 pb-1 text-xs font-semibold text-muted uppercase tracking-wider flex items-center justify-between">
                资产
                <span className="text-[10px]">{characters.length + foreshadows.length + outlines.length + chapters.length + factions.length + factionRelationships.length + characterRelationships.length + monsters.length}</span>
              </div>
              <SidebarGroup title="角色" count={characters.length} onAdd={() => onCreateAsset("character")}>
                {characters.map((c) => (
                  <SidebarItem key={c.id} label={c.name} active={selectedAsset?.type === "character" && String(c.id) === selectedAsset.id} onClick={() => onSelectAsset("character", String(c.id), c)} />
                ))}
              </SidebarGroup>
              <SidebarGroup title="势力" count={factions.length} onAdd={() => onCreateAsset("faction")}>
                {factions.map((f) => (
                  <SidebarItem key={f.id} label={f.name} active={selectedAsset?.type === "faction" && String(f.id) === selectedAsset.id} onClick={() => onSelectAsset("faction", String(f.id), f)} />
                ))}
              </SidebarGroup>
              <SidebarGroup title="人物关系" count={characterRelationships.length} onAdd={() => onCreateAsset("characterRelationship")}>
                {characterRelationships.map((r) => (
                  <SidebarItem key={r.id} label={`${r.source_character} → ${r.target_character}`} active={selectedAsset?.type === "characterRelationship" && String(r.id) === selectedAsset.id} onClick={() => onSelectAsset("characterRelationship", String(r.id), r)} />
                ))}
              </SidebarGroup>
              <SidebarGroup title="怪物" count={monsters.length} onAdd={() => onCreateAsset("monster")}>
                {monsters.map((m) => (
                  <SidebarItem key={m.id} label={m.name} active={selectedAsset?.type === "monster" && String(m.id) === selectedAsset.id} onClick={() => onSelectAsset("monster", String(m.id), m)} />
                ))}
              </SidebarGroup>
              <SidebarGroup title="伏笔" count={foreshadows.length} onAdd={() => onCreateAsset("foreshadow")}>
                {foreshadows.map((f) => (
                  <SidebarItem key={f.id} label={f.foreshadow_id} active={selectedAsset?.type === "foreshadow" && String(f.id) === selectedAsset.id} onClick={() => onSelectAsset("foreshadow", String(f.id), f)} />
                ))}
              </SidebarGroup>
              <SidebarGroup title="大纲" count={outlines.length} onAdd={() => onCreateAsset("outline")}>
                {outlines.map((o) => (
                  <SidebarItem key={o.id} label={o.title} active={selectedAsset?.type === "outline" && String(o.id) === selectedAsset.id} onClick={() => onSelectAsset("outline", String(o.id), o)} />
                ))}
              </SidebarGroup>
              <SidebarGroup title="章节" count={chapters.length} onAdd={() => onCreateAsset("chapter")}>
                {chapters.length > 50 ? (
                  <VirtualList
                    items={chapters}
                    itemHeight={28}
                    maxHeight={280}
                    getKey={(ch) => ch.chapter}
                    renderItem={(ch) => (
                      <SidebarItem
                        label={`第${ch.chapter}章`}
                        active={selectedAsset?.type === "chapter" && String(ch.chapter) === selectedAsset.id}
                        onClick={() => selectChapter(ch.chapter)}
                      />
                    )}
                  />
                ) : (
                  chapters.map((ch) => (
                    <SidebarItem key={ch.chapter} label={`第${ch.chapter}章`} active={selectedAsset?.type === "chapter" && String(ch.chapter) === selectedAsset.id} onClick={() => selectChapter(ch.chapter)} />
                  ))
                )}
              </SidebarGroup>
            </div>
          )}
        </CardContent>
        {currentProject && (
          <div className="p-3 border-t border-border bg-surface/50">
            <Button variant="danger" size="sm" className="w-full" onClick={() => setDeleteDialogOpen(true)}>
              删除项目
            </Button>
          </div>
        )}
      </Card>

      <ConfirmDialog
        open={deleteDialogOpen}
        onOpenChange={setDeleteDialogOpen}
        title="删除项目"
        description={currentProject ? `确定要删除项目「${currentProject.title}」吗？此操作不可恢复。` : "确定要删除此项目吗？"}
        confirmText="删除"
        cancelText="取消"
        variant="danger"
        onConfirm={() => {
          setDeleteDialogOpen(false);
          onDeleteProject();
        }}
      />
    </div>
  );
}
