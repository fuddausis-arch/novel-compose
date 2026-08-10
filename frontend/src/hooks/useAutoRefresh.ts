import { type DependencyList, useEffect, useRef } from "react";
import { useDataVersionStore } from "@/store/slices/dataVersion";

/**
 * 统一数据自动刷新 hook：
 * 1. 挂载 / deps 变化时执行 fetcher；
 * 2. 窗口重新获得焦点（window focus）时执行 fetcher；
 * 3. useDataVersionStore 中对应 key 的版本号变化（其他页面写入数据后 bump）时执行 fetcher。
 *
 * 首次渲染时版本监听跳过，避免与挂载拉取重复请求。
 *
 * @param keys   订阅的版本 key（如 "bible" / "chapters"，可传数组）
 * @param fetcher 数据拉取函数（建议 useCallback 包裹）
 * @param deps   与 fetcher 关联的依赖数组（projectId 等变化时重新拉取）
 */
export function useAutoRefresh(
  keys: string | string[],
  fetcher: () => void | Promise<void>,
  deps: DependencyList = [],
): void {
  const keyList = Array.isArray(keys) ? keys : [keys];
  const versions = useDataVersionStore((s) =>
    keyList.map((k) => s.version[k] ?? 0).join(":"),
  );

  const fetcherRef = useRef(fetcher);
  fetcherRef.current = fetcher;

  // 挂载 / 依赖变化时拉取
  useEffect(() => {
    void fetcherRef.current();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, deps);

  // 版本号变化时拉取（跳过首次渲染）
  const mountedRef = useRef(false);
  useEffect(() => {
    if (!mountedRef.current) {
      mountedRef.current = true;
      return;
    }
    void fetcherRef.current();
  }, [versions]);

  // 窗口 focus 时拉取
  useEffect(() => {
    const onFocus = () => {
      void fetcherRef.current();
    };
    window.addEventListener("focus", onFocus);
    return () => window.removeEventListener("focus", onFocus);
  }, []);
}
