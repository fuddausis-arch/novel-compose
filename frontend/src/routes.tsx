import { lazy, Suspense, useEffect, useState } from 'react'
import { Navigate, Route, Routes, useNavigate } from 'react-router-dom'
import { Loader2, BookOpen } from 'lucide-react'
import { useAppStore } from '@/store'

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

export default function AppRoutes() {
  return (
    <Suspense fallback={<Loading />}>
      <Routes>
        {/* 根路由：自动跳转到最近项目的对话页 */}
        <Route path="/" element={<RootRedirect />} />

        {/* 项目列表页（从设置页返回时的目标） */}
        <Route path="/projects" element={<RootRedirect />} />

        {/* 项目内路由：对话为默认页 */}
        <Route path="/projects/:projectId" element={<Navigate to="chat" replace />} />
        <Route path="/projects/:projectId/chat" element={<ChatPage />} />
        <Route path="/projects/:projectId/dashboard" element={<DashboardPage />} />
        <Route path="/projects/:projectId/planning" element={<PlanningPage />} />
        <Route path="/projects/:projectId/outlines" element={<OutlinesPage />} />
        <Route path="/projects/:projectId/write" element={<WritePage />} />
        <Route path="/projects/:projectId/workflow" element={<ProjectWorkflowPage />} />
        <Route path="/projects/:projectId/roundtable" element={<ProjectRoundtablePage />} />
        <Route path="/projects/:projectId/graph" element={<ProjectGraphPage />} />
        <Route path="/projects/:projectId/assets" element={<AssetsPage />} />
        <Route path="/projects/:projectId/import" element={<ImportPage />} />
        <Route path="/projects/:projectId/export" element={<ExportPage />} />
        <Route path="/projects/:projectId/summaries" element={<SummariesPage />} />
        <Route path="/projects/:projectId/references" element={<ReferencesPage />} />
        <Route path="/projects/:projectId/stats" element={<StatsPage />} />
        <Route path="/projects/:projectId/timeline" element={<TimelinePage />} />
        <Route path="/projects/:projectId/encyclopedia" element={<EncyclopediaPage />} />
        <Route path="/projects/:projectId/ai-style" element={<AiStylePage />} />
        <Route path="/projects/:projectId/storyline" element={<StorylinePage />} />

        {/* 全局设置（带子路由布局） */}
        <Route path="/settings" element={<SettingsLayout />}>
          <Route index element={<SettingsOverview />} />
          <Route path="skills" element={<SkillsPage />} />
          <Route path="rules" element={<RulesPage />} />
          <Route path="orchestration" element={<OrchestrationPage />} />
          <Route path="models" element={<ModelsPage />} />
          <Route path="plugins" element={<PluginsPage />} />
          <Route path="cron" element={<CronPage />} />
          <Route path="compression" element={<CompressionPage />} />
          <Route path="workspace" element={<WorkspacePage />} />
          <Route path="distillation" element={<DistillationPage />} />
          <Route path="injection" element={<InjectionPage />} />
        </Route>

        <Route path="*" element={<RootRedirect />} />
      </Routes>
    </Suspense>
  )
}
