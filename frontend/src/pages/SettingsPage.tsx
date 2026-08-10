import { Navigate } from "react-router-dom";

/** 旧设置页已迁移到 /settings 子路由体系，此处仅做重定向 */
export default function SettingsPage() {
  return <Navigate to="/settings" replace />;
}
