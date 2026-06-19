import { useState } from "react";
import { cn } from "@/lib/utils";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Textarea } from "@/components/ui/textarea";
import { useToast } from "@/hooks/useToast";

interface ImportViewProps {
  content: string;
  setContent: (content: string) => void;
  onImport: () => void;
  onImportFile: (file: File) => void;
  onImportStructured: (data: object) => Promise<void>;
  loading: boolean;
}

const JSON_EXAMPLE = `{
  "world_settings": [
    {
      "category": "修炼体系",
      "title": "掌天瓶",
      "content": "可催熟灵药的神秘小瓶，来历不凡",
      "order": 1
    }
  ],
  "characters": [
    {
      "name": "韩立",
      "role": "主角",
      "personality": "谨慎沉稳",
      "motivation": "追求长生",
      "current_location": "黄枫谷",
      "current_emotion": "平静",
      "known_info": "凡人出身",
      "background": "山村小子",
      "arc": "从凡人到仙人的成长"
    }
  ],
  "foreshadows": [
    {
      "foreshadow_id": "S-001",
      "tier": "long",
      "description": "掌天瓶的真正来历",
      "plant_chapter": 1,
      "planned_resolve_chapter": 300,
      "status": "pending"
    }
  ],
  "outlines": [
    {
      "order": 1,
      "level": "chapter",
      "title": "第1章 山村少年",
      "summary": "韩立意外获得掌天瓶",
      "act": "开端",
      "strand": "quest"
    }
  ]
}`;

export function ImportView({ content, setContent, onImport, onImportFile, onImportStructured, loading }: ImportViewProps) {
  const [activeTab, setActiveTab] = useState<"document" | "structured">("document");
  const [dragActive, setDragActive] = useState(false);
  const [selectedFile, setSelectedFile] = useState<File | null>(null);
  const [jsonContent, setJsonContent] = useState(JSON_EXAMPLE);
  const [jsonError, setJsonError] = useState<string | null>(null);
  const { showSuccess, showError } = useToast();

  const supportedFormats = [
    ".txt", ".md", ".markdown", ".json", ".csv", ".html", ".htm",
    ".xml", ".yaml", ".yml", ".docx", ".pdf",
    ".png", ".jpg", ".jpeg", ".webp", ".gif", ".bmp",
  ];

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

  const handleFileImport = async () => {
    if (!selectedFile) return;
    await onImportFile(selectedFile);
    setSelectedFile(null);
  };

  const readLocalTextFile = (file: File) => {
    const reader = new FileReader();
    reader.onload = (e) => {
      setContent(String(e.target?.result || ""));
    };
    reader.readAsText(file);
  };

  const handleStructuredImport = async () => {
    setJsonError(null);
    let data: object;
    try {
      data = JSON.parse(jsonContent);
    } catch (e: any) {
      setJsonError("JSON 格式错误：" + e.message);
      return;
    }
    try {
      await onImportStructured(data);
      showSuccess("结构化导入完成");
    } catch (e: any) {
      showError("导入失败：" + e.message);
    }
  };

  const handleLoadExample = () => setJsonContent(JSON_EXAMPLE);

  return (
    <Card className="flex-1 flex flex-col overflow-hidden">
      <CardHeader>
        <CardTitle>导入设定</CardTitle>
      </CardHeader>
      <CardContent className="flex-1 flex flex-col gap-3 overflow-hidden">
        <div className="flex gap-2 border-b border-border pb-2">
          <Button
            variant={activeTab === "document" ? "default" : "ghost"}
            size="sm"
            onClick={() => setActiveTab("document")}
          >
            自然语言导入
          </Button>
          <Button
            variant={activeTab === "structured" ? "default" : "ghost"}
            size="sm"
            onClick={() => setActiveTab("structured")}
          >
            JSON 批量导入
          </Button>
        </div>

        {activeTab === "document" && (<> 
        <div className="flex gap-2 text-xs text-muted">
          <span className="font-medium text-foreground">支持格式：</span>
          <span>文本文档（txt/md/json/csv/html/xml/docx/pdf）</span>
          <span>·</span>
          <span>图片（png/jpg/webp/gif，需视觉模型）</span>
        </div>

        <div
          className={cn(
            "border-2 border-dashed rounded-xl p-6 text-center transition-colors cursor-pointer",
            dragActive ? "border-primary bg-primary/5" : "border-border hover:border-primary/50"
          )}
          onDragEnter={handleDrag}
          onDragLeave={handleDrag}
          onDragOver={handleDrag}
          onDrop={handleDrop}
          onClick={() => document.getElementById("file-upload")?.click()}
        >
          <input
            id="file-upload"
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
            <Button size="sm" onClick={handleFileImport} disabled={loading}>
              {loading ? "AI 解析中…" : "上传并解析"}
            </Button>
            <Button size="sm" variant="ghost" onClick={() => { setSelectedFile(null); setContent(""); }}>
              清除
            </Button>
            {selectedFile.type.startsWith("text/") && (
              <Button size="sm" variant="ghost" onClick={() => readLocalTextFile(selectedFile)}>
                读取到文本框
              </Button>
            )}
          </div>
        )}

        <div className="text-xs text-muted text-center">— 或 —</div>

        <Textarea
          className="flex-1 resize-none"
          value={content}
          onChange={(e) => setContent(e.target.value)}
          placeholder="在此粘贴世界观、角色介绍、大纲等文档…"
        />
        <Button onClick={onImport} disabled={loading || !content.trim()}>
          {loading ? "AI 解析中…" : "解析并预览"}
        </Button>
        </>)}

        {activeTab === "structured" && (
          <div className="flex-1 flex flex-col gap-3 overflow-hidden">
            <div className="flex items-center justify-between">
              <span className="text-xs text-muted">粘贴符合 schema 的 JSON，可批量导入角色、伏笔、大纲。</span>
              <Button variant="ghost" size="sm" onClick={handleLoadExample}>加载示例</Button>
            </div>
            <Textarea
              className="flex-1 resize-none font-mono text-xs"
              value={jsonContent}
              onChange={(e) => { setJsonContent(e.target.value); setJsonError(null); }}
              placeholder={`{"world_settings":[], "characters":[], "foreshadows":[], "outlines":[]}`}
            />
            {jsonError && <div className="text-xs text-danger">{jsonError}</div>}
            <Button onClick={handleStructuredImport} disabled={loading || !jsonContent.trim()}>
              {loading ? "导入中…" : "批量导入"}
            </Button>
          </div>
        )}
      </CardContent>
    </Card>
  );
}
