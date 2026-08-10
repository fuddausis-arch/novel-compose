import { AppLayout } from "@/components/layout/AppLayout";
import { EncyclopediaView } from "@/views/EncyclopediaView";
import { useCurrentProject } from "@/hooks/useCurrentProject";

export default function EncyclopediaPage() {
  useCurrentProject();
  return (
    <AppLayout>
      <EncyclopediaView />
    </AppLayout>
  );
}
