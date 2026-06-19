import { useState } from "react";
import { api } from "@/api";
import { useAppStore } from "@/store";
import { useToast } from "@/hooks/useToast";
import type { ImportPreviewData } from "@/types";

export function useImportActions({
  setLoading,
  onImportSuccess,
}: {
  setLoading: (loading: boolean) => void;
  onImportSuccess?: () => void;
}) {
  const store = useAppStore();
  const { showSuccess, showError } = useToast();
  const [importContent, setImportContent] = useState("");
  const [importPreviewOpen, setImportPreviewOpen] = useState(false);
  const [importPreviewData, setImportPreviewData] = useState<ImportPreviewData>({
    world_settings: [],
    factions: [],
    faction_relationships: [],
    character_relationships: [],
    characters: [],
    foreshadows: [],
    outlines: [],
    monsters: [],
  });

  const parseDocument = async () => {
    if (!store.currentProject || !importContent.trim()) return;
    setLoading(true);
    try {
      const r = await api.parseDocument(store.currentProject.id, importContent.trim());
      setImportPreviewData(r);
      setImportPreviewOpen(true);
    } catch (e: any) {
      showError("解析失败：" + e.message);
    } finally {
      setLoading(false);
    }
  };

  const parseFile = async (file: File) => {
    if (!store.currentProject) return;
    setLoading(true);
    try {
      const r = await api.parseFile(store.currentProject.id, file);
      setImportPreviewData(r);
      setImportPreviewOpen(true);
    } catch (e: any) {
      showError("解析失败：" + e.message);
    } finally {
      setLoading(false);
    }
  };

  const formatImportSuccess = (r: { imported: { world_settings: number; factions: number; faction_relationships: number; character_relationships: number; characters: number; foreshadows: number; outlines: number; monsters: number } }) => {
    return `导入完成：世界观+${r.imported.world_settings} 势力+${r.imported.factions} 势力关系+${r.imported.faction_relationships} 人物关系+${r.imported.character_relationships} 角色+${r.imported.characters} 伏笔+${r.imported.foreshadows} 大纲+${r.imported.outlines} 怪物+${r.imported.monsters}`;
  };

  const importFromPreview = async (data: Partial<ImportPreviewData>) => {
    if (!store.currentProject) return;
    setImportPreviewOpen(false);
    setLoading(true);
    try {
      const r = await api.importStructured(store.currentProject.id, data);
      await store.refreshAssets();
      setImportContent("");
      onImportSuccess?.();
      showSuccess(formatImportSuccess(r));
    } catch (e: any) {
      showError("导入失败：" + e.message);
    } finally {
      setLoading(false);
    }
  };

  const importStructured = async (data: object) => {
    if (!store.currentProject) return;
    setLoading(true);
    try {
      const r = await api.importStructured(store.currentProject.id, data);
      await store.refreshAssets();
      onImportSuccess?.();
      showSuccess(formatImportSuccess(r));
    } catch (e: any) {
      showError("导入失败：" + e.message);
    } finally {
      setLoading(false);
    }
  };

  return {
    importContent,
    setImportContent,
    importPreviewOpen,
    setImportPreviewOpen,
    importPreviewData,
    parseDocument,
    parseFile,
    importFromPreview,
    importStructured,
  };
}
