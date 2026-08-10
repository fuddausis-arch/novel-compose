import { useState, useCallback, useEffect, useRef } from "react";
import { api } from "@/api";
import { useAppStore } from "@/store";
import { useToast } from "@/hooks/useToast";
import type { ChapterText } from "@/types";

const CHAPTER_NODE_PROGRESS: Record<string, number> = {
  assemble: 8,
  analyze_style: 15,
  write: 30,
  audit: 55,
  rewrite: 70,
  human_review: 75,
  style_refine: 85,
  save_text: 92,
  summarize: 97,
};

export interface ReviewPendingData {
  thread_id: string;
  chapter: number;
  title: string;
  overall_score: number;
  summary: string;
  issues: { dimension: string; severity: string; message: string }[];
  draft_preview: string;
  polished?: boolean;
}

export function useGeneration({
  setLoading,
  onDone,
}: {
  setLoading: (loading: boolean) => void;
  onDone: (chapterText: ChapterText) => void;
}) {
  const store = useAppStore();
  const { showError, showSuccess } = useToast();
  const [generatingChapter, setGeneratingChapter] = useState<number | null>(
    store.activeGeneration?.chapter ?? null
  );
  const [reviewPending, setReviewPending] = useState<ReviewPendingData | null>(
    store.activeGeneration?.reviewPendingData ?? null
  );
  const currentThreadId = useRef<string>(store.activeGeneration?.threadId || "");

  // 终止状态（done/error）后延迟清空流水线，避免事件立即消失用户看不到结果
  const schedulePipelineClear = () => {
    setTimeout(() => store.clearPipeline(), 5000);
  };

  // 根据 store 中的 activeGeneration 同步本地状态（切回页面时恢复）
  useEffect(() => {
    const ag = store.activeGeneration;
    if (ag?.chapter) {
      setGeneratingChapter(ag.chapter);
    } else if (!ag) {
      setGeneratingChapter(null);
    }
    if (ag?.reviewPendingData) {
      setReviewPending(ag.reviewPendingData as ReviewPendingData);
    } else if (!ag) {
      setReviewPending(null);
    }
    if (ag?.threadId) {
      currentThreadId.current = ag.threadId;
    }
  }, [store.activeGeneration?.chapter, store.activeGeneration?.threadId, store.activeGeneration?.reviewPendingData]);

  // 订阅全局生成事件流：EventSource 由 store 持有，切换页面不中断
  useEffect(() => {
    const unsubscribe = store.subscribeGeneration((event) => {
      switch (event.type) {
        case "node": {
          const data = event.data;
          const node = data?.node || "unknown";
          if (data?.thread_id) {
            currentThreadId.current = data.thread_id;
          }
          if (data?.status === "failed" || data?.status === "end_failed") {
            const msg = `节点 ${node} 失败`;
            store.addPipelineEvent(`错误：${msg}`);
            store.setPipelineStatus("error");
            schedulePipelineClear();
            setGeneratingChapter(null);
            setLoading(false);
            showError("章节生成失败：" + msg);
            return;
          }
          if (node === "analyze_style" && data?.style_analysis) {
            store.setStyleAnalysis(data.style_analysis, data.style_benchmark || "");
            store.addPipelineEvent("人类样本写法分析完成", CHAPTER_NODE_PROGRESS[node]);
          } else {
            store.addPipelineEvent(`节点完成：${node}`, CHAPTER_NODE_PROGRESS[node] ?? store.pipelineProgress);
          }
          break;
        }
        case "review_pending": {
          const data = event.data as ReviewPendingData;
          store.addPipelineEvent("等待人审…", 75);
          store.setPipelineStatus("idle");
          setReviewPending(data);
          break;
        }
        case "error": {
          const data = event.data || {};
          const raw = data.error || (data.status === "failed" ? "生成失败，流水线中途结束" : "生成失败");
          const isQuota = /配额|quota|余额不足|insufficient|exceeded|rate.?limit/i.test(raw);
          const msg = isQuota ? "API 配额超限，请等待重置或更换 LLM 配置" : raw;
          store.addPipelineEvent(`错误：${msg}`);
          store.setPipelineStatus("error");
          schedulePipelineClear();
          setGeneratingChapter(null);
          setLoading(false);
          showError("章节生成失败：" + msg);
          break;
        }
        case "done": {
          const data = event.data || {};
          const chapter = store.activeGeneration?.chapter || data?.chapter;
          if (data.status === "failed") {
            store.addPipelineEvent("错误：生成失败，流水线中途结束");
            store.setPipelineStatus("error");
            schedulePipelineClear();
            setGeneratingChapter(null);
            setLoading(false);
            showError("章节生成失败：流水线中途结束");
            return;
          }
          store.addPipelineEvent("生成完成", 100);
          store.setPipelineStatus("done");
          schedulePipelineClear();
          setGeneratingChapter(null);
          setLoading(false);
          if (store.activeGeneration?.mode === "resume" && store.activeGeneration.reviewDecision === "reject") {
            showSuccess("已驳回，章节将重写");
            return;
          }
          store.refreshAssets().then(() => {
            if (!store.currentProject || !chapter) return;
            api.getChapterText(store.currentProject.id, chapter).then((ct) => {
              onDone(ct);
            }).catch((e: any) => {
              showError("加载生成结果失败：" + e.message);
            });
          });
          break;
        }
        case "connection_error": {
          store.addPipelineEvent("连接中断");
          store.setPipelineStatus("error");
          schedulePipelineClear();
          setGeneratingChapter(null);
          setLoading(false);
          showError("章节生成连接中断，请检查网络或 API 额度");
          break;
        }
      }
    });

    // 如果切回页面时仍有活跃的生成任务，恢复加载状态
    if (store.activeGeneration) {
      setLoading(true);
    }

    return unsubscribe;
  }, [store, setLoading, onDone, showError, showSuccess]);

  const generate = (chapter: number, title: string) => {
    if (!store.currentProject) return;
    setGeneratingChapter(chapter);
    setReviewPending(null);
    setLoading(true);
    store.startPipeline("开始生成章节…", "chapter");
    store.startGenerationStream(store.currentProject.id, chapter, title);
  };

  const resume = (decision: "approve" | "reject", feedback?: string) => {
    if (!store.currentProject || !reviewPending) return;
    const { thread_id, chapter } = reviewPending;
    setReviewPending(null);
    setLoading(true);
    store.setPipelineStatus("running");
    const hasFeedback = feedback && feedback.trim();
    const msg = decision === "approve"
      ? (hasFeedback ? "人审通过（含意见），继续生成…" : "人审通过，继续生成…")
      : (hasFeedback ? "人审驳回（含意见），重写中…" : "人审驳回，重写中…");
    store.addPipelineEvent(msg);
    store.resumeGenerationStream(store.currentProject.id, thread_id, decision, feedback, chapter);
    // 恢复 chapter 信息，便于 done 后加载结果
    setGeneratingChapter(chapter);
  };

  const cancel = useCallback(async () => {
    if (!store.currentProject || !generatingChapter) return;
    try {
      const tid = reviewPending?.thread_id || currentThreadId.current;
      if (tid) await api.cancelChapter(store.currentProject.id, tid);
    } catch {
      // 忽略错误，前端仍然关闭连接
    }
    store.stopGenerationStream();
    store.addPipelineEvent("已取消");
    store.setPipelineStatus("idle");
    setGeneratingChapter(null);
    setLoading(false);
    setReviewPending(null);
  }, [generatingChapter, store, reviewPending, setLoading]);

  return { generatingChapter, generate, reviewPending, resume, cancel };
}
