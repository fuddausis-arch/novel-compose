import { useState, useEffect, useCallback } from "react";
import { FileText, Trash2, Eye, RefreshCw } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { useToast } from "@/hooks/useToast";
import { useConfirmDialog } from "@/hooks/useConfirmDialog";
import { api } from "@/api";
import { cn } from "@/lib/utils";

interface ReferenceFile {
  filename: string;
  size: number;
  content_preview: string;
}

interface ReferencesViewProps {
  projectId: number;
}

export function ReferencesView({ projectId }: ReferencesViewProps) {
  const [files, setFiles] = useState<ReferenceFile[]>([]);
  const [loading, setLoading] = useState(false);
  const [dragActive, setDragActive] = useState(false);
  const [selectedFile, setSelectedFile] = useState<File | null>(null);
  const [previewFile, setPreviewFile] = useState<{ filename: string; content: string } | null>(null);
  const { showSuccess, showError } = useToast();
  const { confirm: confirmDelete, dialog: deleteDialog } = useConfirmDialog();

  const loadFiles = useCallback(async () => {
    try {
      const list = await api.listReferences(projectId);
      setFiles(list);
    } catch (e: any) {
      showError("加载参考文件失败：" + e.message);
    }
  }, [projectId, showError]);

  useEffect(() => {
    loadFiles();
  }, [loadFiles]);

  const handleDrag = (e: React.DragEvent) => {
    e.preventDefault();
    e.stopPropagation();
    if (e.type === "dragenter" || e.type === "dragover") {
      setDragActive(true);
    } else if (e.type === "dragleave") {
      setDragActive(false);
    }
  };

  const handleDrop = (e: React.DragEvent) => {
    e.preventDefault();
    e.stopPropagation();
    setDragActive(false);
    if (e.dataTransfer.files && e.dataTransfer.files[0]) {
      setSelectedFile(e.dataTransfer.files[0]);
    }
  };

  const handleFileChange = (e: React.ChangeEvent<HTMLInputElement>) => {
    if (e.target.files && e.target.files[0]) {
      setSelectedFile(e.target.files[0]);
    }
  };

  const handleUpload = async () => {
    if (!selectedFile) return;
    setLoading(true);
    try {
      const result = await api.uploadReference(projectId, selectedFile);
      showSuccess(`已上传参考文件：${result.filename}（${result.char_count} 字符）`);
      setSelectedFile(null);
      await loadFiles();
    } catch (e: any) {
      showError("上传失败：" + e.message);
    } finally {
      setLoading(false);
    }
  };

  const handleDelete = async (filename: string) => {
    const ok = await confirmDelete({
      title: "删除参考文件",
      description: `参考文件「${filename}」将被永久删除。`,
      confirmText: "确认删除",
    });
    if (!ok) return;
    try {
      await api.deleteReference(projectId, filename);
      showSuccess("已删除");
      await loadFiles();
    } catch (e: any) {
      showError("删除失败：" + e.message);
    }
  };

  const handlePreview = async (filename: string) => {
    try {
      const result = await api.getReference(projectId, filename);
      setPreviewFile({ filename: result.filename, content: result.content });
    } catch (e: any) {
      showError("读取失败：" + e.message);
    }
  };

  const formatSize = (bytes: number) => {
    if (bytes < 1024) return `${bytes} B`;
    if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
    return `${(bytes / 1024 / 1024).toFixed(1)} MB`;
  };

  const supportedFormats = [
    ".txt", ".md", ".markdown", ".json", ".csv", ".html", ".htm",
    ".xml", ".yaml", ".yml", ".docx", ".pdf",
  ];

  return (
    <Card className="flex-1 flex flex-col overflow-hidden">
      <CardHeader className="flex-row items-center justify-between">
        <CardTitle>参考文件</CardTitle>
        <Button variant="ghost" size="sm" onClick={loadFiles}>
          <RefreshCw className="w-3.5 h-3.5" />
        </Button>
      </CardHeader>
      <CardContent className="flex-1 flex flex-col gap-3 overflow-hidden">
        <div className="text-xs text-muted">
          上传的文件将持久保存为项目参考资料，在 AI 对话（全局对话模式）中自动注入作为上下文。
          适合存放无法被自动解析的背景资料、设定文档、风格参考等。
        </div>

        {/* 上传区域 */}
        <div
          className={cn(
            "border-2 border-dashed rounded-xl p-4 text-center transition-colors cursor-pointer",
            dragActive ? "border-primary bg-primary/5" : "border-border hover:border-primary/50"
          )}
          onDragEnter={handleDrag}
          onDragLeave={handleDrag}
          onDragOver={handleDrag}
          onDrop={handleDrop}
          onClick={() => document.getElementById("ref-file-upload")?.click()}
        >
          <input
            id="ref-file-upload"
            type="file"
            className="hidden"
            accept={supportedFormats.join(",")}
            onChange={handleFileChange}
          />
          <p className="text-sm text-muted">
            {selectedFile ? `已选择：${selectedFile.name}` : "点击或拖拽文件到此处上传"}
          </p>
        </div>

        {selectedFile && (
          <div className="flex gap-2">
            <Button size="sm" onClick={handleUpload} disabled={loading}>
              {loading ? "上传中…" : "上传"}
            </Button>
            <Button size="sm" variant="ghost" onClick={() => setSelectedFile(null)}>
              取消
            </Button>
          </div>
        )}

        {/* 文件列表 */}
        <div className="flex-1 overflow-y-auto space-y-2">
          {files.length === 0 && (
            <div className="text-xs text-muted text-center py-8">
              暂无参考文件，上传一个试试
            </div>
          )}
          {files.map((f) => (
            <div
              key={f.filename}
              className="flex items-center gap-2 p-2 rounded-lg border border-border hover:bg-foreground/5"
            >
              <FileText className="w-4 h-4 text-muted shrink-0" />
              <div className="flex-1 min-w-0">
                <div className="text-sm font-medium truncate">{f.filename}</div>
                <div className="text-xs text-muted truncate">
                  {formatSize(f.size)} · {f.content_preview.slice(0, 80)}…
                </div>
              </div>
              <Button variant="ghost" size="sm" onClick={() => handlePreview(f.filename)} aria-label={`预览 ${f.filename}`}>
                <Eye className="w-3.5 h-3.5" />
              </Button>
              <Button variant="ghost" size="sm" onClick={() => handleDelete(f.filename)} aria-label={`删除 ${f.filename}`}>
                <Trash2 className="w-3.5 h-3.5 text-danger" />
              </Button>
            </div>
          ))}
        </div>

        {/* 预览弹窗 */}
        {previewFile && (
          <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/50" onClick={() => setPreviewFile(null)}>
            <div className="bg-background rounded-xl shadow-xl w-[92vw] max-w-[600px] max-h-[80vh] flex flex-col" onClick={(e) => e.stopPropagation()}>
              <div className="flex items-center justify-between p-3 border-b border-border">
                <span className="text-sm font-medium">{previewFile.filename}</span>
                <Button variant="ghost" size="sm" onClick={() => setPreviewFile(null)}>关闭</Button>
              </div>
              <div className="flex-1 overflow-y-auto p-3">
                <pre className="text-xs whitespace-pre-wrap break-words">{previewFile.content}</pre>
              </div>
            </div>
          </div>
        )}
      </CardContent>
      {deleteDialog}
    </Card>
  );
}
