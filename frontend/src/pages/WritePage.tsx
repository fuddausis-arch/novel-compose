import { AppLayout } from "@/components/layout/AppLayout";
import { ProjectBrowser } from "@/components/layout/ProjectBrowser";
import { AiPanel } from "@/components/layout/AiPanel";
import { EditorTabs } from "@/components/write/EditorTabs";
import { useCurrentProject } from "@/hooks/useCurrentProject";
import { useOpenTabs } from "@/hooks/useOpenTabs";

export default function WritePage() {
  useCurrentProject();
  const { tabs, activeTabId, open, close, setActiveTabId } = useOpenTabs();

  const activeTab = tabs.find((tab) => tab.id === activeTabId);

  return (
    <AppLayout browser={<ProjectBrowser />} rightPanel={<AiPanel />}>
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
          ) : (
            <div className="flex h-full flex-col items-center justify-center gap-2 text-muted">
              <div className="text-sm font-medium text-foreground">
                {activeTab?.label}
              </div>
              <div className="text-sm">编辑器占位区</div>
            </div>
          )}
        </div>
      </div>
    </AppLayout>
  );
}
