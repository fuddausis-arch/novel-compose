/** DeterminFlow 融合界面 · 管理页通用 API 辅助 */

/** 统一 fetch 封装：自动解析 FastAPI 错误 detail，非 2xx 抛出带中文信息的 Error */
export async function apiFetch<T = unknown>(path: string, init?: RequestInit): Promise<T> {
  const resp = await fetch(path, init);
  if (!resp.ok) {
    let detail = `请求失败（HTTP ${resp.status}）`;
    try {
      const data = await resp.json();
      if (typeof data?.detail === "string") {
        detail = data.detail;
      } else if (Array.isArray(data?.detail)) {
        // FastAPI 参数校验错误为数组格式：[{loc, msg, type}]
        const msgs = data.detail
          .map((d: { msg?: string }) => d?.msg)
          .filter((m: unknown): m is string => typeof m === "string");
        if (msgs.length > 0) detail = msgs.join("；");
      }
    } catch {
      /* 响应体非 JSON 时沿用默认提示 */
    }
    throw new Error(detail);
  }
  return (await resp.json()) as T;
}

/** JSON 请求体便捷封装（POST/PUT/DELETE） */
export function apiJson<T = unknown>(
  path: string,
  method: "POST" | "PUT" | "DELETE",
  body?: unknown,
): Promise<T> {
  return apiFetch<T>(path, {
    method,
    headers: body !== undefined ? { "Content-Type": "application/json" } : undefined,
    body: body !== undefined ? JSON.stringify(body) : undefined,
  });
}

/** 将字符串列表输入（逗号/换行分隔）解析为数组 */
export function parseListInput(raw: string): string[] {
  return raw
    .split(/[,，\n]/)
    .map((s) => s.trim())
    .filter(Boolean);
}
