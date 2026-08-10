/**
 * 用户注入配置页（/settings/injection）
 *
 * 会话启动时自动注入的自定义内容：
 * - 全局注入：对所有会话生效
 * - 按项目注入：仅对指定项目生效
 * - 注入位置：system prompt 拼接 / 独立用户消息
 *
 * 复用 df/components/admin/UserInjectionPanel（对接 GET/PUT /api/user-injection）。
 */
import { UserRound } from "lucide-react";
import UserInjectionPanel from "../../df/components/admin/UserInjectionPanel";

export default function InjectionPage() {
  return (
    <div className="h-full overflow-y-auto">
      <div className="mx-auto max-w-3xl space-y-4 p-6">
        <header className="flex items-center gap-2">
          <UserRound className="h-5 w-5 text-indigo-400" />
          <div>
            <h2 className="text-lg font-semibold text-foreground">用户注入配置</h2>
            <p className="text-sm text-muted">
              会话启动时自动注入的自定义内容（写作偏好、禁忌等），支持全局与按项目两种模式
            </p>
          </div>
        </header>
        <UserInjectionPanel />
      </div>
    </div>
  );
}
