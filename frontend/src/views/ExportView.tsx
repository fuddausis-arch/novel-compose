import { api } from "@/api";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";

interface ExportViewProps {
  projectId?: number;
}

export function ExportView({ projectId }: ExportViewProps) {
  if (!projectId) return null;
  return (
    <Card className="flex-1">
      <CardHeader><CardTitle>导出</CardTitle></CardHeader>
      <CardContent className="space-y-3">
        <p className="text-sm text-muted">导出当前项目全部章节为 TXT 文件。</p>
        <a href={api.exportTxt(projectId)} download target="_blank" rel="noreferrer">
          <Button>下载 TXT</Button>
        </a>
      </CardContent>
    </Card>
  );
}
