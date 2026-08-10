import { AppLayout } from "@/components/layout/AppLayout";
import StorylineView from "@/views/StorylineView";
import { useCurrentProject } from "@/hooks/useCurrentProject";

export default function StorylinePage() {
  useCurrentProject();
  return (
    <AppLayout>
      <StorylineView />
    </AppLayout>
  );
}
