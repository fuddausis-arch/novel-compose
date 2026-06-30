import { AppLayout } from "@/components/layout/AppLayout";
import { SettingsView } from "@/views/SettingsView";

export default function SettingsPage() {
  return (
    <AppLayout>
      <div className="max-w-3xl mx-auto px-4 py-6">
        <h1 className="text-2xl font-bold mb-6">设置</h1>
        <SettingsView />
      </div>
    </AppLayout>
  );
}
