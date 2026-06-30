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

  const close = useCallback((id: string) => {
    setTabs((prev) => {
      const index = prev.findIndex((t) => t.id === id);
      if (index === -1) return prev;

      const next = prev.filter((t) => t.id !== id);

      setActiveTabId((currentActiveId) => {
        if (currentActiveId !== id) return currentActiveId;
        if (next.length === 0) return null;

        const adjacentIndex = Math.min(index, next.length - 1);
        return next[adjacentIndex]?.id ?? null;
      });

      return next;
    });
  }, []);

  return { tabs, activeTabId, open, close, setActiveTabId };
}
