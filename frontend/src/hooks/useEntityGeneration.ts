import { useState } from "react";
import { api } from "@/api";
import { useAppStore } from "@/store";
import { useToast } from "@/hooks/useToast";
import type { AssetType, Character, CharacterRelationship, Faction, Monster } from "@/types";

export function useEntityGeneration({
  setLoading,
  onSelectAsset,
}: {
  setLoading: (loading: boolean) => void;
  onSelectAsset?: (type: AssetType, id: string) => void;
}) {
  const store = useAppStore();
  const { showSuccess, showError } = useToast();
  const [generating, setGenerating] = useState<Record<AssetType, boolean>>({
    character: false,
    foreshadow: false,
    outline: false,
    chapter: false,
    faction: false,
    factionRelationship: false,
    characterRelationship: false,
    monster: false,
  });

  const withLoading = async <T,>(key: AssetType, fn: () => Promise<T>) => {
    setGenerating((prev) => ({ ...prev, [key]: true }));
    setLoading(true);
    try {
      return await fn();
    } finally {
      setGenerating((prev) => ({ ...prev, [key]: false }));
      setLoading(false);
    }
  };

  const refreshAndOpen = async (type: AssetType, id: string, refresh: () => Promise<void>) => {
    await refresh();
    onSelectAsset?.(type, id);
    showSuccess("AI 生成完成");
  };

  const generateCharacter = async (seed?: Partial<Character>) => {
    if (!store.currentProject) return;
    try {
      const character = await withLoading("character", () => api.generateCharacter(store.currentProject!.id, seed));
      await refreshAndOpen("character", String(character.id), store.refreshAssets);
    } catch (e: any) {
      showError("生成角色失败：" + e.message);
    }
  };

  const generateFaction = async (seed?: Partial<Faction>) => {
    if (!store.currentProject) return;
    try {
      const faction = await withLoading("faction", () => api.generateFaction(store.currentProject!.id, seed));
      await refreshAndOpen("faction", String(faction.id), store.refreshAssets);
    } catch (e: any) {
      showError("生成势力失败：" + e.message);
    }
  };

  const generateMonster = async (seed?: Partial<Monster>) => {
    if (!store.currentProject) return;
    try {
      const monster = await withLoading("monster", () => api.generateMonster(store.currentProject!.id, seed));
      await refreshAndOpen("monster", String(monster.id), store.refreshAssets);
    } catch (e: any) {
      showError("生成怪物失败：" + e.message);
    }
  };

  const generateCharacterRelationship = async (seed?: { source_character?: string; target_character?: string } & Partial<CharacterRelationship>) => {
    if (!store.currentProject) return;
    try {
      const relationship = await withLoading("characterRelationship", () => api.generateCharacterRelationship(store.currentProject!.id, seed || {}));
      await refreshAndOpen("characterRelationship", String(relationship.id), store.refreshCharacterRelationships);
    } catch (e: any) {
      showError("生成关系失败：" + e.message);
    }
  };

  return {
    generating,
    generateCharacter,
    generateFaction,
    generateMonster,
    generateCharacterRelationship,
  };
}
