import { useEffect } from "react";
import { FileText, Trash2 } from "lucide-react";
import { useAppStore } from "@/store";
import { api } from "@/api";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { useToast } from "@/hooks/useToast";
import { useConfirmDialog } from "@/hooks/useConfirmDialog";

export function SummariesView() {
  const project = useAppStore((s) => s.currentProject);
  const summaries = useAppStore((s) => s.summaries);
  const refreshSummaries = useAppStore((s) => s.refreshSummaries);
  const { showSuccess, showError } = useToast();
  const { confirm: confirmDelete, dialog: deleteDialog } = useConfirmDialog();

  useEffect(() => {
    const load = async () => {
      if (!project) return;
      try {
        await refreshSummaries();
      } catch (e: any) {
        showError("加载摘要失败：" + e.message);
      }
    };
    load();
  }, [project?.id]);

  if (!project) {
    return (
      <div className="flex h-full items-center justify-center text-muted">
        请先选择一个项目
      </div>
    );
  }

  const handleDelete = async (chapter: number) => {
    const confirmed = await confirmDelete({
      title: "删除章节摘要",
      description: `确定删除第 ${chapter} 章摘要吗？此操作不可恢复。`,
      confirmText: "删除",
      cancelText: "取消",
      variant: "danger",
    });
    if (!confirmed) return;
    try {
      await api.deleteSummary(project.id, chapter);
      await refreshSummaries();
      showSuccess("摘要已删除");
    } catch (e: any) {
      showError("删除失败：" + e.message);
    }
  };

  return (
    <div className="space-y-6 p-6">
      <div className="flex items-center justify-between">
        <h1 className="text-2xl font-bold">章节摘要</h1>
        <Button variant="outline" onClick={refreshSummaries}>
          刷新
        </Button>
      </div>

      {summaries.length === 0 ? (
        <Card>
          <CardContent className="py-12 text-center text-muted">
            暂无章节摘要。提交章节后会自动生成摘要。
          </CardContent>
        </Card>
      ) : (
        <div className="grid grid-cols-1 gap-4">
          {summaries.map((s) => (
            <Card key={s.chapter}>
              <CardHeader className="pb-2">
                <div className="flex items-center justify-between">
                  <CardTitle className="flex items-center gap-2 text-base">
                    <FileText className="h-4 w-4" />
                    第 {s.chapter} 章 · {s.title || "未命名"}
                  </CardTitle>
                  <div className="flex items-center gap-2">
                    <Badge>{s.word_count} 字</Badge>
                    <Button variant="ghost" size="sm" onClick={() => handleDelete(s.chapter)}>
                      <Trash2 className="h-4 w-4 text-danger" />
                    </Button>
                  </div>
                </div>
              </CardHeader>
              <CardContent>
                <p className="text-sm text-muted whitespace-pre-wrap">{s.core_events || "无核心事件记录"}</p>
              </CardContent>
            </Card>
          ))}
        </div>
      )}
      {deleteDialog}
    </div>
  );
}
