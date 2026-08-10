import { useState } from "react";
import { AppLayout } from "@/components/layout/AppLayout";
import { ImportView } from "@/views/ImportView";
import { useCurrentProject } from "@/hooks/useCurrentProject";
import { useAppStore } from "@/store";
import { api } from "@/api";
import type { ImportPreviewData } from "@/types";

export default function ImportPage() {
  const { project } = useCurrentProject();
  const refreshAssets = useAppStore((s) => s.refreshAssets);
  const [content, setContent] = useState("");
  const [loading, setLoading] = useState(false);

  if (!project) return null;

  // 解析文本（不入库），返回预览数据
  const handleParseContent = async (text: string): Promise<ImportPreviewData> => {
    setLoading(true);
    try {
      return await api.parseDocument(project.id, text);
    } finally {
      setLoading(false);
    }
  };

  // 解析文件（不入库），返回预览数据
  const handleParseFile = async (file: File): Promise<ImportPreviewData> => {
    setLoading(true);
    try {
      return await api.parseFile(project.id, file);
    } finally {
      setLoading(false);
    }
  };

  // 确认导入：把预览数据（已勾选过滤）入库
  const handleConfirmImport = async (data: ImportPreviewData) => {
    setLoading(true);
    try {
      await api.importStructured(project.id, data);
      await refreshAssets();
    } finally {
      setLoading(false);
    }
  };

  // JSON 批量导入（直接入库，用户自己手写的结构化数据）
  const handleImportStructured = async (data: object) => {
    setLoading(true);
    try {
      await api.importStructured(project.id, data);
      await refreshAssets();
    } finally {
      setLoading(false);
    }
  };

  // AI 扫描文件夹导入
  const handleScanFolder = async (folderPath: string, overwrite: boolean) => {
    setLoading(true);
    try {
      return await api.scanFolder(project.id, folderPath, overwrite);
    } finally {
      setLoading(false);
    }
  };

  return (
    <AppLayout>
      <div className="flex h-full flex-col overflow-hidden bg-background">
        <header className="flex items-center justify-between border-b border-border px-6 py-4">
          <h1 className="text-xl font-bold text-foreground">导入设定</h1>
        </header>
        <div className="flex-1 overflow-y-auto p-6">
          <ImportView
            content={content}
            setContent={setContent}
            onParseContent={handleParseContent}
            onParseFile={handleParseFile}
            onConfirmImport={handleConfirmImport}
            onImportStructured={handleImportStructured}
            onScanFolder={handleScanFolder}
            loading={loading}
          />
        </div>
      </div>
    </AppLayout>
  );
}
