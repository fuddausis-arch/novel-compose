import { Navigate, Route, Routes } from 'react-router-dom'
import ProjectsPage from './pages/ProjectsPage'
import DashboardPage from './pages/DashboardPage'
import WritePage from './pages/WritePage'
import AssetsPage from './pages/AssetsPage'
import StatsPage from './pages/StatsPage'
import SettingsPage from './pages/SettingsPage'

export default function AppRoutes() {
  return (
    <Routes>
      <Route path="/" element={<Navigate to="/projects" replace />} />
      <Route path="/projects" element={<ProjectsPage />} />
      <Route path="/projects/:projectId/dashboard" element={<DashboardPage />} />
      <Route path="/projects/:projectId/write" element={<WritePage />} />
      <Route path="/projects/:projectId/assets" element={<AssetsPage />} />
      <Route path="/projects/:projectId/stats" element={<StatsPage />} />
      <Route path="/settings" element={<SettingsPage />} />
      <Route path="*" element={<Navigate to="/projects" replace />} />
    </Routes>
  )
}
