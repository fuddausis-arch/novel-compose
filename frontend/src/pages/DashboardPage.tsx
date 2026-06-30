import { useNavigate } from "react-router-dom";

import { AppLayout } from "@/components/layout/AppLayout";
import { ProgressCard } from "@/components/dashboard/ProgressCard";
import { StatCard } from "@/components/dashboard/StatCard";
import { Button } from "@/components/ui/button";
import { useCurrentProject } from "@/hooks/useCurrentProject";

export default function DashboardPage() {
  const navigate = useNavigate();
  const { project } = useCurrentProject();

  if (!project) return null;

  return (
    <AppLayout>
      <div className="flex h-full flex-col overflow-hidden bg-background">
        <header className="flex items-center justify-between border-b border-border px-6 py-4">
          <h1 className="text-xl font-bold text-foreground">工作台</h1>
          <Button
            variant="primary"
            onClick={() => navigate(`/projects/${project.id}/write`)}
          >
            继续写作
          </Button>
        </header>

        <div className="flex-1 overflow-y-auto p-6">
          <div className="grid grid-cols-2 gap-4 sm:grid-cols-4">
            <StatCard label="总字数" value={0} />
            <StatCard label="章节数" value={0} />
            <StatCard label="角色数" value={0} />
            <StatCard label="伏笔待回收" value={0} tone="warning" />
          </div>

          <div className="mt-4 grid grid-cols-1 gap-4 lg:grid-cols-3">
            <div className="space-y-4 lg:col-span-2">
              <ProgressCard />

              <div className="rounded-xl border border-border bg-surface-elevated p-4">
                <div className="text-sm font-semibold text-foreground">
                  最近动态
                </div>
                <div className="mt-4 text-sm text-muted">暂无动态</div>
              </div>
            </div>

            <div className="rounded-xl border border-border bg-surface-elevated p-4">
              <div className="text-sm font-semibold text-foreground">
                快速操作
              </div>
              <div className="mt-4 grid grid-cols-1 gap-2">
                <Button variant="outline" onClick={() => {}}>
                  ✍️ 新建章节
                </Button>
                <Button variant="outline" onClick={() => {}}>
                  👤 添加角色
                </Button>
                <Button variant="outline" onClick={() => {}}>
                  🪝 创建伏笔
                </Button>
                <Button variant="outline" onClick={() => {}}>
                  🤖 一致性检查
                </Button>
              </div>
            </div>
          </div>
        </div>
      </div>
    </AppLayout>
  );
}
