import { useState } from "react";
import { ProjectNav } from "./ProjectNav";
import { TitleBar } from "./TitleBar";

export interface AppLayoutProps {
  children: React.ReactNode;
  browser?: React.ReactNode;
  rightPanel?: React.ReactNode;
  rightPanelWidth?: string;
  hideNav?: boolean;
}

export function AppLayout({ children, browser, rightPanel, rightPanelWidth = "w-60", hideNav }: AppLayoutProps) {
  const [drawerOpen, setDrawerOpen] = useState(false);
  const [rightDrawerOpen, setRightDrawerOpen] = useState(false);

  return (
    <div className="flex h-screen w-screen flex-col overflow-hidden">
      <TitleBar />
      {!hideNav && (
        <ProjectNav
          leftSlot={
            browser ? (
              <button
                type="button"
                onClick={() => setDrawerOpen(true)}
                className="inline-flex h-8 w-8 items-center justify-center rounded-md hover:bg-foreground/5 md:hidden"
                aria-label="打开目录"
              >
                ☰
              </button>
            ) : null
          }
          rightSlot={
            rightPanel ? (
              <button
                type="button"
                onClick={() => setRightDrawerOpen(true)}
                className="inline-flex h-8 w-8 items-center justify-center rounded-md hover:bg-foreground/5 lg:hidden"
                aria-label="打开侧边栏"
              >
                ☰
              </button>
            ) : null
          }
        />
      )}

      <div className="flex flex-1 overflow-hidden">
        {browser && (
          <>
            <aside className="hidden w-56 overflow-y-auto border-r border-border bg-surface md:block">
              {browser}
            </aside>

            {drawerOpen && (
              <>
                <div
                  className="fixed inset-0 z-40 bg-black/50 md:hidden"
                  onClick={() => setDrawerOpen(false)}
                  aria-hidden="true"
                />
                <aside className="fixed left-0 top-0 z-50 h-full w-56 overflow-y-auto border-r border-border bg-surface md:hidden">
                  <div className="flex h-14 items-center border-b border-border px-4">
                    <button
                      type="button"
                      onClick={() => setDrawerOpen(false)}
                      className="inline-flex h-8 w-8 items-center justify-center rounded-md hover:bg-foreground/5"
                      aria-label="关闭目录"
                    >
                      ✕
                    </button>
                  </div>
                  {browser}
                </aside>
              </>
            )}
          </>
        )}

        <main className="flex min-w-0 flex-1 flex-col overflow-y-auto bg-background">
          {children}
        </main>

        {rightPanel && (
          <>
            <aside className={`hidden ${rightPanelWidth} overflow-y-auto border-l border-border bg-surface lg:block`}>
              {rightPanel}
            </aside>

            {rightDrawerOpen && (
              <>
                <div
                  className="fixed inset-0 z-40 bg-black/50 lg:hidden"
                  onClick={() => setRightDrawerOpen(false)}
                  aria-hidden="true"
                />
                <aside className={`fixed right-0 top-0 z-50 h-full ${rightPanelWidth} overflow-y-auto border-l border-border bg-surface lg:hidden`}>
                  <div className="flex h-14 items-center justify-end border-b border-border px-4">
                    <button
                      type="button"
                      onClick={() => setRightDrawerOpen(false)}
                      className="inline-flex h-8 w-8 items-center justify-center rounded-md hover:bg-foreground/5"
                      aria-label="关闭侧边栏"
                    >
                      ✕
                    </button>
                  </div>
                  {rightPanel}
                </aside>
              </>
            )}
          </>
        )}
      </div>
    </div>
  );
}
