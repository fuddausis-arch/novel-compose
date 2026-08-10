import { useState, useMemo } from "react";
import { cn } from "@/lib/utils";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Textarea } from "@/components/ui/textarea";
import { useToast } from "@/hooks/useToast";
import { ChevronDown, ChevronRight, X, Check } from "lucide-react";
import type { ImportPreviewData } from "@/types";

interface ImportViewProps {
  content: string;
  setContent: (content: string) => void;
  onParseContent: (content: string) => Promise<ImportPreviewData>;
  onParseFile: (file: File) => Promise<ImportPreviewData>;
  onConfirmImport: (data: ImportPreviewData) => Promise<void>;
  onImportStructured: (data: object) => Promise<void>;
  onScanFolder: (folderPath: string, overwrite: boolean) => Promise<{
    total_files: number; extracted_files: number; failed_files: number; merged_chars: number;
    imported: Record<string, number>;
    imported_items: Record<string, any[]>;
    extracted_file_list: { path: string; chars: number }[];
    failed: { path: string; error: string }[];
  }>;
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

// ── 预览面板：每个类别如何展示关键字段 ──
const SECTION_META: { key: keyof ImportPreviewData; label: string; primary: string; secondary: string[] }[] = [
  { key: "characters", label: "角色", primary: "name", secondary: ["role", "personality", "motivation"] },
  { key: "world_settings", label: "世界设定", primary: "title", secondary: ["category", "content"] },
  { key: "factions", label: "势力", primary: "name", secondary: ["type", "tier", "description"] },
  { key: "foreshadows", label: "伏笔", primary: "foreshadow_id", secondary: ["tier", "description", "status"] },
  { key: "outlines", label: "大纲", primary: "title", secondary: ["level", "summary", "order"] },
  { key: "monsters", label: "怪物", primary: "name", secondary: ["type", "description"] },
  { key: "instances", label: "副本", primary: "name", secondary: ["instance_type", "objective", "description"] },
  { key: "faction_relationships", label: "势力关系", primary: "relation_type", secondary: ["source_faction_id", "target_faction_id", "description"] },
  { key: "character_relationships", label: "角色关系", primary: "relation_type", secondary: ["source_character", "target_character", "description"] },
];

const SCAN_CAT_LABELS: Record<string, string> = {
  world_settings: "世界设定",
  characters: "角色",
  factions: "势力",
  faction_relationships: "势力关系",
  character_relationships: "角色关系",
  foreshadows: "伏笔",
  outlines: "大纲",
  monsters: "怪物",
  instances: "副本",
};

function renderValue(v: unknown): string {
  if (v === undefined || v === null || v === "") return "-";
  if (typeof v === "string" || typeof v === "number" || typeof v === "boolean") return String(v);
  return JSON.stringify(v);
}

export function ImportView({ content, setContent, onParseContent, onParseFile, onConfirmImport, onImportStructured, onScanFolder, loading }: ImportViewProps) {
  const [activeTab, setActiveTab] = useState<"document" | "structured" | "folder">("document");
  const [dragActive, setDragActive] = useState(false);
  const [selectedFile, setSelectedFile] = useState<File | null>(null);
  const [jsonContent, setJsonContent] = useState(JSON_EXAMPLE);
  const [jsonError, setJsonError] = useState<string | null>(null);
  const { showSuccess, showError } = useToast();

  // 扫描文件夹状态
  const [folderPath, setFolderPath] = useState("");
  const [overwriteMode, setOverwriteMode] = useState(false);
  const [scanResult, setScanResult] = useState<{
    total_files: number; extracted_files: number; failed_files: number; merged_chars: number;
    imported: Record<string, number>;
    imported_items: Record<string, { name?: string; title?: string; role?: string; category?: string; type?: string; order?: number; level?: string; description?: string; source_character?: string; target_character?: string; relation_type?: string; species?: string }[]>;
    extracted_file_list: { path: string; chars: number }[];
    failed: { path: string; error: string }[];
  } | null>(null);

  // 预览状态
  const [previewData, setPreviewData] = useState<ImportPreviewData | null>(null);
  const [previewSource, setPreviewSource] = useState<"text" | "file" | null>(null);
  // 勾选状态：每个类别一个 boolean 数组，true=选中导入
  const [selected, setSelected] = useState<Record<string, boolean[]>>({});
  const [expanded, setExpanded] = useState<Set<string>>(new Set());

  const supportedFormats = [
    ".txt", ".md", ".markdown", ".json", ".csv", ".html", ".htm",
    ".xml", ".yaml", ".yml", ".docx", ".pdf",
    ".png", ".jpg", ".jpeg", ".webp", ".gif", ".bmp",
  ];
  const textExtensions = ["txt", "md", "markdown", "json", "csv", "html", "xml", "yaml", "yml", "log"];
  const isTextFile = selectedFile ? textExtensions.some((ext) => selectedFile.name.toLowerCase().endsWith("." + ext)) : false;

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

  const readLocalTextFile = (file: File) => {
    const reader = new FileReader();
    reader.onload = (e) => {
      setContent(String(e.target?.result || ""));
    };
    reader.readAsText(file);
  };

  // ── 解析文本 -> 预览 ──
  const handleParseText = async () => {
    if (!content.trim()) {
      showError("请输入文档内容");
      return;
    }
    try {
      const data = await onParseContent(content);
      setPreviewData(data);
      setPreviewSource("text");
      initSelection(data);
    } catch (e: any) {
      showError("解析失败：" + e.message);
    }
  };

  // ── 扫描文件夹 -> AI 识别导入 ──
  const handleScanFolder = async () => {
    if (!folderPath.trim()) {
      showError("请输入文件夹路径");
      return;
    }
    setScanResult(null);
    try {
      const result = await onScanFolder(folderPath.trim(), overwriteMode);
      setScanResult(result);
      const total = Object.values(result.imported).reduce((a: number, b: number) => a + b, 0);
      showSuccess(`扫描完成：${result.extracted_files} 个文件，导入 ${total} 条设定`);
    } catch (e: any) {
      showError("扫描失败：" + e.message);
    }
  };

  // ── 解析文件 -> 预览 ──
  const handleParseFile = async () => {
    if (!selectedFile) return;
    try {
      const data = await onParseFile(selectedFile);
      setPreviewData(data);
      setPreviewSource("file");
      initSelection(data);
    } catch (e: any) {
      showError("解析失败：" + e.message);
    }
  };

  // 初始化勾选：默认全选
  const initSelection = (data: ImportPreviewData) => {
    const sel: Record<string, boolean[]> = {};
    for (const meta of SECTION_META) {
      const arr = (data as any)[meta.key] as any[] | undefined;
      sel[meta.key] = (arr || []).map(() => true);
    }
    // 金手指是单对象，单独用 boolean
    sel["golden_finger"] = data.golden_finger ? [true] : [];
    setSelected(sel);
    setExpanded(new Set());
  };

  const toggleItem = (sectionKey: string, idx: number) => {
    setSelected((prev) => {
      const arr = prev[sectionKey] ? [...prev[sectionKey]] : [];
      arr[idx] = !arr[idx];
      return { ...prev, [sectionKey]: arr };
    });
  };

  const toggleSectionAll = (sectionKey: string, value: boolean) => {
    setSelected((prev) => {
      const arr = prev[sectionKey] ? [...prev[sectionKey]].map(() => value) : [];
      return { ...prev, [sectionKey]: arr };
    });
  };

  const toggleExpand = (key: string) => {
    setExpanded((prev) => {
      const next = new Set(prev);
      if (next.has(key)) next.delete(key);
      else next.add(key);
      return next;
    });
  };

  // 统计总数 / 选中数
  const stats = useMemo(() => {
    let total = 0, selectedCount = 0;
    if (previewData) {
      for (const meta of SECTION_META) {
        const arr = (previewData as any)[meta.key] as any[] | undefined;
        if (arr) {
          total += arr.length;
          const selArr = selected[meta.key] || [];
          selectedCount += selArr.filter(Boolean).length;
        }
      }
      // 金手指算 1 条
      if (previewData.golden_finger) {
        total += 1;
        if (selected["golden_finger"]?.[0]) selectedCount += 1;
      }
    }
    return { total, selectedCount };
  }, [previewData, selected]);

  // ── 确认导入：只导入勾选项 ──
  const handleConfirm = async () => {
    if (!previewData) return;
    // 构造过滤后的数据
    const filtered: any = {};
    for (const meta of SECTION_META) {
      const arr = (previewData as any)[meta.key] as any[] | undefined;
      const selArr = selected[meta.key] || [];
      if (arr) {
        filtered[meta.key] = arr.filter((_, i) => selArr[i]);
      } else {
        filtered[meta.key] = [];
      }
    }
    // 金手指：只有勾选才传给后端
    filtered.golden_finger = selected["golden_finger"]?.[0] ? previewData.golden_finger : null;
    try {
      await onConfirmImport(filtered);
      showSuccess("已导入到设定库");
      setPreviewData(null);
      setPreviewSource(null);
      setSelected({});
      setContent("");
      setSelectedFile(null);
    } catch (e: any) {
      showError("导入失败：" + e.message);
    }
  };

  const handleCancel = () => {
    setPreviewData(null);
    setPreviewSource(null);
    setSelected({});
    setExpanded(new Set());
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
    <>
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
            <Button
              variant={activeTab === "folder" ? "default" : "ghost"}
              size="sm"
              onClick={() => setActiveTab("folder")}
            >
              文件夹扫描
            </Button>
          </div>

          {activeTab === "document" && (
          <>
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
              <div className="flex flex-col gap-1">
                <div className="flex gap-2">
                  <Button size="sm" onClick={handleParseFile} disabled={loading}>
                    {loading ? "AI 解析中…" : "预览解析结果"}
                  </Button>
                  <Button size="sm" variant="ghost" onClick={() => { setSelectedFile(null); setContent(""); }}>
                    清除
                  </Button>
                  {isTextFile && (
                    <Button size="sm" variant="ghost" onClick={() => readLocalTextFile(selectedFile)}>
                      读取到文本框
                    </Button>
                  )}
                </div>
                <p className="text-xs text-muted">先预览解析结果，可勾选/取消条目后再导入</p>
              </div>
            )}

            <div className="text-xs text-muted text-center">- 或 -</div>

            <Textarea
              className="flex-1 resize-none"
              value={content}
              onChange={(e) => setContent(e.target.value)}
              placeholder="在此粘贴世界观、角色介绍、大纲等文档…"
            />
            <div className="flex flex-col gap-1">
              <Button onClick={handleParseText} disabled={loading || !content.trim()}>
                {loading ? "AI 解析中…" : "预览解析结果"}
              </Button>
              <p className="text-xs text-muted">先预览解析结果，可勾选/取消条目后再导入</p>
            </div>
          </>
          )}

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

          {activeTab === "folder" && (
            <div className="flex-1 flex flex-col gap-3">
              <div className="text-xs text-muted">
                输入文件夹路径，AI 会自动递归扫描所有文件（txt/md/json/csv/html/docx/pdf），
                识别角色、世界观、势力、伏笔、大纲等设定并导入设定库。
              </div>
              <div className="flex gap-2">
                <input
                  type="text"
                  className="flex-1 rounded-lg border border-border bg-surface px-3 py-2 text-sm text-foreground placeholder:text-muted"
                  placeholder="例如：D:\我的小说设定"
                  value={folderPath}
                  onChange={(e) => setFolderPath(e.target.value)}
                  onKeyDown={(e) => { if (e.key === "Enter" && !loading) handleScanFolder(); }}
                />
                <Button onClick={handleScanFolder} disabled={loading || !folderPath.trim()}>
                  {loading ? "AI 扫描中…" : "开始扫描"}
                </Button>
              </div>
              <label className="flex items-center gap-2 text-xs text-muted cursor-pointer select-none">
                <input
                  type="checkbox"
                  checked={overwriteMode}
                  onChange={(e) => setOverwriteMode(e.target.checked)}
                  className="rounded border-border"
                />
                覆盖更新模式（已存在的设定会被更新 summary/能力等字段，不会重复创建）
              </label>

              {scanResult && (
                <div className="rounded-xl border border-border bg-surface p-4 space-y-3 overflow-y-auto">
                  <div className="text-sm font-medium text-foreground">扫描结果</div>
                  <div className="grid grid-cols-2 gap-2 text-xs">
                    <div className="text-muted">扫描文件：<span className="text-foreground font-medium">{scanResult.total_files}</span></div>
                    <div className="text-muted">提取成功：<span className="text-foreground font-medium">{scanResult.extracted_files}</span></div>
                    <div className="text-muted">合并字符：<span className="text-foreground font-medium">{scanResult.merged_chars}</span></div>
                    <div className="text-muted">失败文件：<span className="text-foreground font-medium">{scanResult.failed_files}</span></div>
                  </div>

                  {/* 提取的文件列表 */}
                  {scanResult.extracted_file_list.length > 0 && (
                    <div className="border-t border-border pt-3">
                      <div className="text-xs font-medium text-foreground mb-2">已扫描文件</div>
                      <div className="space-y-1 max-h-32 overflow-y-auto">
                        {scanResult.extracted_file_list.map((f, i) => (
                          <div key={i} className="text-xs text-muted flex justify-between">
                            <span className="text-foreground">{f.path}</span>
                            <span>{f.chars} 字</span>
                          </div>
                        ))}
                      </div>
                    </div>
                  )}

                  {/* 提取的具体内容 */}
                  {scanResult.imported_items && Object.entries(scanResult.imported_items).map(([cat, items]) =>
                    items.length > 0 && (
                      <div key={cat} className="border-t border-border pt-3">
                        <div className="text-xs font-medium text-foreground mb-2">
                          {SCAN_CAT_LABELS[cat] || cat} <span className="text-muted">({items.length})</span>
                        </div>
                        <div className="space-y-2">
                          {items.map((item: any, i: number) => {
                            const mainTitle = item.name || item.title || (item.source_character ? `${item.source_character} -> ${item.target_character}` : "");
                            const longFields = ["summary", "content", "description", "background", "personality", "motivation", "arc", "history", "goals", "hierarchy", "territories", "resources", "appearance", "secrets", "behavior", "weaknesses", "lore", "core_ability", "limitation", "growth", "origin", "objective", "mechanism", "rewards", "cost"];
                            const subFields = Object.entries(item)
                              .filter(([k, v]) => !longFields.includes(k) && v != null && v !== "" && v !== 0)
                              .slice(0, 6);
                            const detailFields = Object.entries(item)
                              .filter(([k, v]) => longFields.includes(k) && v != null && v !== "");
                            return (
                              <div key={i} className="rounded-lg bg-foreground/5 p-2 border-l-2 border-primary/30">
                                {mainTitle && <div className="text-xs font-medium text-foreground">{i + 1}. {mainTitle}</div>}
                                {subFields.length > 0 && (
                                  <div className="text-xs text-muted mt-0.5">
                                    {subFields.map(([k, v]) => <span key={k} className="mr-2">{k}: {String(v)}</span>)}
                                  </div>
                                )}
                                {detailFields.map(([k, v]) => (
                                  <div key={k} className="text-xs text-muted mt-1">
                                    <span className="text-foreground/70">{k}: </span>
                                    <span>{String(v)}</span>
                                  </div>
                                ))}
                              </div>
                            );
                          })}
                        </div>
                      </div>
                    )
                  )}

                  {/* 失败文件 */}
                  {scanResult.failed.length > 0 && (
                    <div className="border-t border-border pt-3">
                      <div className="text-xs font-medium text-foreground mb-1">失败文件</div>
                      <div className="space-y-1 max-h-32 overflow-y-auto">
                        {scanResult.failed.map((f, i) => (
                          <div key={i} className="text-xs text-danger">
                            {f.path}: {f.error}
                          </div>
                        ))}
                      </div>
                    </div>
                  )}
                </div>
              )}
            </div>
          )}
        </CardContent>
      </Card>

      {/* 预览弹窗 */}
      {previewData && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/50 backdrop-blur-sm">
          <div className="w-[92vw] max-w-[800px] max-h-[85vh] bg-background border border-border rounded-2xl shadow-2xl flex flex-col">
            {/* 头部 */}
            <div className="flex items-center justify-between px-5 py-4 border-b border-border">
              <div>
                <h3 className="text-sm font-semibold">
                  预览解析结果{previewSource === "file" && selectedFile ? ` · ${selectedFile.name}` : ""}
                </h3>
                <p className="text-xs text-muted mt-0.5">
                  共解析出 {stats.total} 条，已选 {stats.selectedCount} 条。勾选要导入的条目，取消不想要的。
                </p>
              </div>
              <button
                onClick={handleCancel}
                className="inline-flex h-8 w-8 items-center justify-center rounded-md hover:bg-foreground/5"
                aria-label="关闭预览"
              >
                <X className="h-4 w-4" />
              </button>
            </div>

            {/* 内容区 */}
            <div className="flex-1 px-5 py-4 overflow-y-auto">
              <div className="space-y-3">
                {SECTION_META.map((meta) => {
                  const arr = ((previewData as any)[meta.key] as any[]) || [];
                  if (arr.length === 0) return null;
                  const selArr = selected[meta.key] || [];
                  const selCount = selArr.filter(Boolean).length;
                  const isExpanded = expanded.has(meta.key);
                  const allSelected = selCount === arr.length;
                  return (
                    <div key={meta.key} className="border border-border rounded-lg overflow-hidden">
                      {/* 类别头 */}
                      <div className="flex items-center gap-2 px-3 py-2 bg-foreground/5">
                        <button
                          onClick={() => toggleExpand(meta.key)}
                          className="inline-flex h-5 w-5 items-center justify-center rounded hover:bg-foreground/10"
                        >
                          {isExpanded ? <ChevronDown className="h-3.5 w-3.5" /> : <ChevronRight className="h-3.5 w-3.5" />}
                        </button>
                        <span className="text-sm font-medium flex-1">
                          {meta.label}（{arr.length}）
                        </span>
                        {selCount !== arr.length && (
                          <span className="text-[10px] text-muted">已选 {selCount}/{arr.length}</span>
                        )}
                        <button
                          onClick={() => toggleSectionAll(meta.key, !allSelected)}
                          className="text-[11px] text-primary hover:underline"
                        >
                          {allSelected ? "全不选" : "全选"}
                        </button>
                      </div>
                      {/* 条目列表 */}
                      {isExpanded && (
                        <div className="divide-y divide-border">
                          {arr.map((item, idx) => {
                            const checked = selArr[idx] !== false;
                            return (
                              <label
                                key={idx}
                                className={cn(
                                  "flex items-start gap-3 px-3 py-2 cursor-pointer transition-colors",
                                  checked ? "bg-transparent" : "opacity-50"
                                )}
                              >
                                <input
                                  type="checkbox"
                                  checked={checked}
                                  onChange={() => toggleItem(meta.key, idx)}
                                  className="mt-0.5"
                                />
                                <div className="flex-1 min-w-0">
                                  <div className="text-sm font-medium text-foreground truncate">
                                    {renderValue(item[meta.primary]) || `条目 ${idx + 1}`}
                                  </div>
                                  <div className="text-xs text-muted mt-0.5 space-y-0.5">
                                    {meta.secondary.map((field) => {
                                      const val = item[field];
                                      if (val === undefined || val === null || val === "") return null;
                                      return (
                                        <div key={field}>
                                          <span className="text-muted/70">{field}：</span>
                                          <span className="text-foreground/80">{renderValue(val)}</span>
                                        </div>
                                      );
                                    })}
                                  </div>
                                </div>
                              </label>
                            );
                          })}
                        </div>
                      )}
                    </div>
                  );
                })}
                {/* 金手指（单对象，非数组） */}
                {previewData.golden_finger && (() => {
                  const gf = previewData.golden_finger!;
                  const checked = selected["golden_finger"]?.[0] !== false;
                  const isExpanded = expanded.has("golden_finger");
                  return (
                    <div className="border border-border rounded-lg overflow-hidden">
                      <div className="flex items-center gap-2 px-3 py-2 bg-foreground/5">
                        <button
                          onClick={() => toggleExpand("golden_finger")}
                          className="inline-flex h-5 w-5 items-center justify-center rounded hover:bg-foreground/10"
                        >
                          {isExpanded ? <ChevronDown className="h-3.5 w-3.5" /> : <ChevronRight className="h-3.5 w-3.5" />}
                        </button>
                        <span className="text-sm font-medium flex-1">金手指（1）</span>
                        <button
                          onClick={() => toggleItem("golden_finger", 0)}
                          className="text-[11px] text-primary hover:underline"
                        >
                          {checked ? "取消导入" : "加入导入"}
                        </button>
                      </div>
                      {isExpanded && (
                        <label className={cn(
                          "flex items-start gap-3 px-3 py-2 cursor-pointer transition-colors",
                          checked ? "bg-transparent" : "opacity-50"
                        )}>
                          <input
                            type="checkbox"
                            checked={checked}
                            onChange={() => toggleItem("golden_finger", 0)}
                            className="mt-0.5"
                          />
                          <div className="flex-1 min-w-0">
                            <div className="text-sm font-medium text-foreground">{gf.name || "未命名金手指"}</div>
                            <div className="text-xs text-muted mt-0.5 space-y-0.5">
                              {gf.type && <div><span className="text-muted/70">类型：</span><span className="text-foreground/80">{gf.type}</span></div>}
                              {gf.core_ability && <div><span className="text-muted/70">核心能力：</span><span className="text-foreground/80">{gf.core_ability}</span></div>}
                              {gf.limitation && <div><span className="text-muted/70">限制：</span><span className="text-foreground/80">{gf.limitation}</span></div>}
                              {gf.growth && <div><span className="text-muted/70">成长：</span><span className="text-foreground/80">{gf.growth}</span></div>}
                              {gf.origin && <div><span className="text-muted/70">来历：</span><span className="text-foreground/80">{gf.origin}</span></div>}
                            </div>
                          </div>
                        </label>
                      )}
                    </div>
                  );
                })()}
                {stats.total === 0 && (
                  <div className="text-center text-sm text-muted py-8">
                    AI 未解析出任何内容，请检查文档内容或重试。
                  </div>
                )}
              </div>
            </div>

            {/* 底部操作 */}
            <div className="flex flex-wrap items-center justify-between gap-2 px-5 py-4 border-t border-border">
              <span className="text-xs text-muted">
                将导入 {stats.selectedCount}/{stats.total} 条到设定库
              </span>
              <div className="flex flex-wrap items-center gap-2">
                <Button variant="outline" size="sm" onClick={handleCancel}>
                  <X className="h-4 w-4 mr-1" />
                  取消，不导入
                </Button>
                <Button size="sm" onClick={handleConfirm} disabled={stats.selectedCount === 0}>
                  <Check className="h-4 w-4 mr-1" />
                  确认导入（{stats.selectedCount}）
                </Button>
              </div>
            </div>
          </div>
        </div>
      )}
    </>
  );
}
