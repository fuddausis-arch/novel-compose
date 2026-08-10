import { useEffect, useState } from "react";
import { FolderOpen, Trash2, Eye, Loader2 } from "lucide-react";
import { api } from "@/api";
import { useAppStore } from "@/store";
import { useToast } from "@/hooks/useToast";
import { useConfirmDialog } from "@/hooks/useConfirmDialog";
import type { ImportedChapterDetail } from "@/types";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";

export function ImportFolderView() {
  const store = useAppStore();
  const { showSuccess, showError } = useToast();
  const { confirm: confirmDelete, dialog: deleteDialog } = useConfirmDialog();

  const project = store.currentProject;
  const importedChapters = store.importedChapters;

  const [folderPath, setFolderPath] = useState("");
  const [importing, setImporting] = useState(false);
  const [detailOpen, setDetailOpen] = useState(false);
  const [detail, setDetail] = useState<ImportedChapterDetail | null>(null);
  const [detailLoading, setDetailLoading] = useState(false);

  useEffect(() => {
    if (project) {
      store.refreshImportedChapters().catch(() => {});
    }
  }, [project?.id]);

  if (!project) {
    return (
      <div className="flex-1 flex items-center justify-center text-muted text-sm">
        请先选择或创建一个项目
      </div>
    );
  }

  const handleImport = async () => {
    if (!folderPath.trim()) {
      showError("请填写文件夹路径");
      return;
    }
    setImporting(true);
    try {
      const result = await api.importFolder(project.id, folderPath.trim());
      showSuccess(`已导入 ${result.imported_count} 章${result.failed_count > 0 ? `，${result.failed_count} 章失败` : ""}`);
      setFolderPath("");
      await store.refreshImportedChapters();
    } catch (err: any) {
      showError("导入失败：" + (err?.message || "未知错误"));
    } finally {
      setImporting(false);
    }
  };

  const handleViewDetail = async (chapterNum: number) => {
    setDetailLoading(true);
    setDetailOpen(true);
    setDetail(null);
    try {
      const d = await api.getImportedChapter(project.id, chapterNum);
      setDetail(d);
    } catch (err: any) {
      showError("加载详情失败：" + (err?.message || "未知错误"));
      setDetailOpen(false);
    } finally {
      setDetailLoading(false);
    }
  };

  const handleDelete = async (id: number, chapterNum: number, title: string) => {
    const ok = await confirmDelete({
      title: "删除导入章节",
      description: `确定删除第 ${chapterNum} 章「${title}」的导入记录吗？此操作不可恢复。`,
      confirmText: "删除",
      cancelText: "取消",
      variant: "danger",
    });
    if (!ok) return;
    try {
      await api.deleteImportedChapter(id);
      await store.refreshImportedChapters();
      showSuccess("已删除");
    } catch (err: any) {
      showError("删除失败：" + (err?.message || "未知错误"));
    }
  };

  const renderMeta = (metaInfo: string) => {
    if (!metaInfo || !metaInfo.trim()) return null;
    return (
      <div className="text-sm text-foreground whitespace-pre-wrap break-words">
        {metaInfo}
      </div>
    );
  };

  return (
    <div className="flex-1 flex flex-col gap-3 min-h-0 overflow-hidden">
      <Card>
        <CardHeader>
          <CardTitle className="flex items-center gap-2">
            <FolderOpen className="h-4 w-4 text-primary" />
            导入文件夹
          </CardTitle>
        </CardHeader>
        <CardContent className="space-y-3">
          <div className="text-xs text-muted">
            输入本地文件夹路径，后端会扫描其中的章节文件并批量导入。导入后可在下方查看每章的元信息、章纲、细纲和套壳标注。
          </div>
          <div className="flex gap-2">
            <Input
              placeholder="如：C:\novel\chapters 或 /home/user/novel/chapters"
              value={folderPath}
              onChange={(e) => setFolderPath(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === "Enter" && !importing) handleImport();
              }}
            />
            <Button variant="primary" onClick={handleImport} disabled={importing || !folderPath.trim()}>
              {importing ? (
                <>
                  <Loader2 className="h-3.5 w-3.5 mr-1 animate-spin" /> 导入中…
                </>
              ) : (
                "导入"
              )}
            </Button>
          </div>
        </CardContent>
      </Card>

      <Card className="flex-1 flex flex-col overflow-hidden">
        <CardHeader>
          <CardTitle className="flex items-center gap-2 text-sm">
            已导入章节
            <Badge>{importedChapters.length}</Badge>
          </CardTitle>
        </CardHeader>
        <CardContent className="flex-1 overflow-y-auto space-y-2">
          {importedChapters.length === 0 ? (
            <div className="text-center text-sm text-muted py-10">
              暂无导入章节，请在上方输入文件夹路径进行导入。
            </div>
          ) : (
            importedChapters
              .slice()
              .sort((a, b) => a.chapter_order - b.chapter_order)
              .map((c) => (
                <div
                  key={c.id}
                  className="flex items-center gap-3 rounded-xl border border-border bg-surface p-3 hover:bg-foreground/5 transition-colors"
                >
                  <div className="flex h-8 w-8 shrink-0 items-center justify-center rounded-lg bg-primary-muted text-xs font-bold text-primary">
                    {c.chapter_order}
                  </div>
                  <div className="flex-1 min-w-0">
                    <div className="text-sm font-medium text-foreground truncate">
                      {c.title || `第 ${c.chapter_order} 章`}
                    </div>
                    <div className="text-xs text-muted truncate">
                      来源：{c.source_filename}
                    </div>
                  </div>
                  <div className="flex items-center gap-1 shrink-0">
                    <Button
                      variant="ghost"
                      size="sm"
                      onClick={() => handleViewDetail(c.chapter_order)}
                      aria-label="查看详情"
                    >
                      <Eye className="h-3.5 w-3.5" />
                    </Button>
                    <Button
                      variant="ghost"
                      size="sm"
                      onClick={() => handleDelete(c.id, c.chapter_order, c.title)}
                      aria-label="删除"
                    >
                      <Trash2 className="h-3.5 w-3.5 text-danger" />
                    </Button>
                  </div>
                </div>
              ))
          )}
        </CardContent>
      </Card>

      <Dialog open={detailOpen} onOpenChange={setDetailOpen}>
        <DialogContent className="max-w-2xl">
          <DialogHeader>
            <DialogTitle>
              {detail ? `第 ${detail.chapter_order} 章 · ${detail.title}` : "章节详情"}
            </DialogTitle>
          </DialogHeader>
          {detailLoading ? (
            <div className="flex items-center justify-center py-10 text-sm text-muted">
              <Loader2 className="h-4 w-4 mr-2 animate-spin" /> 加载中…
            </div>
          ) : detail ? (
            <div className="space-y-4 max-h-[70vh] overflow-y-auto">
              <div className="space-y-1">
                <div className="text-xs font-semibold text-muted uppercase tracking-wide">来源文件</div>
                <div className="text-sm text-foreground break-all">{detail.source_filename}</div>
              </div>

              {detail.meta_info && detail.meta_info.trim() && (
                <div className="space-y-1">
                  <div className="text-xs font-semibold text-muted uppercase tracking-wide">元信息</div>
                  <div className="rounded-xl border border-border bg-surface p-3">
                    {renderMeta(detail.meta_info)}
                  </div>
                </div>
              )}

              {detail.chapter_outline && (
                <div className="space-y-1">
                  <div className="text-xs font-semibold text-muted uppercase tracking-wide">章纲</div>
                  <div className="rounded-xl border border-border bg-surface p-3 text-sm text-foreground whitespace-pre-wrap">
                    {detail.chapter_outline}
                  </div>
                </div>
              )}

              {detail.detail_outline && (
                <div className="space-y-1">
                  <div className="text-xs font-semibold text-muted uppercase tracking-wide">细纲</div>
                  <div className="rounded-xl border border-border bg-surface p-3 text-sm text-foreground whitespace-pre-wrap">
                    {detail.detail_outline}
                  </div>
                </div>
              )}

              {detail.shell_annotation && (
                <div className="space-y-1">
                  <div className="text-xs font-semibold text-muted uppercase tracking-wide">套壳标注</div>
                  <div className="rounded-xl border border-warning/30 bg-warning/5 p-3 text-sm text-foreground whitespace-pre-wrap">
                    {detail.shell_annotation}
                  </div>
                </div>
              )}

              {!detail.chapter_outline && !detail.detail_outline && !detail.shell_annotation &&
                (!detail.meta_info || !detail.meta_info.trim()) && (
                  <div className="text-center text-sm text-muted py-6">
                    该章节暂无详细信息
                  </div>
                )}
            </div>
          ) : (
            <div className="text-center text-sm text-muted py-6">无数据</div>
          )}
          <div className="flex justify-end pt-2">
            <Button variant="outline" size="sm" onClick={() => setDetailOpen(false)}>
              关闭
            </Button>
          </div>
        </DialogContent>
      </Dialog>

      {deleteDialog}
    </div>
  );
}
