import { WorldView } from "@/components/world-view";
import { CharactersView } from "@/components/characters-view";
import { OutlinesVolumeView } from "@/views/OutlinesVolumeView";
import { OutlinesArcView } from "@/views/OutlinesArcView";
import { OutlinesChapterView } from "@/views/OutlinesChapterView";
import { DashboardView } from "@/views/DashboardView";
import { AssetEditorView } from "@/views/AssetEditorView";
import { ChapterEditorView } from "@/views/ChapterEditorView";
import { ImportView } from "@/views/ImportView";
import { ExportView } from "@/views/ExportView";
import { PlanningView } from "@/views/PlanningView";
import { SummariesView } from "@/views/SummariesView";
import { FactionsView } from "@/views/FactionsView";
import { FactionEditorView } from "@/views/FactionEditorView";
import { RelationshipsView } from "@/views/RelationshipsView";
import { RelationshipEditorView } from "@/views/RelationshipEditorView";
import { MonstersView } from "@/views/MonstersView";
import { MonsterEditorView } from "@/views/MonsterEditorView";
import { SettingsView } from "@/views/SettingsView";
import { ImportPreviewDialog } from "@/components/import-preview-dialog";
import { useAppStore } from "@/store";
import type { Project, Character, Foreshadow, Outline, AssetType, ImportPreviewData, Faction, Monster, CharacterRelationship } from "@/types";

type Tab = "dashboard" | "planning" | "world" | "characters" | "outlines-volume" | "outlines-arc" | "outlines-chapter" | "asset" | "chapter" | "summaries" | "import" | "export" | "factions" | "relationships" | "monsters" | "settings";

type EntityGenerationApi = {
  generating: Record<AssetType, boolean>;
  generateCharacter: (seed?: Partial<Character>) => Promise<void>;
  generateFaction: (seed?: Partial<Faction>) => Promise<void>;
  generateMonster: (seed?: Partial<Monster>) => Promise<void>;
  generateCharacterRelationship: (seed?: { source_character?: string; target_character?: string } & Partial<CharacterRelationship>) => Promise<void>;
};

interface WorkspaceProps {
  activeTab: Tab;
  selectedAsset: { type: AssetType; id: string } | null;
  loading: boolean;
  projectForm: Partial<Project>;
  setProjectForm: (form: Partial<Project>) => void;
  onSaveProject: (form: Partial<Project>) => void | Promise<void>;
  characterForm: Partial<Character>;
  setCharacterForm: (form: Partial<Character>) => void;
  foreshadowForm: Partial<Foreshadow>;
  setForeshadowForm: (form: Partial<Foreshadow>) => void;
  outlineForm: Partial<Outline>;
  setOutlineForm: (form: Partial<Outline>) => void;
  chapterTitle: string;
  setChapterTitle: (title: string) => void;
  chapterContent: string;
  setChapterContent: (content: string) => void;
  chapterDirty: boolean;
  setChapterDirty: (dirty: boolean) => void;
  autoSaveState: "idle" | "saving" | "saved";
  onSaveAsset: () => void;
  onDeleteAsset: () => void;
  onGenerate: (chapter: number, title: string) => void;
  generatingChapter: number | null;
  importContent: string;
  setImportContent: (content: string) => void;
  onImportDocument: () => void;
  onImportFile: (file: File) => void;
  onImportStructured: (data: object) => Promise<void>;
  importPreviewOpen: boolean;
  setImportPreviewOpen: (open: boolean) => void;
  importPreviewData: ImportPreviewData;
  onImportFromPreview: (data: ImportPreviewData) => void;
  totalWords: number;
  setLoading: (loading: boolean) => void;
  onSelectAsset?: (type: AssetType, id: string) => void;
  setActiveTab?: (tab: Tab) => void;
  entityGeneration?: EntityGenerationApi;
}

export function Workspace({
  activeTab,
  selectedAsset,
  loading,
  projectForm,
  setProjectForm,
  onSaveProject,
  characterForm,
  setCharacterForm,
  foreshadowForm,
  setForeshadowForm,
  outlineForm,
  setOutlineForm,
  chapterTitle,
  setChapterTitle,
  chapterContent,
  setChapterContent,
  chapterDirty,
  setChapterDirty,
  autoSaveState,
  onSaveAsset,
  onDeleteAsset,
  onGenerate,
  generatingChapter,
  importContent,
  setImportContent,
  onImportDocument,
  onImportFile,
  onImportStructured,
  importPreviewOpen,
  setImportPreviewOpen,
  importPreviewData,
  onImportFromPreview,
  totalWords,
  setLoading,
  onSelectAsset,
  setActiveTab,
  entityGeneration,
}: WorkspaceProps) {
  const store = useAppStore();

  const handleAssetBack = () => {
    if (!setActiveTab) return;
    if (selectedAsset?.type === "faction") return setActiveTab("factions");
    if (selectedAsset?.type === "characterRelationship") return setActiveTab("relationships");
    if (selectedAsset?.type === "monster") return setActiveTab("monsters");
    return setActiveTab("dashboard");
  };

  return (
    <div className="flex-1 min-w-0 flex flex-col gap-3 relative">
      {loading && (
        <div className="absolute inset-x-0 top-0 z-50">
          <div className="h-1 w-full bg-primary/20 overflow-hidden">
            <div className="h-full bg-primary animate-[loading_1.5s_ease-in-out_infinite]" style={{ width: "40%" }} />
          </div>
          <div className="absolute right-3 top-2 text-xs text-primary font-medium">AI 处理中…</div>
        </div>
      )}
      {activeTab === "dashboard" && (
        <DashboardView
          project={store.currentProject}
          totalWords={totalWords}
          chapterCount={store.chapters.length}
          characterCount={store.characters.length}
          foreshadowCount={store.foreshadows.length}
          outlineCount={store.outlines.length}
          projectForm={projectForm}
          setProjectForm={setProjectForm}
          onSave={onSaveProject}
          genreContext={store.genreContext}
          onRefreshGenreContext={store.refreshGenreContext}
        />
      )}
      {activeTab === "planning" && <PlanningView setLoading={setLoading} />}
      {activeTab === "world" && (
        <WorldView project={store.currentProject} worldSettings={store.worldSettings} refresh={store.refreshAssets} setLoading={setLoading} />
      )}
      {activeTab === "characters" && (
        <CharactersView project={store.currentProject} characters={store.characters} refresh={store.refreshAssets} setLoading={setLoading} />
      )}
      {activeTab === "outlines-volume" && (
        <OutlinesVolumeView project={store.currentProject} refresh={store.refreshAssets} setLoading={setLoading} />
      )}
      {activeTab === "outlines-arc" && (
        <OutlinesArcView project={store.currentProject} refresh={store.refreshAssets} setLoading={setLoading} />
      )}
      {activeTab === "outlines-chapter" && (
        <OutlinesChapterView project={store.currentProject} refresh={store.refreshAssets} setLoading={setLoading} />
      )}
      {activeTab === "factions" && (
        <FactionsView project={store.currentProject} factions={store.factions} refresh={store.refreshAssets} setLoading={setLoading} onSelectAsset={onSelectAsset} />
      )}
      {activeTab === "relationships" && (
        <RelationshipsView
          project={store.currentProject}
          characters={store.characters}
          relationships={store.characterRelationships}
          refresh={store.refreshAssets}
          setLoading={setLoading}
          onSelectAsset={onSelectAsset}
          onGenerateRelationship={() => entityGeneration?.generateCharacterRelationship()}
          generatingRelationship={entityGeneration?.generating["characterRelationship"]}
        />
      )}
      {activeTab === "monsters" && (
        <MonstersView project={store.currentProject} monsters={store.monsters} refresh={store.refreshAssets} setLoading={setLoading} onSelectAsset={onSelectAsset} />
      )}
      {activeTab === "asset" && selectedAsset && selectedAsset.type === "faction" && (
        <FactionEditorView
          factionId={Number(selectedAsset.id)}
          onBack={handleAssetBack}
          onGenerateFaction={() => entityGeneration?.generateFaction()}
          generatingFaction={entityGeneration?.generating["faction"]}
        />
      )}
      {activeTab === "asset" && selectedAsset && selectedAsset.type === "characterRelationship" && (
        <RelationshipEditorView
          relationshipId={Number(selectedAsset.id)}
          onBack={handleAssetBack}
          onGenerateRelationship={() =>
            entityGeneration?.generateCharacterRelationship({
              source_character: store.characterRelationships.find((r) => r.id === Number(selectedAsset.id))?.source_character,
              target_character: store.characterRelationships.find((r) => r.id === Number(selectedAsset.id))?.target_character,
            })
          }
          generatingRelationship={entityGeneration?.generating["characterRelationship"]}
        />
      )}
      {activeTab === "asset" && selectedAsset && selectedAsset.type === "monster" && (
        <MonsterEditorView
          monsterId={Number(selectedAsset.id)}
          onBack={handleAssetBack}
          onGenerateMonster={() => entityGeneration?.generateMonster()}
          generatingMonster={entityGeneration?.generating["monster"]}
        />
      )}
      {activeTab === "asset" && selectedAsset && (selectedAsset.type === "character" || selectedAsset.type === "foreshadow" || selectedAsset.type === "outline") && (
        <AssetEditorView
          type={selectedAsset.type}
          character={characterForm}
          setCharacter={setCharacterForm}
          foreshadow={foreshadowForm}
          setForeshadow={setForeshadowForm}
          outline={outlineForm}
          setOutline={setOutlineForm}
          onSave={onSaveAsset}
          onDelete={onDeleteAsset}
          onGenerateCharacter={() => entityGeneration?.generateCharacter()}
          generatingCharacter={entityGeneration?.generating["character"]}
        />
      )}
      {activeTab === "chapter" && selectedAsset && (
        <ChapterEditorView
          project={store.currentProject ?? undefined}
          chapter={Number(selectedAsset.id)}
          title={chapterTitle}
          content={chapterContent}
          dirty={chapterDirty}
          autoSaveState={autoSaveState}
          onTitleChange={setChapterTitle}
          onContentChange={(v: string) => { setChapterContent(v); setChapterDirty(true); }}
          onSave={onSaveAsset}
          onDelete={onDeleteAsset}
          onGenerate={() => onGenerate(Number(selectedAsset.id), chapterTitle)}
          generating={generatingChapter === Number(selectedAsset.id)}
        />
      )}
      {activeTab === "import" && (
        <ImportView content={importContent} setContent={setImportContent} onImport={onImportDocument} onImportFile={onImportFile} onImportStructured={onImportStructured} loading={loading} />
      )}
      <ImportPreviewDialog
        open={importPreviewOpen}
        data={importPreviewData}
        onClose={() => setImportPreviewOpen(false)}
        onImport={onImportFromPreview}
      />
      {activeTab === "summaries" && <SummariesView />}
      {activeTab === "export" && (
        <ExportView projectId={store.currentProject?.id} />
      )}
      {activeTab === "settings" && <SettingsView />}
      {!store.currentProject && activeTab === "dashboard" && (
        <div className="flex-1 flex items-center justify-center text-muted text-sm">请选择一个项目或创建新项目</div>
      )}
    </div>
  );
}
