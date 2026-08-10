import { AppLayout } from "@/components/layout/AppLayout";
import { TimelineView } from "@/views/TimelineView";
import { useCurrentProject } from "@/hooks/useCurrentProject";

export default function TimelinePage() {
  useCurrentProject();
  return (
    <AppLayout>
      <TimelineView />
    </AppLayout>
  );
}
