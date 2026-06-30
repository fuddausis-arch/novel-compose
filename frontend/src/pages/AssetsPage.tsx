import { useState } from "react";

import { AppLayout } from "@/components/layout/AppLayout";
import { ProjectBrowser } from "@/components/layout/ProjectBrowser";
import { AssetCards } from "@/components/assets/AssetCards";
import { AssetTypeNav, type AssetNavType } from "@/components/assets/AssetTypeNav";
import { useCurrentProject } from "@/hooks/useCurrentProject";

export default function AssetsPage() {
  const [type, setType] = useState<AssetNavType>("characters");
  useCurrentProject();

  return (
    <AppLayout browser={<ProjectBrowser />}>
      <div className="flex h-full overflow-hidden">
        <AssetTypeNav value={type} onChange={setType} />
        <AssetCards type={type} />
      </div>
    </AppLayout>
  );
}
