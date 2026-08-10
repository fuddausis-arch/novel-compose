import { AppLayout } from "@/components/layout/AppLayout";
import AiStyleView from "@/views/AiStyleView";
import { useCurrentProject } from "@/hooks/useCurrentProject";

export default function AiStylePage() {
  useCurrentProject();
  return (
    <AppLayout>
      <AiStyleView />
    </AppLayout>
  );
}
