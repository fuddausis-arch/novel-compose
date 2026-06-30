import { ProjectNav } from "./ProjectNav";

export interface AppLayoutProps {
  children: React.ReactNode;
  browser?: React.ReactNode;
  rightPanel?: React.ReactNode;
  hideNav?: boolean;
}

export function AppLayout({ children, browser, rightPanel, hideNav }: AppLayoutProps) {
  return (
    <div className="flex h-screen w-screen flex-col overflow-hidden">
      {!hideNav && <ProjectNav />}

      <div className="flex flex-1 overflow-hidden">
        {browser && (
          <aside className="hidden w-56 overflow-y-auto border-r border-border bg-surface md:block">
            {browser}
          </aside>
        )}

        <main className="flex min-w-0 flex-1 flex-col overflow-hidden bg-background">
          {children}
        </main>

        {rightPanel && (
          <aside className="hidden w-60 overflow-y-auto border-l border-border bg-surface lg:block">
            {rightPanel}
          </aside>
        )}
      </div>
    </div>
  );
}
