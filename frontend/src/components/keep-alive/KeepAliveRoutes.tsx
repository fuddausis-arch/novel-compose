/**
 * 路由级 KeepAlive（页面保活）：
 *
 * 目标：界面切换时状态完全保持（表单输入、滚动位置、选中状态、后台任务进度等）。
 * 实现方式：已访问过的页面保持挂载，切换时仅用 display:none 隐藏而非卸载，
 * 因此组件实例不销毁 → React 内部状态、DOM 滚动位置、SSE 流式连接全部原样保留。
 *
 * 关键点：
 * - 模块级 Map 缓存每个页面「首次渲染的 element 实例」，之后永远复用，
 *   React 按 key + 组件类型复用 Fiber，不重新 mount，状态不丢。
 * - 每页独立 Suspense：隐藏页仍在懒加载时不阻塞当前页显示。
 * - 后台任务（蒸馏/交互创作）随组件常驻而保持 SSE 连接，切回立即恢复实时进度。
 */
import { Suspense, type ReactElement } from "react";
import { Routes, Route, useLocation, matchPath, type Location } from "react-router-dom";
import { Loader2 } from "lucide-react";

export interface KeepAliveRoute {
  /** react-router 匹配 pattern，如 "/projects/:projectId/chat" */
  path: string;
  /** 渲染完整页面（含页面自己的布局） */
  render: (location: Location) => ReactElement;
}

interface LiveEntry {
  node: ReactElement;
  order: number;
  /** 页面自己的路由 pattern（如 /projects/:projectId/chat），用于包 <Route> 建立路由上下文 */
  pattern: string;
  /** 页面自己的固定 location：让该页 <Routes> 始终匹配，从而 useParams() 拿到本项目参数 */
  location: Location;
}

/** 模块级保活缓存：key=完整路径（含 projectId，不同项目各自保留） */
const livePages = new Map<string, LiveEntry>();
let orderCounter = 0;

function PageLoading() {
  return (
    <div className="flex h-full w-full items-center justify-center">
      <Loader2 className="h-8 w-8 animate-spin text-muted" />
    </div>
  );
}

export function KeepAliveRoutes({ routes }: { routes: KeepAliveRoute[] }) {
  const location = useLocation();
  const matched = routes.find((r) => matchPath(r.path, location.pathname));
  const activeKey = matched ? location.pathname : null;

  // 首次进入某页面：把 element 实例缓存起来，之后只切可见性，绝不重新挂载
  if (matched && activeKey && !livePages.has(activeKey)) {
    livePages.set(activeKey, {
      node: matched.render(location),
      order: orderCounter++,
      pattern: matched.path,
      // 固定 location 指向页面自身路径：该页 <Routes> 恒匹配 → 建立 RouteContext，
      // 页面内 useParams() 才能拿到 projectId（KeepAlive 手动渲染绕开了 <Route>，必须补上下文）
      location: { pathname: activeKey, search: "", hash: "", state: null, key: activeKey },
    });
  }

  const entries = [...livePages.entries()].sort((a, b) => a[1].order - b[1].order);

  return (
    <>
      {entries.map(([key, entry]) => (
        <div
          key={key}
          style={{ display: key === activeKey ? undefined : "none", height: "100%" }}
        >
          {/* 每页独立 Suspense：隐藏页懒加载不阻塞当前页显示 */}
          <Suspense fallback={key === activeKey ? <PageLoading /> : null}>
            {/* 用 <Routes location={entry.location}> 包一层：为该页提供匹配该页 path 的
                RouteContext（useParams 依赖它），同时不改变全局 location/navigate 行为 */}
            <Routes location={entry.location}>
              <Route path={entry.pattern} element={entry.node} />
            </Routes>
          </Suspense>
        </div>
      ))}
    </>
  );
}
