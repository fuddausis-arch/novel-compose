import { useState } from "react";
import { api } from "@/api";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { useToast } from "@/hooks/useToast";

interface ExportViewProps {
  projectId?: number;
}

export function ExportView({ projectId }: ExportViewProps) {
  const { showError, showSuccess } = useToast();
  const [exportingBible, setExportingBible] = useState(false);

  const handleExportBible = async () => {
    if (!projectId) return;
    setExportingBible(true);
    try {
      const data = await api.exportBible(projectId);
      const blob = new Blob([JSON.stringify(data, null, 2)], { type: "application/json" });
      const url = URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = url;
      a.download = `bible_${projectId}.json`;
      a.click();
      URL.revokeObjectURL(url);
      showSuccess("项目设定已导出");
    } catch (e: any) {
      showError("导出项目设定失败：" + e.message);
    } finally {
      setExportingBible(false);
    }
  };

  if (!projectId) return null;
  return (
    <Card className="flex-1">
      <CardHeader><CardTitle>导出</CardTitle></CardHeader>
      <CardContent className="space-y-3">
        <div className="space-y-2">
          <p className="text-sm text-muted">导出当前项目全部章节为 TXT 文件。</p>
          <a href={api.exportTxt(projectId)} download target="_blank" rel="noreferrer">
            <Button>下载 TXT</Button>
          </a>
        </div>
        <div className="space-y-2">
          <p className="text-sm text-muted">导出项目设定（角色/世界/大纲/伏笔等）为 JSON 文件。</p>
          <Button onClick={handleExportBible} disabled={exportingBible}>
            {exportingBible ? "导出中…" : "导出项目设定（JSON）"}
          </Button>
        </div>
      </CardContent>
    </Card>
  );
}
