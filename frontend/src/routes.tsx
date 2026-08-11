import { lazy, Suspense, useEffect, useState } from 'react'
import { Navigate, Route, Routes, useLocation, useNavigate, matchPath } from 'react-router-dom'
import { Loader2, BookOpen } from 'lucide-react'
import { useAppStore } from '@/store'
import { KeepAliveRoutes, type KeepAliveRoute } from '@/components/keep-alive/KeepAliveRoutes'

const DashboardPage = lazy(() => import('./pages/DashboardPage'))
const WritePage = lazy(() => import('./pages/WritePage'))
const AssetsPage = lazy(() => import('./pages/AssetsPage'))
const StatsPage = lazy(() => import('./pages/StatsPage'))
const PlanningPage = lazy(() => import('./pages/PlanningPage'))
const OutlinesPage = lazy(() => import('./pages/OutlinesPage'))
const ImportPage = lazy(() => import('./pages/ImportPage'))
const ExportPage = lazy(() => import('./pages/ExportPage'))
const SummariesPage = lazy(() => import('./pages/SummariesPage'))
const ReferencesPage = lazy(() => import('./pages/ReferencesPage'))
const ChatPage = lazy(() => import('./pages/ChatPage'))
const TimelinePage = lazy(() => import('./pages/TimelinePage'))
const EncyclopediaPage = lazy(() => import('./pages/EncyclopediaPage'))
const AiStylePage = lazy(() => import('./pages/AiStylePage'))
const StorylinePage = lazy(() => import('./pages/StorylinePage'))

// 工作流融合界面（组件实现位于 df/ 目录，统一接入项目内路由）
const ProjectWorkflowPage = lazy(() => import('./df/pages/DFWorkflowPage'))
const ProjectRoundtablePage = lazy(() => import('./df/pages/DFRoundtablePage'))
const ProjectGraphPage = lazy(() => import('./df/pages/DFGraphPage'))

// 设置页子模块（懒加载）
const SettingsLayout = lazy(() => import('./pages/settings/SettingsLayout'))
const SettingsOverview = lazy(() => import('./pages/settings/SettingsOverview'))
const SkillsPage = lazy(() => import('./pages/settings/SkillsPage'))
const RulesPage = lazy(() => import('./pages/settings/RulesPage'))
const OrchestrationPage = lazy(() => import('./pages/settings/OrchestrationPage'))
const ModelsPage = lazy(() => import('./pages/settings/ModelsPage'))
const PluginsPage = lazy(() => import('./pages/settings/PluginsPage'))
const CronPage = lazy(() => import('./pages/settings/CronPage'))
const CompressionPage = lazy(() => import('./pages/settings/CompressionPage'))
const WorkspacePage = lazy(() => import('./pages/settings/WorkspacePage'))
const DistillationPage = lazy(() => import('./pages/settings/DistillationPage'))
const InjectionPage = lazy(() => import('./pages/settings/InjectionPage'))

function Loading() {
  return (
    <div className="flex h-screen w-screen items-center justify-center">
      <Loader2 className="h-8 w-8 animate-spin text-muted" />
    </div>
  )
}

/** 空状态：无项目时的引导页 */
function EmptyState() {
  return (
    <div className="flex h-screen w-screen items-center justify-center bg-background">
      <div className="text-center space-y-4">
        <BookOpen className="h-12 w-12 text-muted mx-auto" />
        <h2 className="text-lg font-semibold text-foreground">还没有作品</h2>
        <p className="text-sm text-muted">点击左上角「选择作品」创建第一个项目开始创作</p>
      </div>
    </div>
  )
}

/** 根路由：自动跳转到最近使用的项目的对话页 */
function RootRedirect() {
  const navigate = useNavigate()
  const projects = useAppStore((s) => s.projects)
  const refreshProjects = useAppStore((s) => s.refreshProjects)
  const [loaded, setLoaded] = useState(false)
  const [timedOut, setTimedOut] = useState(false)

  useEffect(() => {
    // 给一个超时保护：8 秒后强制显示空状态，避免永远转圈
    const timer = setTimeout(() => setTimedOut(true), 8000)
    return () => clearTimeout(timer)
  }, [])

  useEffect(() => {
    if (projects.length === 0 && !loaded) {
      refreshProjects()
        .catch(() => {})
        .finally(() => setLoaded(true))
    }
  }, [projects.length, loaded, refreshProjects])

  useEffect(() => {
    if (loaded && projects.length > 0) {
      // 按更新时间排序，取最近使用的
      const sorted = [...projects].sort(
        (a, b) => new Date(b.updated_at).getTime() - new Date(a.updated_at).getTime()
      )
      navigate(`/projects/${sorted[0].id}/chat`, { replace: true })
    }
  }, [loaded, projects, navigate])

  if (!loaded && !timedOut) {
    return <Loading />
  }

  if (projects.length === 0) {
    return <EmptyState />
  }

  return <Loading />
}

/**
 * 保活路由表：进入过的页面保持挂载（切走只是隐藏，切回状态/滚动/后台任务原样保留）。
 * 设置页子页直接传 children 给 SettingsLayout（其内部优先渲染 children，Outlet 仅作兼容）。
 */
const keepAliveRoutes: KeepAliveRoute[] = [
  { path: '/projects/:projectId/chat', render: () => <ChatPage /> },
  { path: '/projects/:projectId/dashboard', render: () => <DashboardPage /> },
  { path: '/projects/:projectId/planning', render: () => <PlanningPage /> },
  { path: '/projects/:projectId/outlines', render: () => <OutlinesPage /> },
  { path: '/projects/:projectId/write', render: () => <WritePage /> },
  { path: '/projects/:projectId/workflow', render: () => <ProjectWorkflowPage /> },
  { path: '/projects/:projectId/roundtable', render: () => <ProjectRoundtablePage /> },
  { path: '/projects/:projectId/graph', render: () => <ProjectGraphPage /> },
  { path: '/projects/:projectId/assets', render: () => <AssetsPage /> },
  { path: '/projects/:projectId/import', render: () => <ImportPage /> },
  { path: '/projects/:projectId/export', render: () => <ExportPage /> },
  { path: '/projects/:projectId/summaries', render: () => <SummariesPage /> },
  { path: '/projects/:projectId/references', render: () => <ReferencesPage /> },
  { path: '/projects/:projectId/stats', render: () => <StatsPage /> },
  { path: '/projects/:projectId/timeline', render: () => <TimelinePage /> },
  { path: '/projects/:projectId/encyclopedia', render: () => <EncyclopediaPage /> },
  { path: '/projects/:projectId/ai-style', render: () => <AiStylePage /> },
  { path: '/projects/:projectId/storyline', render: () => <StorylinePage /> },
  // 设置页（保活渲染直接传入子页面）
  { path: '/settings', render: () => <SettingsLayout><SettingsOverview /></SettingsLayout> },
  { path: '/settings/skills', render: () => <SettingsLayout><SkillsPage /></SettingsLayout> },
  { path: '/settings/rules', render: () => <SettingsLayout><RulesPage /></SettingsLayout> },
  { path: '/settings/orchestration', render: () => <SettingsLayout><OrchestrationPage /></SettingsLayout> },
  { path: '/settings/models', render: () => <SettingsLayout><ModelsPage /></SettingsLayout> },
  { path: '/settings/plugins', render: () => <SettingsLayout><PluginsPage /></SettingsLayout> },
  { path: '/settings/cron', render: () => <SettingsLayout><CronPage /></SettingsLayout> },
  { path: '/settings/compression', render: () => <SettingsLayout><CompressionPage /></SettingsLayout> },
  { path: '/settings/workspace', render: () => <SettingsLayout><WorkspacePage /></SettingsLayout> },
  { path: '/settings/distillation', render: () => <SettingsLayout><DistillationPage /></SettingsLayout> },
  { path: '/settings/injection', render: () => <SettingsLayout><InjectionPage /></SettingsLayout> },
]

export default function AppRoutes() {
  const location = useLocation()
  // 命中保活路由 → KeepAlive 渲染（页面常驻）；否则走普通重定向路由
  const isKeepAlive = keepAliveRoutes.some((r) => matchPath(r.path, location.pathname))
  return (
    <Suspense fallback={<Loading />}>
      {isKeepAlive ? (
        <KeepAliveRoutes routes={keepAliveRoutes} />
      ) : (
        <Routes>
          {/* 根路由：自动跳转到最近项目的对话页 */}
          <Route path="/" element={<RootRedirect />} />

          {/* 项目列表页（从设置页返回时的目标） */}
          <Route path="/projects" element={<RootRedirect />} />

          {/* 项目内路由：无子路径时跳到对话页 */}
          <Route path="/projects/:projectId" element={<Navigate to="chat" replace />} />

          <Route path="*" element={<RootRedirect />} />
        </Routes>
      )}
    </Suspense>
  )
}
