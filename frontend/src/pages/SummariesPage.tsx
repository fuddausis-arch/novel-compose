import { AppLayout } from "@/components/layout/AppLayout";
import { SummariesView } from "@/views/SummariesView";
import { useCurrentProject } from "@/hooks/useCurrentProject";

export default function SummariesPage() {
  useCurrentProject();
  return (
    <AppLayout>
      <SummariesView />
    </AppLayout>
  );
}
