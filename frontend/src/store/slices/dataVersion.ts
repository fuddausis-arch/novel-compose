import { create } from "zustand";

/**
 * 轻量「数据版本」store（独立于 useAppStore，供全页面订阅）。
 *
 * 各页面/模块在成功写入数据后调用 bump(key) 使 version[key] +1，
 * 依赖该数据的页面通过 useAutoRefresh 或直接订阅 useDataVersionStore 感知变化并重新拉取。
 * key 约定："bible" / "chapters" / "timeline" / "outlines"。
 */

interface DataVersionState {
  version: Record<string, number>;
  bump: (key: string) => void;
}

export const useDataVersionStore = create<DataVersionState>((set) => ({
  version: {},
  bump: (key) =>
    set((state) => ({
      version: { ...state.version, [key]: (state.version[key] ?? 0) + 1 },
    })),
}));

/** 命令式 bump 助手：供 store slice / 组件在写操作成功后调用。 */
export function bumpDataVersion(key: string): void {
  useDataVersionStore.getState().bump(key);
}
