import { useCallback, useState } from "react";

export type TabType = "chapter" | "asset";

export interface TabItem {
  id: string;
  label: string;
  type: TabType;
}

export interface UseOpenTabsReturn {
  tabs: TabItem[];
  activeTabId: string | null;
  open: (tab: TabItem) => void;
  close: (id: string) => void;
  setActiveTabId: (id: string | null) => void;
}

export function useOpenTabs(): UseOpenTabsReturn {
  const [tabs, setTabs] = useState<TabItem[]>([]);
  const [activeTabId, setActiveTabId] = useState<string | null>(null);

  const open = useCallback((tab: TabItem) => {
    setTabs((prev) => {
      const exists = prev.some((t) => t.id === tab.id);
      return exists ? prev : [...prev, tab];
    });
    setActiveTabId(tab.id);
  }, []);

  const close = useCallback(
    (id: string) => {
      const index = tabs.findIndex((t) => t.id === id);
      if (index === -1) return;

      const next = tabs.filter((t) => t.id !== id);
      setTabs(next);

      if (activeTabId === id) {
        setActiveTabId(
          next.length === 0
            ? null
            : next[Math.min(index, next.length - 1)]?.id ?? null
        );
      }
    },
    [tabs, activeTabId]
  );

  return { tabs, activeTabId, open, close, setActiveTabId };
}
