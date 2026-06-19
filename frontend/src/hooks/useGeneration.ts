import { useState } from "react";
import { api } from "@/api";
import { useAppStore } from "@/store";
import { useToast } from "@/hooks/useToast";
import type { ChapterText } from "@/types";

export function useGeneration({
  setLoading,
  onDone,
}: {
  setLoading: (loading: boolean) => void;
  onDone: (chapterText: ChapterText) => void;
}) {
  const store = useAppStore();
  const { showError } = useToast();
  const [pipelineEvents, setPipelineEvents] = useState<string[]>([]);
  const [pipelineStatus, setPipelineStatus] = useState<"idle" | "running" | "done" | "error">("idle");
  const [generatingChapter, setGeneratingChapter] = useState<number | null>(null);

  const generate = (chapter: number, title: string) => {
    if (!store.currentProject) return;
    setGeneratingChapter(chapter);
    setLoading(true);
    setPipelineStatus("running");
    setPipelineEvents(["开始生成…"]);
    const es = api.generateStream(store.currentProject.id, chapter, title);
    es.addEventListener("node", (e) => {
      const data = JSON.parse((e as MessageEvent).data);
      setPipelineEvents((prev) => [...prev, `节点完成：${data.node || "unknown"}`]);
    });
    es.addEventListener("error", (e) => {
      const data = JSON.parse((e as MessageEvent).data || "{}");
      setPipelineEvents((prev) => [...prev, `错误：${data.error || "生成失败"}`]);
      setPipelineStatus("error");
      setGeneratingChapter(null);
      setLoading(false);
      es.close();
    });
    es.addEventListener("done", () => {
      setPipelineEvents((prev) => [...prev, "生成完成"]);
      setPipelineStatus("done");
      setGeneratingChapter(null);
      setLoading(false);
      es.close();
      store.refreshAssets().then(() => {
        api.getChapterText(chapter).then((ct) => {
          onDone(ct);
        }).catch((e: any) => {
          showError("加载生成结果失败：" + e.message);
        });
      });
    });
    es.onerror = () => {
      setPipelineEvents((prev) => [...prev, "连接错误"]);
      setPipelineStatus("error");
      setGeneratingChapter(null);
      setLoading(false);
      es.close();
    };
  };

  return { pipelineEvents, pipelineStatus, generatingChapter, generate };
}
