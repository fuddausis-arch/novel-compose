import { AppLayout } from "@/components/layout/AppLayout";
import { ExportView } from "@/views/ExportView";
import { useCurrentProject } from "@/hooks/useCurrentProject";

export default function ExportPage() {
  const { project } = useCurrentProject();
  return (
    <AppLayout>
      <div className="flex h-full flex-col overflow-hidden bg-background">
        <header className="flex items-center justify-between border-b border-border px-6 py-4">
          <h1 className="text-xl font-bold text-foreground">导出</h1>
        </header>
        <div className="flex-1 overflow-y-auto p-6">
          <ExportView projectId={project?.id} />
        </div>
      </div>
    </AppLayout>
  );
}
