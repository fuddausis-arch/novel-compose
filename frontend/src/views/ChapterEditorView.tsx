import { useState, useEffect } from "react";
import { Sparkles, Save } from "lucide-react";
import { api } from "@/api";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { AiSuggestionDialog } from "@/components/ai-suggestion-dialog";
import { useToast } from "@/hooks/useToast";
import { useAppStore } from "@/store";
import type { ChapterBrief, Project, ReviewResult } from "@/types";

interface ChapterEditorViewProps {
  project?: Project;
  chapter: number;
  title: string;
  content: string;
  dirty: boolean;
  autoSaveState?: "idle" | "saving" | "saved";
  onTitleChange: (title: string) => void;
  onContentChange: (content: string) => void;
  onSave: () => void;
  onDelete: () => void;
  onGenerate: () => void;
  generating: boolean;
  onCancel?: () => void;
}

export function ChapterEditorView({
  project,
  chapter,
  title,
  content,
  dirty,
  autoSaveState = "idle",
  onTitleChange,
  onContentChange,
  onSave,
  onDelete,
  onGenerate,
  generating,
  onCancel,
}: ChapterEditorViewProps) {
  const [tab, setTab] = useState<"write" | "brief" | "review" | "commit">("write");
  const [brief, setBrief] = useState<ChapterBrief | null>(null);
  const [briefError, setBriefError] = useState<string | null>(null);
  const [review, setReview] = useState<ReviewResult | null>(null);
  const [commitResult, setCommitResult] = useState<{ chapter: number; committed: boolean; summary: string; deltas: number; relationships: number; events: number; foreshadow_updates: number; error?: string } | null>(null);
  const [loading, setLoading] = useState<string | null>(null);
  const [suggestOpen, setSuggestOpen] = useState(false);

  const { showSuccess, showError } = useToast();
  const refreshAssets = useAppStore((s) => s.refreshAssets);
  const startPipeline = useAppStore((s) => s.startPipeline);
  const addPipelineEvent = useAppStore((s) => s.addPipelineEvent);
  const setPipelineStatus = useAppStore((s) => s.setPipelineStatus);
  const clearPipeline = useAppStore((s) => s.clearPipeline);
  const projectId = project?.id;

  // 切换章节时尝试加载已保存的任务书
  useEffect(() => {
    if (!projectId || !chapter) { setBrief(null); return; }
    api.getChapterBrief(projectId, chapter)
      .then((r) => { setBrief(r); })
      .catch(() => { setBrief(null); });
  }, [projectId, chapter]);

  const handleSaveBrief = async () => {
    if (!projectId || !brief) return;
    try {
      await api.saveChapterBrief(projectId, chapter, title, brief.brief, brief.brief_text, brief.context_stats);
      showSuccess("任务书已保存");
    } catch (e: any) {
      showError("保存失败：" + e.message);
    }
  };

  const handleBrief = async () => {
    if (!projectId) return;
    setLoading("brief");
    setBriefError(null);
    try {
      const r = await api.generateChapterBrief(projectId, chapter, title);
      setBrief(r);
      setTab("brief");
    } catch (e: any) {
      setBrief(null);
      setBriefError("生成失败：" + e.message);
      setTab("brief");
    } finally {
      setLoading(null);
    }
  };

  const handleReview = async () => {
    if (!projectId) return;
    setLoading("review");
    startPipeline("审查章节一致性…", "chapter");
    addPipelineEvent("正在审查", 50);
    try {
      const r = await api.reviewChapter(projectId, chapter);
      setReview(r);
      setTab("review");
      addPipelineEvent("审查完成", 100);
      setPipelineStatus("done");
      setTimeout(() => clearPipeline(), 2000);
    } catch (e: any) {
      setReview({ summary: "审查失败：" + e.message, issues: [], dimension_results: [] } as unknown as ReviewResult);
      setTab("review");
      addPipelineEvent(`错误：审查失败：${e.message}`);
      setPipelineStatus("error");
      setTimeout(() => clearPipeline(), 3000);
    } finally {
      setLoading(null);
    }
  };

  const handleCommit = async () => {
    if (!projectId) return;
    setLoading("commit");
    try {
      const r = await api.commitChapter(projectId, chapter);
      setCommitResult(r);
      setTab("commit");
      if (r.committed) {
        // 提交会写入角色/怪物/势力/世界观/伏笔/状态/事件/关系 8 类实体，
        // 刷新 store 让其他视图（角色卡/怪物/势力等）立即看到新数据
        await refreshAssets();
        showSuccess(`第${chapter}章已提交，已提取 ${r.deltas} 项变更`);
      }
    } catch (e: any) {
      setCommitResult({ chapter, committed: false, summary: "", deltas: 0, relationships: 0, events: 0, foreshadow_updates: 0, error: e.message });
      setTab("commit");
    } finally {
      setLoading(null);
    }
  };

  const isLoading = loading !== null;

  return (
    <Card className="flex-1 flex flex-col overflow-hidden relative">
      {isLoading && (
        <div className="absolute inset-x-0 top-0 z-50">
          <div className="h-1 w-full bg-primary/20 overflow-hidden">
            <div className="h-full bg-primary animate-[loading_1.5s_ease-in-out_infinite]" style={{ width: "40%" }} />
          </div>
          <div className="absolute right-3 top-2 text-xs text-primary font-medium">AI 处理中…</div>
        </div>
      )}
      <CardHeader className="pb-2">
        <div className="flex items-center justify-between">
          <Input className="w-64" value={title} onChange={(e) => onTitleChange(e.target.value)} />
          <div className="flex items-center gap-2">
            {autoSaveState === "saving" && <Badge className="text-primary border-primary">自动保存中…</Badge>}
            {autoSaveState === "saved" && !dirty && <Badge className="text-success border-success">已自动保存</Badge>}
            {dirty && autoSaveState !== "saving" && <Badge className="text-warning border-warning">未保存</Badge>}
            <Button size="sm" onClick={onSave} disabled={!dirty}>保存</Button>
            <Button size="sm" variant="primary" onClick={onGenerate} disabled={generating}>{generating ? "生成中…" : "AI 生成"}</Button>
            {generating && onCancel && (
              <Button size="sm" variant="danger" onClick={onCancel}>取消生成</Button>
            )}
            <Button size="sm" variant="default" onClick={() => setSuggestOpen(true)}>
              <Sparkles className="h-3.5 w-3.5 mr-1" /> AI 建议后续
            </Button>
            <Button size="sm" variant="danger" onClick={onDelete}>删除</Button>
          </div>
        </div>
        <div className="flex items-center gap-2 mt-2">
          {(["write", "brief", "review", "commit"] as const).map((t) => (
            <button
              key={t}
              onClick={() => setTab(t)}
              className={`px-2 py-1 rounded-lg text-xs ${tab === t ? "bg-primary/10 text-primary" : "text-muted hover:bg-foreground/5"}`}
            >
              {t === "write" ? "正文" : t === "brief" ? "任务书" : t === "review" ? "审查" : "提交"}
            </button>
          ))}
          {tab === "write" && (
            <span className="text-xs text-muted ml-1">
              {content.replace(/\s/g, "").length} 字
              {content.length > 0 && (
                <span className="ml-2">
                  （含空格 {content.length}）
                </span>
              )}
            </span>
          )}
          <Button size="sm" variant="ghost" onClick={handleBrief} disabled={loading === "brief"} className="ml-auto">{loading === "brief" ? "…" : "生成任务书"}</Button>
          {brief && <Button size="sm" variant="ghost" onClick={handleSaveBrief}><Save className="h-3.5 w-3.5 mr-1" />保存任务书</Button>}
          <Button size="sm" variant="ghost" onClick={handleReview} disabled={loading === "review"}>{loading === "review" ? "…" : "审查"}</Button>
          <Button size="sm" variant="ghost" onClick={handleCommit} disabled={loading === "commit"}>{loading === "commit" ? "…" : "提交"}</Button>
        </div>
      </CardHeader>
      <CardContent className="flex-1 p-0 overflow-hidden">
        {tab === "write" && (
          <textarea
            className="w-full h-full resize-none outline-none p-4 editor-surface text-base leading-relaxed"
            value={content}
            onChange={(e) => onContentChange(e.target.value)}
            placeholder="在此输入章节正文…"
          />
        )}
        {tab === "brief" && (
          <div className="h-full overflow-y-auto p-4 text-sm text-foreground">
            {briefError ? (
              <div className="text-danger">{briefError}</div>
            ) : brief ? (
              <div className="space-y-3">
                <div className="text-xs text-muted">第{brief.chapter}章 {brief.title} · 上下文：角色{brief.context_stats?.characters ?? brief.context_stats?.total_chars ?? 0} · 设定{brief.context_stats?.world_settings ?? ""} · 待埋伏笔{brief.context_stats?.fore_to_plant ?? ""} · 待回收{brief.context_stats?.fore_to_resolve ?? ""}</div>
                {[
                  { label: "开篇委托", value: brief.brief?.opening },
                  { label: "这章的故事", value: brief.brief?.story },
                  { label: "这章的人物", value: brief.brief?.characters },
                  { label: "怎么写更顺", value: brief.brief?.craft },
                  { label: "收在哪里", value: brief.brief?.ending },
                ].map((section) => {
                  const text = typeof section.value === "string"
                    ? section.value
                    : section.value == null
                      ? ""
                      : JSON.stringify(section.value, null, 2);
                  return (
                    <div key={section.label} className="rounded-lg border border-border bg-surface p-3">
                      <div className="font-medium text-primary mb-1">{section.label}</div>
                      <div className="whitespace-pre-wrap">{text}</div>
                    </div>
                  );
                })}
              </div>
            ) : (
              <div className="text-muted">点击右上角「生成任务书」获取 AI 写作任务书。</div>
            )}
          </div>
        )}
        {tab === "review" && (
          <div className="h-full overflow-y-auto p-4 space-y-2">
            {review ? (
              <>
                <div className="text-sm font-medium">{review.summary}</div>
                {review.dimension_results?.map((d, i) => (
                  <div key={i} className="text-xs"><span className="font-medium">{d.dimension}</span>：{d.conclusion}</div>
                ))}
                {review.issues?.map((issue, i) => (
                  <div key={i} className={`rounded-lg border p-2 text-xs ${issue.blocking ? "border-danger bg-danger/5" : "border-border bg-surface"}`}>
                    <div className="flex items-center gap-1">
                      <Badge className={issue.blocking ? "text-danger border-danger" : "text-warning border-warning"}>{issue.category}</Badge>
                      <span className="font-medium">{issue.severity}</span>
                    </div>
                    <div className="mt-1">{issue.description}</div>
                    <div className="text-muted mt-0.5">证据：{issue.evidence}</div>
                    <div className="text-primary mt-0.5">修复：{issue.fix_hint}</div>
                  </div>
                ))}
              </>
            ) : <div className="text-sm text-muted">点击右上角「审查」开始一致性审查。</div>}
          </div>
        )}
        {tab === "commit" && (
          <div className="h-full overflow-y-auto p-4 text-sm">
            {commitResult ? (
              commitResult.error ? (
                <div className="text-danger">提交失败：{commitResult.error}</div>
              ) : (
                <div className="space-y-2">
                  <div className="font-medium">第{commitResult.chapter}章已提交</div>
                  <div className="text-muted">摘要：{commitResult.summary}</div>
                  <div className="text-xs text-muted">状态增量 {commitResult.deltas} 条 · 关系 {commitResult.relationships} 条 · 事件 {commitResult.events} 条 · 伏笔更新 {commitResult.foreshadow_updates} 条</div>
                </div>
              )
            ) : <div className="text-muted">点击右上角「提交」把本章事实沉淀到状态库。</div>}
          </div>
        )}
      </CardContent>
      {project && (
        <AiSuggestionDialog
          open={suggestOpen}
          project={project}
          contextType="chapter"
          contextId={chapter}
          defaultSuggestType="plot"
          onClose={() => setSuggestOpen(false)}
          onAdopted={() => { setSuggestOpen(false); showSuccess("建议已采纳"); }}
        />
      )}
    </Card>
  );
}
