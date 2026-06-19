import { api } from "@/api";
import { useAppStore } from "@/store";
import { useToast } from "@/hooks/useToast";
import type { AssetType, Character, Foreshadow, Outline, Tab } from "@/types";

export function useAssetActions({
  selectedAsset,
  characterForm,
  foreshadowForm,
  outlineForm,
  chapterTitle,
  chapterContent,
  setSelectedAsset,
  setActiveTab,
  setChapterDirty,
}: {
  selectedAsset: { type: AssetType; id: string } | null;
  characterForm: Partial<Character>;
  foreshadowForm: Partial<Foreshadow>;
  outlineForm: Partial<Outline>;
  chapterTitle: string;
  chapterContent: string;
  setSelectedAsset: (asset: { type: AssetType; id: string } | null) => void;
  setActiveTab: (tab: Tab) => void;
  setChapterDirty: (dirty: boolean) => void;
}) {
  const store = useAppStore();
  const { showSuccess, showError } = useToast();

  const create = async (type: AssetType) => {
    if (!store.currentProject) return;
    try {
      if (type === "character") {
        await api.createCharacter(store.currentProject.id, { name: "新角色", role: "" });
      } else if (type === "foreshadow") {
        await api.createForeshadow(store.currentProject.id, { foreshadow_id: `伏笔${Date.now()}`, tier: "中", description: "" });
      } else if (type === "outline") {
        const order = store.outlines.length + 1;
        await api.createOutline(store.currentProject.id, { order, title: `第${order}章`, summary: "", level: "chapter" });
      } else if (type === "chapter") {
        const ch = store.chapters.length + 1;
        await api.saveChapterText(store.currentProject.id, ch, `第${ch}章`, "");
      } else if (type === "faction") {
        await api.createFaction(store.currentProject.id, { name: "新势力", type: "其他", alignment: "中立" });
      } else if (type === "factionRelationship") {
        const factions = store.factions;
        const sourceId = factions[0]?.id ?? 0;
        const targetId = factions[1]?.id ?? sourceId;
        await api.createFactionRelationship(store.currentProject.id, { source_faction_id: sourceId, target_faction_id: targetId, relation_type: "中立", strength: 0 });
      } else if (type === "characterRelationship") {
        const names = store.characters.map((c) => c.name).filter(Boolean);
        const source = names[0] || "角色A";
        const target = names[1] || "角色B";
        await api.createCharacterRelationship(store.currentProject.id, { source_character: source, target_character: target, relation_type: "其他", strength: 0 });
      } else if (type === "monster") {
        await api.createMonster(store.currentProject.id, { name: "新怪物", species: "未知", rank: "普通" });
      }
      await store.refreshAssets();
      showSuccess("创建成功");
    } catch (e: any) {
      showError("创建失败：" + e.message);
    }
  };

  const save = async () => {
    if (!store.currentProject || !selectedAsset) return;
    try {
      if (selectedAsset.type === "character") {
        const name = characterForm.name || "";
        await api.updateCharacter(store.currentProject.id, name, characterForm);
      } else if (selectedAsset.type === "foreshadow") {
        const id = String(foreshadowForm.foreshadow_id || selectedAsset.id);
        await api.updateForeshadow(store.currentProject.id, id, foreshadowForm);
      } else if (selectedAsset.type === "outline") {
        await api.updateOutline(store.currentProject.id, Number(selectedAsset.id), outlineForm);
      } else if (selectedAsset.type === "chapter") {
        await api.saveChapterText(store.currentProject.id, Number(selectedAsset.id), chapterTitle, chapterContent);
        setChapterDirty(false);
      } else if (selectedAsset.type === "faction" || selectedAsset.type === "factionRelationship" || selectedAsset.type === "characterRelationship" || selectedAsset.type === "monster") {
        return;
      }
      await store.refreshAssets();
      showSuccess("保存成功");
    } catch (e: any) {
      showError("保存失败：" + e.message);
    }
  };

  const remove = async () => {
    if (!store.currentProject || !selectedAsset) return;
    try {
      if (selectedAsset.type === "character") {
        await api.deleteCharacter(store.currentProject.id, characterForm.name || "");
      } else if (selectedAsset.type === "foreshadow") {
        await api.deleteForeshadow(store.currentProject.id, String(foreshadowForm.foreshadow_id || selectedAsset.id));
      } else if (selectedAsset.type === "outline") {
        await api.deleteOutline(store.currentProject.id, Number(selectedAsset.id));
      } else if (selectedAsset.type === "chapter") {
        await api.deleteChapter(store.currentProject.id, Number(selectedAsset.id));
      } else if (selectedAsset.type === "faction") {
        await api.deleteFaction(store.currentProject.id, Number(selectedAsset.id));
      } else if (selectedAsset.type === "factionRelationship") {
        await api.deleteFactionRelationship(store.currentProject.id, Number(selectedAsset.id));
      } else if (selectedAsset.type === "characterRelationship") {
        await api.deleteCharacterRelationship(store.currentProject.id, Number(selectedAsset.id));
      } else if (selectedAsset.type === "monster") {
        await api.deleteMonster(store.currentProject.id, Number(selectedAsset.id));
      }
      setSelectedAsset(null);
      setActiveTab("dashboard");
      await store.refreshAssets();
      showSuccess("删除成功");
    } catch (e: any) {
      showError("删除失败：" + e.message);
    }
  };

  return { create, save, remove };
}
