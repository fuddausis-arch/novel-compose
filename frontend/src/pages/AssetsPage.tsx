import { useState } from "react";
import { cn } from "@/lib/utils";
import { AppLayout } from "@/components/layout/AppLayout";
import { AssetTypeNav, ASSET_TYPES, type AssetNavType } from "@/components/assets/AssetTypeNav";
import { CharactersView } from "@/components/characters-view";
import { WorldView } from "@/components/world-view";
import { ForeshadowsView } from "@/components/foreshadows-view";
import { FactionsView } from "@/views/FactionsView";
import { MonstersView } from "@/views/MonstersView";
import { InstancesView } from "@/views/InstancesView";
import { RelationshipsView } from "@/views/RelationshipsView";
import { FactionEditorView } from "@/views/FactionEditorView";
import { MonsterEditorView } from "@/views/MonsterEditorView";
import { InstanceEditorView } from "@/views/InstanceEditorView";
import { RelationshipEditorView } from "@/views/RelationshipEditorView";
import { AssetCards } from "@/components/assets/AssetCards";
import { RedLinesView } from "@/components/red-lines-view";
import { GagsView } from "@/components/gags-view";
import { ImportFolderView } from "@/components/import-folder-view";
import { useCurrentProject } from "@/hooks/useCurrentProject";
import { useAppStore } from "@/store";

export default function AssetsPage() {
  const [type, setType] = useState<AssetNavType>("characters");
  const [showRelationships, setShowRelationships] = useState(false);
  const [selectedAsset, setSelectedAsset] = useState<{ type: string; id: string } | null>(null);
  const { project } = useCurrentProject();
  const store = useAppStore();

  const setLoading = (loading: boolean) => {
    store.setLoading("assets", loading);
  };

  const handleSelectAsset = (assetType: string, id: string) => {
    setSelectedAsset({ type: assetType, id });
  };

  const backToList = () => setSelectedAsset(null);

  const renderEditor = () => {
    if (!selectedAsset) return null;
    const numericId = Number(selectedAsset.id);
    if (selectedAsset.type === "faction") {
      return <FactionEditorView factionId={numericId} onBack={backToList} />;
    }
    if (selectedAsset.type === "monster") {
      return <MonsterEditorView monsterId={numericId} onBack={backToList} />;
    }
    if (selectedAsset.type === "instance") {
      return <InstanceEditorView instanceId={numericId} onBack={backToList} />;
    }
    if (selectedAsset.type === "characterRelationship") {
      return <RelationshipEditorView relationshipId={numericId} onBack={backToList} />;
    }
    return null;
  };

  return (
    <AppLayout>
      <div className="flex h-full flex-col overflow-hidden md:flex-row">
        <div className="hidden w-44 shrink-0 flex-col gap-1 border-r border-border bg-surface p-3 md:flex">
          <AssetTypeNav
            value={type}
            onChange={(value) => {
              setType(value);
              setShowRelationships(false);
              setSelectedAsset(null);
            }}
          />
          <button
            onClick={() => {
              setShowRelationships(true);
              setSelectedAsset(null);
            }}
            className={cn(
              "flex items-center gap-2 rounded-lg px-3 py-2 text-left text-sm font-medium transition-colors",
              showRelationships
                ? "bg-primary text-primary-foreground"
                : "text-foreground hover:bg-foreground/5"
            )}
          >
            <span>🔗</span>
            <span>人物关系</span>
          </button>
        </div>

        {/* 移动端（<768px）：顶部横向滚动分类 chips 栏，替代左侧导航 */}
        <div className="flex shrink-0 items-center gap-1 overflow-x-auto border-b border-border bg-surface px-3 py-2 md:hidden">
          {ASSET_TYPES.map((t) => (
            <button
              key={t.key}
              type="button"
              onClick={() => {
                setType(t.key);
                setShowRelationships(false);
                setSelectedAsset(null);
              }}
              className={cn(
                "shrink-0 whitespace-nowrap rounded-full px-3 py-1.5 text-sm font-medium transition-colors",
                type === t.key
                  ? "bg-primary text-primary-foreground"
                  : "text-foreground hover:bg-foreground/5"
              )}
            >
              <span>{t.icon}</span>
              <span className="ml-1">{t.label}</span>
            </button>
          ))}
          <button
            type="button"
            onClick={() => {
              setShowRelationships(true);
              setSelectedAsset(null);
            }}
            className={cn(
              "shrink-0 whitespace-nowrap rounded-full px-3 py-1.5 text-sm font-medium transition-colors",
              showRelationships
                ? "bg-primary text-primary-foreground"
                : "text-foreground hover:bg-foreground/5"
            )}
          >
            <span>🔗</span>
            <span className="ml-1">人物关系</span>
          </button>
        </div>

        <div className="flex flex-1 flex-col overflow-hidden overflow-y-auto">
          {selectedAsset ? (
            renderEditor()
          ) : showRelationships ? (
            <RelationshipsView
              project={project}
              characters={store.characters}
              relationships={store.characterRelationships}
              refresh={store.refreshCharacterRelationships}
              setLoading={setLoading}
              onSelectAsset={handleSelectAsset}
            />
          ) : type === "characters" ? (
            <CharactersView
              project={project}
              characters={store.characters}
              refresh={store.refreshCharacters}
              setLoading={setLoading}
            />
          ) : type === "world" ? (
            <WorldView
              project={project}
              worldSettings={store.worldSettings}
              refresh={store.refreshWorldSettings}
              setLoading={setLoading}
            />
          ) : type === "factions" ? (
            <FactionsView
              project={project}
              factions={store.factions}
              refresh={store.refreshFactions}
              setLoading={setLoading}
              onSelectAsset={handleSelectAsset}
            />
          ) : type === "monsters" ? (
            <MonstersView
              project={project}
              monsters={store.monsters}
              refresh={store.refreshMonsters}
              setLoading={setLoading}
              onSelectAsset={handleSelectAsset}
            />
          ) : type === "instances" ? (
            <InstancesView
              project={project}
              instances={store.instances}
              refresh={store.refreshInstances}
              setLoading={setLoading}
              onSelectAsset={handleSelectAsset}
            />
          ) : type === "foreshadows" ? (
            <ForeshadowsView />
          ) : type === "redLines" ? (
            <RedLinesView />
          ) : type === "gags" ? (
            <GagsView />
          ) : type === "importFolder" ? (
            <ImportFolderView />
          ) : (
            <AssetCards type={type} projectId={project?.id ?? 0} />
          )}
        </div>
      </div>
    </AppLayout>
  );
}
