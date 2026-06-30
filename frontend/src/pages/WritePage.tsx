import { useCallback } from "react";
import { AppLayout } from "@/components/layout/AppLayout";
import { ProjectBrowser } from "@/components/layout/ProjectBrowser";
import { AiPanel } from "@/components/layout/AiPanel";
import { ChapterEditor } from "@/components/write/ChapterEditor";
import { EditorTabs } from "@/components/write/EditorTabs";
import { useCurrentProject } from "@/hooks/useCurrentProject";
import { useOpenTabs } from "@/hooks/useOpenTabs";

export default function WritePage() {
  useCurrentProject();
  const { tabs, activeTabId, open, close, setActiveTabId } = useOpenTabs();

  const activeTab = tabs.find((tab) => tab.id === activeTabId);

  const handleOpenChapter = useCallback(
    (chapterId: number, title: string) => {
      open({
        id: `chapter-${chapterId}`,
        label: title || `第${chapterId}章`,
        type: "chapter",
      });
    },
    [open]
  );

  return (
    <AppLayout browser={<ProjectBrowser onOpenChapter={handleOpenChapter} />} rightPanel={<AiPanel />}>
      <div className="flex h-full flex-col overflow-hidden bg-background">
        <EditorTabs
          tabs={tabs}
          activeTabId={activeTabId}
          onActivate={setActiveTabId}
          onClose={close}
          onAdd={() => {
            const nextIndex = tabs.length + 1;
            open({
              id: `new-${Date.now()}`,
              label: `新标签 ${nextIndex}`,
              type: "chapter",
            });
          }}
        />

        <div className="flex flex-1 flex-col overflow-hidden">
          {tabs.length === 0 ? (
            <div className="flex h-full items-center justify-center text-muted">
              从左侧选择章节或资产开始编辑
            </div>
          ) : activeTab?.type === "chapter" ? (
            <ChapterEditor
              key={activeTab.id}
              chapterId={Number(activeTab.id.replace(/^chapter-/, ""))}
            />
          ) : activeTab?.type === "asset" ? (
            <div className="flex h-full items-center justify-center text-muted">
              资产编辑占位
            </div>
          ) : (
            <div className="flex h-full items-center justify-center text-muted">
              未知标签类型
            </div>
          )}
        </div>
      </div>
    </AppLayout>
  );
}
