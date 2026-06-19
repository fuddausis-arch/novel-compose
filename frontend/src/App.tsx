import { useEffect, useRef, useState } from "react";
import { BookOpen, Loader2, Menu, PanelRightClose, PanelRightOpen } from "lucide-react";
import { api } from "./api";
import { useAppStore } from "./store";
import { cn } from "@/lib/utils";
import type { Project, Character, Foreshadow, Outline, ChapterText, AssetType, Faction, FactionRelationship, CharacterRelationship, Monster } from "./types";
import { AppSidebar } from "@/components/app-sidebar";
import { PipelinePanel } from "@/components/pipeline-panel";
import { Workspace } from "@/components/workspace";
import { useProjectActions } from "@/hooks/useProjectActions";
import { useAssetActions } from "@/hooks/useAssetActions";
import { useImportActions } from "@/hooks/useImportActions";
import { useGeneration } from "@/hooks/useGeneration";
import { useEntityGeneration } from "@/hooks/useEntityGeneration";
import { useToast } from "@/hooks/useToast";
import { useConfirmDialog } from "@/hooks/useConfirmDialog";
import { ThemeSwitcher } from "@/components/theme-switcher";

type Tab = "dashboard" | "planning" | "world" | "characters" | "outlines-volume" | "outlines-arc" | "outlines-chapter" | "asset" | "chapter" | "summaries" | "import" | "export" | "factions" | "relationships" | "monsters" | "settings";

const EMPTY_PROJECT: Partial<Project> = {
  title: "",
  genre: "",
  summary: "",
  style: "",
};

const AUTOSAVE_DELAY_MS = 1000;

export default function App() {
  const store = useAppStore();
  const { showError } = useToast();
  const [activeTab, setActiveTab] = useState<Tab>("dashboard");
  const [selectedAsset, setSelectedAsset] = useState<{ type: AssetType; id: string } | null>(null);
  const [loading, setLoading] = useState(false);
  const [sidebarOpen, setSidebarOpen] = useState(false);
  const [rightPanelOpen, setRightPanelOpen] = useState(false);
  const [projectSearch, setProjectSearch] = useState("");

  const [projectForm, setProjectForm] = useState<Partial<Project>>(EMPTY_PROJECT);
  const [characterForm, setCharacterForm] = useState<Partial<Character>>({});
  const [foreshadowForm, setForeshadowForm] = useState<Partial<Foreshadow>>({});
  const [outlineForm, setOutlineForm] = useState<Partial<Outline>>({});
  const [chapterTitle, setChapterTitle] = useState("");
  const [chapterContent, setChapterContent] = useState("");
  const [chapterDirty, setChapterDirty] = useState(false);
  const [autoSaveState, setAutoSaveState] = useState<"idle" | "saving" | "saved">("idle");
  const autoSaveTimer = useRef<ReturnType<typeof setTimeout> | null>(null);

  const projectActions = useProjectActions({ setActiveTab, setSelectedAsset });
  const assetActions = useAssetActions({
    selectedAsset,
    characterForm,
    foreshadowForm,
    outlineForm,
    chapterTitle,
    chapterContent,
    setSelectedAsset,
    setActiveTab,
    setChapterDirty,
  });
  const importActions = useImportActions({
    setLoading,
    onImportSuccess: () => setActiveTab("dashboard"),
  });
  const { confirm: confirmDelete, dialog: deleteAssetDialog } = useConfirmDialog();

  const handleDeleteAsset = async () => {
    if (!selectedAsset) return;
    const labels: Record<AssetType, string> = {
      character: "角色",
      foreshadow: "伏笔",
      outline: "大纲",
      chapter: "章节",
      faction: "势力",
      factionRelationship: "势力关系",
      characterRelationship: "人物关系",
      monster: "怪物",
    };
    const name =
      selectedAsset.type === "character"
        ? characterForm.name
        : selectedAsset.type === "foreshadow"
        ? foreshadowForm.foreshadow_id
        : selectedAsset.type === "outline"
        ? outlineForm.title
        : selectedAsset.type === "chapter"
        ? chapterTitle
        : selectedAsset.id;
    const confirmed = await confirmDelete({
      title: `删除${labels[selectedAsset.type]}`,
      description: `确定要删除${labels[selectedAsset.type]}「${name || selectedAsset.id}」吗？此操作不可恢复。`,
      confirmText: "删除",
      cancelText: "取消",
      variant: "danger",
    });
    if (confirmed) {
      await assetActions.remove();
    }
  };

  useEffect(() => {
    const applyResponsive = () => {
      const w = window.innerWidth;
      setSidebarOpen(w >= 768);
      setRightPanelOpen(w >= 1024);
    };
    applyResponsive();
    window.addEventListener("resize", applyResponsive);
    return () => window.removeEventListener("resize", applyResponsive);
  }, []);

  useEffect(() => {
    const load = async () => {
      try {
        await store.refreshProjects();
      } catch (e: any) {
        showError("加载项目列表失败：" + e.message);
      }
    };
    load();
  }, []);

  useEffect(() => {
    const load = async () => {
      if (store.currentProject) {
        setProjectForm(store.currentProject);
        try {
          await store.refreshAssets();
          await store.refreshGenreContext();
        } catch (e: any) {
          showError("加载项目数据失败：" + e.message);
        }
        setActiveTab("dashboard");
        setSelectedAsset(null);
      } else {
        setProjectForm(EMPTY_PROJECT);
        setActiveTab("dashboard");
        setSelectedAsset(null);
      }
    };
    load();
  }, [store.currentProject?.id]);

  useEffect(() => {
    if (!chapterDirty || !selectedAsset || selectedAsset.type !== "chapter") {
      setAutoSaveState("idle");
      return;
    }
    if (autoSaveTimer.current) {
      clearTimeout(autoSaveTimer.current);
    }
    setAutoSaveState("idle");
    autoSaveTimer.current = setTimeout(async () => {
      setAutoSaveState("saving");
      try {
        await api.saveChapterText(Number(selectedAsset.id), chapterTitle, chapterContent);
        setChapterDirty(false);
        setAutoSaveState("saved");
      } catch (e: any) {
        showError("自动保存失败：" + e.message);
        setAutoSaveState("idle");
      }
    }, AUTOSAVE_DELAY_MS);
    return () => {
      if (autoSaveTimer.current) {
        clearTimeout(autoSaveTimer.current);
      }
    };
  }, [chapterTitle, chapterContent, chapterDirty, selectedAsset?.id, selectedAsset?.type]);

  const handleSelectAsset = (type: AssetType, id: string, data?: Character | Foreshadow | Outline | ChapterText | Faction | FactionRelationship | CharacterRelationship | Monster) => {
    setSelectedAsset({ type, id });
    if (type === "chapter") {
      setActiveTab("chapter");
      const chapterData = data as ChapterText | undefined;
      setChapterTitle(chapterData?.chapter ? `第${chapterData.chapter}章` : `第${id}章`);
      setChapterContent(chapterData?.text || "");
      setChapterDirty(false);
    } else if (type === "faction" || type === "characterRelationship" || type === "monster") {
      setActiveTab("asset");
    } else {
      setActiveTab("asset");
      if (type === "character") setCharacterForm((data as Character) || store.characters.find((c) => String(c.id) === id) || {});
      if (type === "foreshadow") setForeshadowForm((data as Foreshadow) || store.foreshadows.find((f) => String(f.id) === id) || {});
      if (type === "outline") setOutlineForm((data as Outline) || store.outlines.find((o) => String(o.id) === id) || {});
    }
  };

  const generation = useGeneration({
    setLoading,
    onDone: (ct) => handleSelectAsset("chapter", String(ct.chapter), ct),
  });

  const entityGeneration = useEntityGeneration({
    setLoading,
    onSelectAsset: handleSelectAsset,
  });

  const totalWords = store.chapters.reduce((sum, ch) => sum + (ch.text_preview?.length || 0), 0);

  return (
    <div className="h-screen w-screen flex flex-col bg-background text-foreground overflow-hidden">
      {/* Title Bar */}
      <div className="relative z-50 h-11 flex items-center justify-between px-4 glass select-none app-drag">
        <div className="flex items-center gap-2">
          <button
            className="md:hidden p-1.5 rounded-lg hover:bg-foreground/5 no-drag"
            onClick={() => setSidebarOpen((v) => !v)}
            aria-label="切换侧边栏"
          >
            <Menu className="h-4 w-4 text-foreground" />
          </button>
          <BookOpen className="h-4 w-4 text-primary" />
          <span className="text-sm font-medium">小说生成器</span>
          {store.currentProject && (
            <span className="text-xs text-muted ml-2 hidden sm:inline">· {store.currentProject.title}</span>
          )}
        </div>
        <div className="flex items-center gap-2 no-drag">
          <ThemeSwitcher />
          {generation.pipelineStatus === "running" && <Loader2 className="h-3 w-3 animate-spin text-primary" />}
          <button
            className="lg:hidden p-1.5 rounded-lg hover:bg-foreground/5"
            onClick={() => setRightPanelOpen((v) => !v)}
            aria-label="切换右侧面板"
          >
            {rightPanelOpen ? <PanelRightOpen className="h-4 w-4 text-foreground" /> : <PanelRightClose className="h-4 w-4 text-foreground" />}
          </button>
        </div>
      </div>

      {/* Main Body */}
      <div className="flex-1 flex overflow-hidden p-3 gap-3 relative">
        {/* Left Sidebar */}
        <div
          className={cn(
            "z-40 h-full transition-transform duration-200 ease-out",
            "md:relative md:block md:w-56",
            sidebarOpen ? "absolute inset-y-3 left-3 w-56 md:relative" : "hidden md:block"
          )}
        >
          <AppSidebar
            projects={store.projects}
            currentProject={store.currentProject}
            projectSearch={projectSearch}
            setProjectSearch={setProjectSearch}
            onSelectProject={projectActions.select}
            onCreateProject={projectActions.create}
            onDeleteProject={projectActions.remove}
            activeTab={activeTab}
            setActiveTab={setActiveTab}
            selectedAsset={selectedAsset}
            onSelectAsset={handleSelectAsset}
            onCreateAsset={assetActions.create}
            characters={store.characters}
            foreshadows={store.foreshadows}
            outlines={store.outlines}
            chapters={store.chapters}
            worldSettings={store.worldSettings}
            factions={store.factions}
            factionRelationships={store.factionRelationships}
            characterRelationships={store.characterRelationships}
            monsters={store.monsters}
          />
        </div>
        {sidebarOpen && (
          <div className="absolute inset-0 bg-black/20 z-30 md:hidden" onClick={() => setSidebarOpen(false)} />
        )}

        {/* Center Workspace */}
        <Workspace
          activeTab={activeTab}
          selectedAsset={selectedAsset}
          loading={loading}
          projectForm={projectForm}
          setProjectForm={setProjectForm}
          onSaveProject={projectActions.save}
          characterForm={characterForm}
          setCharacterForm={setCharacterForm}
          foreshadowForm={foreshadowForm}
          setForeshadowForm={setForeshadowForm}
          outlineForm={outlineForm}
          setOutlineForm={setOutlineForm}
          chapterTitle={chapterTitle}
          setChapterTitle={setChapterTitle}
          chapterContent={chapterContent}
          setChapterContent={setChapterContent}
          chapterDirty={chapterDirty}
          setChapterDirty={setChapterDirty}
          autoSaveState={autoSaveState}
          onSaveAsset={assetActions.save}
          onDeleteAsset={handleDeleteAsset}
          onGenerate={generation.generate}
          generatingChapter={generation.generatingChapter}
          importContent={importActions.importContent}
          setImportContent={importActions.setImportContent}
          onImportDocument={importActions.parseDocument}
          onImportFile={importActions.parseFile}
          onImportStructured={importActions.importStructured}
          importPreviewOpen={importActions.importPreviewOpen}
          setImportPreviewOpen={importActions.setImportPreviewOpen}
          importPreviewData={importActions.importPreviewData}
          onImportFromPreview={importActions.importFromPreview}
          totalWords={totalWords}
          setLoading={setLoading}
          onSelectAsset={handleSelectAsset}
          setActiveTab={setActiveTab}
          entityGeneration={entityGeneration}
        />

        {/* Right Pipeline Panel */}
        <div
          className={cn(
            "z-40 h-full transition-transform duration-200 ease-out",
            "lg:relative lg:block lg:w-72",
            rightPanelOpen ? "absolute inset-y-3 right-3 w-72 lg:relative" : "hidden lg:block"
          )}
        >
          <PipelinePanel events={generation.pipelineEvents} status={generation.pipelineStatus} />
        </div>
        {rightPanelOpen && (
          <div className="absolute inset-0 bg-black/20 z-30 lg:hidden" onClick={() => setRightPanelOpen(false)} />
        )}
      </div>
      {deleteAssetDialog}
    </div>
  );
}
