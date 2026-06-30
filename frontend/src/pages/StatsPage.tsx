import { AppLayout } from "@/components/layout/AppLayout";
import { WordTrendChart } from "@/components/stats/WordTrendChart";
import { Button } from "@/components/ui/button";
import { useCurrentProject } from "@/hooks/useCurrentProject";

export default function StatsPage() {
  const { project } = useCurrentProject();

  if (!project) return null;

  return (
    <AppLayout>
      <div className="flex h-full flex-col overflow-hidden bg-background">
        <header className="flex items-center justify-between border-b border-border px-6 py-4">
          <h1 className="text-xl font-bold text-foreground">统计</h1>
          <Button variant="primary" onClick={() => {}}>
            导出报告
          </Button>
        </header>

        <div className="flex-1 overflow-y-auto p-6">
          <div className="grid grid-cols-1 gap-4 md:grid-cols-2">
            <div className="rounded-xl border border-border bg-surface-elevated p-4">
              <div className="text-sm font-semibold text-foreground">
                近 7 天字数趋势
              </div>
              <WordTrendChart />
            </div>

            <div className="rounded-xl border border-border bg-surface-elevated p-4">
              <div className="text-sm font-semibold text-foreground">
                伏笔状态
              </div>
              <div className="mt-4 grid grid-cols-3 gap-4">
                <div>
                  <div className="text-xs text-muted">已回收</div>
                  <div className="mt-1 text-2xl font-bold text-success">0</div>
                </div>
                <div>
                  <div className="text-xs text-muted">待回收</div>
                  <div className="mt-1 text-2xl font-bold text-warning">0</div>
                </div>
                <div>
                  <div className="text-xs text-muted">疑似遗漏</div>
                  <div className="mt-1 text-2xl font-bold text-danger">0</div>
                </div>
              </div>
            </div>

            <div className="rounded-xl border border-border bg-surface-elevated p-4">
              <div className="text-sm font-semibold text-foreground">
                角色出场章节分布
              </div>
              <div className="mt-4 text-sm text-muted">暂无数据</div>
            </div>

            <div className="rounded-xl border border-border bg-surface-elevated p-4">
              <div className="text-sm font-semibold text-foreground">
                一致性检查报告
              </div>
              <div className="mt-4 text-sm text-muted">暂无数据</div>
            </div>
          </div>
        </div>
      </div>
    </AppLayout>
  );
}
