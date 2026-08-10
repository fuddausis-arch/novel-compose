import { useState } from "react";
import { AppLayout } from "@/components/layout/AppLayout";
import { OutlinesVolumeView } from "@/views/OutlinesVolumeView";
import { OutlinesArcView } from "@/views/OutlinesArcView";
import { OutlinesChapterView } from "@/views/OutlinesChapterView";
import { useCurrentProject } from "@/hooks/useCurrentProject";
import { cn } from "@/lib/utils";
import { HelpIcon } from "@/components/ui/help-icon";
import { helpTexts } from "@/help-texts";

const TABS = [
  { key: "volume", label: "卷大纲" },
  { key: "arc", label: "细纲" },
  { key: "chapter", label: "章纲" },
] as const;

type TabKey = (typeof TABS)[number]["key"];

export default function OutlinesPage() {
  const { project } = useCurrentProject();
  const [tab, setTab] = useState<TabKey>("volume");
  const [, setLoading] = useState(false);

  return (
    <AppLayout>
      <div className="flex h-full flex-col overflow-hidden bg-background">
        <header className="flex flex-wrap items-center justify-between gap-2 border-b border-border px-4 py-4 sm:px-6">
          <h1 className="flex items-center gap-2 text-xl font-bold text-foreground">
            大纲管理
            <HelpIcon title="大纲管理" content={helpTexts.outlines.pageTitle} />
          </h1>
          <div className="flex items-center gap-1 rounded-lg border border-border bg-surface p-1">
            {TABS.map((t) => (
              <button
                key={t.key}
                onClick={() => setTab(t.key)}
                className={cn(
                  "rounded-md px-3 py-1.5 text-sm font-medium transition-colors",
                  tab === t.key
                    ? "bg-primary text-primary-foreground"
                    : "text-foreground hover:bg-foreground/5"
                )}
              >
                {t.label}
              </button>
            ))}
          </div>
        </header>
        <div className="flex-1 overflow-y-auto p-6">
          {tab === "volume" && (
            <OutlinesVolumeView project={project} setLoading={setLoading} />
          )}
          {tab === "arc" && (
            <OutlinesArcView project={project} setLoading={setLoading} />
          )}
          {tab === "chapter" && (
            <OutlinesChapterView project={project} setLoading={setLoading} />
          )}
        </div>
      </div>
    </AppLayout>
  );
}
