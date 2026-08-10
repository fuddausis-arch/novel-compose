import { AppLayout } from "@/components/layout/AppLayout";
import { PlanningView } from "@/views/PlanningView";
import { useCurrentProject } from "@/hooks/useCurrentProject";
import { HelpIcon } from "@/components/ui/help-icon";
import { helpTexts } from "@/help-texts";

export default function PlanningPage() {
  useCurrentProject();
  return (
    <AppLayout>
      <div className="flex h-full flex-col overflow-hidden bg-background">
        <header className="flex items-center justify-between border-b border-border px-6 py-4">
          <h1 className="flex items-center gap-2 text-xl font-bold text-foreground">
            卷级规划
            <HelpIcon title="整书规划" content={helpTexts.planning.pageTitle} />
          </h1>
        </header>
        <div className="flex-1 overflow-y-auto p-6">
          <PlanningView />
        </div>
      </div>
    </AppLayout>
  );
}
