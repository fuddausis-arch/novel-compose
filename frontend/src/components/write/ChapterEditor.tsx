import { useEffect, useMemo, useRef, useState } from "react";
import { api } from "@/api";
import { Input } from "@/components/ui/input";
import { Textarea } from "@/components/ui/textarea";
import { useAppStore } from "@/store";
import { useToast } from "@/hooks/useToast";
import { bumpDataVersion } from "@/store/slices/dataVersion";

interface ChapterEditorProps {
  chapterId: number;
}

export function ChapterEditor({ chapterId }: ChapterEditorProps) {
  const project = useAppStore((s) => s.currentProject);
  const chapters = useAppStore((s) => s.chapters);
  const { showError } = useToast();

  const chapterMeta = useMemo(
    () => chapters.find((c) => c.chapter === chapterId),
    [chapters, chapterId]
  );

  const [title, setTitle] = useState(() => chapterMeta?.title || `第${chapterId}章`);
  const [content, setContent] = useState("");
  const [dirty, setDirty] = useState(false);
  const [saveState, setSaveState] = useState<"idle" | "saving" | "saved">("idle");
  const timerRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  // 当章节元数据变化且未编辑时，同步标题
  useEffect(() => {
    if (chapterMeta && !dirty) {
      setTitle(chapterMeta.title);
    }
  }, [chapterMeta, dirty]);

  // 加载正文
  useEffect(() => {
    if (!project) return;
    let cancelled = false;
    setSaveState("idle");
    setDirty(false);
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
    if (!project) return;
    if (!dirty) return;

    if (timerRef.current) {
      clearTimeout(timerRef.current);
    }
    setSaveState("idle");

    timerRef.current = setTimeout(() => {
      setSaveState("saving");
      api
        .saveChapterText(project.id, chapterId, title, content)
        .then(() => {
          setDirty(false);
          setSaveState("saved");
          // 断链④：保存后 bump，让时间线/统计等页面感知数据变化
          bumpDataVersion("chapters");
          bumpDataVersion("bible");
        })
        .catch((e) => {
          setSaveState("idle");
          showError("自动保存失败：" + e.message);
        });
    }, 1000);

    return () => {
      if (timerRef.current) {
        clearTimeout(timerRef.current);
      }
    };
  }, [project?.id, chapterId, dirty, title, content]);

  const handleTitleChange = (e: React.ChangeEvent<HTMLInputElement>) => {
    setTitle(e.target.value);
    setDirty(true);
    setSaveState("idle");
  };

  const handleContentChange = (e: React.ChangeEvent<HTMLTextAreaElement>) => {
    setContent(e.target.value);
    setDirty(true);
    setSaveState("idle");
  };

  if (!project) {
    return (
      <div className="flex h-full items-center justify-center text-muted">
        未选择项目
      </div>
    );
  }

  return (
    <div className="flex h-full flex-col gap-4 overflow-hidden p-4">
      <div className="flex items-center justify-between gap-4">
        <Input
          value={title}
          onChange={handleTitleChange}
          placeholder="章节标题"
          className="flex-1 text-lg font-semibold bg-transparent border-0 px-0 focus-visible:ring-0"
        />
        <div className="shrink-0 text-xs text-muted">
          {saveState === "saving" && "保存中…"}
          {saveState === "saved" && "已保存"}
        </div>
      </div>
      <Textarea
        value={content}
        onChange={handleContentChange}
        placeholder="在此输入章节正文…"
        className="flex-1 resize-none bg-white border border-border rounded-xl p-4 leading-7"
      />
    </div>
  );
}
