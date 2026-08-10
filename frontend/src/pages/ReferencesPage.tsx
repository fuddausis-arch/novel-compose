import { AppLayout } from "@/components/layout/AppLayout";
import { ReferencesView } from "@/views/ReferencesView";
import { useCurrentProject } from "@/hooks/useCurrentProject";

export default function ReferencesPage() {
  const { project } = useCurrentProject();
  if (!project) return null;
  return (
    <AppLayout>
      <div className="flex h-full flex-col overflow-hidden bg-background">
        <header className="flex items-center justify-between border-b border-border px-6 py-4">
          <h1 className="text-xl font-bold text-foreground">参考文件</h1>
        </header>
        <div className="flex-1 overflow-y-auto p-6">
          <ReferencesView projectId={project.id} />
        </div>
      </div>
    </AppLayout>
  );
}
