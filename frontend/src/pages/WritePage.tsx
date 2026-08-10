import { useCallback, useEffect, useRef, useState } from "react";
import { AppLayout } from "@/components/layout/AppLayout";
import { ProjectBrowser } from "@/components/layout/ProjectBrowser";
import { ChapterEditorView } from "@/views/ChapterEditorView";
import { PipelinePanel } from "@/components/pipeline-panel";
import { ReviewDialog } from "@/components/review-dialog";
import { ChatPanel } from "@/components/chat";
import { EditorTabs } from "@/components/write/EditorTabs";
import { useCurrentProject } from "@/hooks/useCurrentProject";
import { useOpenTabs } from "@/hooks/useOpenTabs";
import { useGeneration } from "@/hooks/useGeneration";
import { useConfirmDialog } from "@/hooks/useConfirmDialog";
import { useAppStore } from "@/store";
import { api } from "@/api";
import { useToast } from "@/hooks/useToast";
import { bumpDataVersion } from "@/store/slices/dataVersion";
import { Button } from "@/components/ui/button";
import type { ChapterText } from "@/types";

export default function WritePage() {
  const { project } = useCurrentProject();
  const { tabs, activeTabId, open, close, setActiveTabId } = useOpenTabs();
  const store = useAppStore();
  const { showError, showSuccess } = useToast();
  const { confirm: confirmDelete, dialog: deleteDialog } = useConfirmDialog();

  const [title, setTitle] = useState("");
  const [content, setContent] = useState("");
  const [dirty, setDirty] = useState(false);
  const [saveState, setSaveState] = useState<"idle" | "saving" | "saved">("idle");
  const [, setGlobalLoading] = useState(false);
  const [chatOpen, setChatOpen] = useState(true);
  const timerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const autoOpenedRef = useRef(false);
  const lastProjectIdRef = useRef<number | null>(null);

  const activeTab = tabs.find((tab) => tab.id === activeTabId);
  const chapterId = activeTab?.type === "chapter"
    ? Number(activeTab.id.replace(/^chapter-/, ""))
    : 0;

  const { generatingChapter, generate, reviewPending, resume, cancel } = useGeneration({
    setLoading: setGlobalLoading,
    onDone: (ct: ChapterText) => {
      setContent(ct.text ?? "");
      setDirty(false);
      setSaveState("saved");
    },
  });

  // 自动打开第一章
  useEffect(() => {
    if (project?.id !== lastProjectIdRef.current) {
      autoOpenedRef.current = false;
      lastProjectIdRef.current = project?.id ?? null;
    }
    if (!project || autoOpenedRef.current) return;
    if (tabs.length === 0 && store.chapters.length > 0) {
      autoOpenedRef.current = true;
      const ch = store.chapters[0];
      open({
        id: `chapter-${ch.chapter}`,
        label: ch.title || `第${ch.chapter}章`,
        type: "chapter",
      });
    }
  }, [project?.id, store.chapters, tabs.length, open]);

  // 加载章节内容
  useEffect(() => {
    if (!project || !chapterId) {
      setContent("");
      setTitle("");
      return;
    }
    let cancelled = false;
    setSaveState("idle");
    setDirty(false);
    const chapterMeta = store.chapters.find((c) => c.chapter === chapterId);
    setTitle(chapterMeta?.title || `第${chapterId}章`);
    api
      .getChapterText(project.id, chapterId)
      .then((data) => {
        if (cancelled) return;
        setContent(data.text ?? "");
      })
      .catch((e) => {
        if (cancelled) return;
        showError("加载章节失败：" + e.message);
      });
    return () => {
      cancelled = true;
    };
  }, [project?.id, chapterId]);

  // 自动保存
  useEffect(() => {
    if (!project || !chapterId || !dirty) return;
    if (timerRef.current) clearTimeout(timerRef.current);
    setSaveState("idle");
    timerRef.current = setTimeout(() => {
      setSaveState("saving");
      api
        .saveChapterText(project.id, chapterId, title, content)
        .then(() => {
          setDirty(false);
          setSaveState("saved");
          // 断链④：写章保存后 bump 版本号，让时间线/统计等页面感知到数据变化
          bumpDataVersion("chapters");
          bumpDataVersion("bible");
        })
        .catch((e) => {
          setSaveState("idle");
          showError("自动保存失败：" + e.message);
        });
    }, 1000);
    return () => {
      if (timerRef.current) clearTimeout(timerRef.current);
    };
  }, [project?.id, chapterId, dirty, title, content]);

  const handleOpenChapter = useCallback(
    (cid: number, chapterTitle: string) => {
      autoOpenedRef.current = true;
      open({
        id: `chapter-${cid}`,
        label: chapterTitle || `第${cid}章`,
        type: "chapter",
      });
    },
    [open]
  );

  const handleSave = useCallback(async () => {
    if (!project || !chapterId) return;
    try {
      await api.saveChapterText(project.id, chapterId, title, content);
      setDirty(false);
      setSaveState("saved");
      bumpDataVersion("chapters");
      bumpDataVersion("bible");
      showSuccess("已保存");
    } catch (e: any) {
      showError("保存失败：" + e.message);
    }
  }, [project, chapterId, title, content]);

  const handleDelete = useCallback(async () => {
    if (!project || !chapterId) return;
    const ok = await confirmDelete({
      title: "删除章节",
      description: `第 ${chapterId} 章及其正文、摘要将被永久删除，此操作不可撤销。`,
      confirmText: "确认删除",
      cancelText: "取消",
      variant: "danger",
    });
    if (!ok) return;
    try {
      await api.deleteChapter(project.id, chapterId);
      await store.refreshChapters();
      if (activeTabId) close(activeTabId);
      showSuccess("章节已删除");
    } catch (e: any) {
      showError("删除失败：" + e.message);
    }
  }, [project, chapterId, activeTabId, confirmDelete, store, close, showSuccess, showError]);

  const handleGenerate = useCallback(() => {
    if (!project || !chapterId) return;
    if (!title.trim()) {
      showError("请先填写章节标题");
      return;
    }
    generate(chapterId, title);
  }, [project, chapterId, title, generate, showError]);

  const handleResume = useCallback(
    (decision: "approve" | "reject", feedback?: string) => {
      resume(decision, feedback);
    },
    [resume]
  );

  const rightPanel = project ? (
    <div className="flex h-full flex-col">
      <div className="flex items-center justify-between border-b border-border px-3 py-2">
        <span className="text-sm font-semibold text-foreground">AI 助手</span>
        <button
          onClick={() => setChatOpen((v) => !v)}
          className="text-xs text-muted hover:text-foreground"
        >
          {chatOpen ? "收起" : "展开"}
        </button>
      </div>
      {chatOpen && (
        <div className="flex-1 overflow-hidden">
          <ChatPanel
            projectId={project.id}
            objectType={chapterId ? "chapter" : ""}
            objectId={chapterId || ""}
            title={title}
            onRewriteChapter={(ch, chTitle) => {
              handleOpenChapter(ch, chTitle);
              generate(ch, chTitle);
            }}
          />
        </div>
      )}
    </div>
  ) : null;

  return (
    <AppLayout browser={<ProjectBrowser onOpenChapter={handleOpenChapter} />} rightPanel={rightPanel} rightPanelWidth="w-[420px]">
      <div className="flex h-full flex-col overflow-hidden bg-background">
        <EditorTabs
          tabs={tabs}
          activeTabId={activeTabId}
          onActivate={setActiveTabId}
          onClose={close}
        />

        {/* 流水线进度条 */}
        {store.pipelineStatus !== "idle" && (
          <PipelinePanel
            events={store.pipelineEvents}
            status={store.pipelineStatus}
            progress={store.pipelineProgress}
          />
        )}

        <div className="flex flex-1 flex-col overflow-hidden">
          {tabs.length === 0 ? (
            <div className="flex h-full flex-col items-center justify-center gap-4 text-muted">
              <div className="text-lg">暂无打开的章节</div>
              <div className="text-sm">
                {store.chapters.length > 0
                  ? "从左侧「章节」列表选择一章开始编辑"
                  : "请先在「大纲」页面生成章纲，或在「规划」页面进行卷级规划"}
              </div>
              {store.chapters.length > 0 && (
                <Button
                  variant="primary"
                  onClick={() => {
                    const ch = store.chapters[0];
                    handleOpenChapter(ch.chapter, ch.title);
                  }}
                >
                  打开第一章
                </Button>
              )}
            </div>
          ) : activeTab?.type === "chapter" && chapterId ? (
            <ChapterEditorView
              project={project || undefined}
              chapter={chapterId}
              title={title}
              content={content}
              dirty={dirty}
              autoSaveState={saveState}
              onTitleChange={(t) => {
                setTitle(t);
                setDirty(true);
                setSaveState("idle");
              }}
              onContentChange={(c) => {
                setContent(c);
                setDirty(true);
                setSaveState("idle");
              }}
              onSave={handleSave}
              onDelete={handleDelete}
              onGenerate={handleGenerate}
              generating={generatingChapter === chapterId}
              onCancel={cancel}
            />
          ) : (
            <div className="flex h-full items-center justify-center text-muted">
              未知标签类型
            </div>
          )}
        </div>
      </div>

      {/* 人审弹窗 */}
      {reviewPending && (
        <ReviewDialog
          data={reviewPending}
          onApprove={(fb) => handleResume("approve", fb)}
          onReject={(fb) => handleResume("reject", fb)}
        />
      )}

      {deleteDialog}
    </AppLayout>
  );
}
