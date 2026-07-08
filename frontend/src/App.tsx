import { useEffect } from 'react'
import { BrowserRouter, Routes, Route, Navigate, useNavigate, useLocation } from 'react-router-dom'
import { useAuthStore } from './store/auth'
import { apiMe } from './api/auth'
import { AppLayout } from './layouts/AppLayout'
import { AuthPage }          from './pages/AuthPage'
import { ResearchDashboard } from './pages/ResearchDashboard'
import { AdminPanel }        from './pages/AdminPanel'
import { ProfilePage }       from './pages/ProfilePage'
import { StockAnalysisPage } from './pages/StockAnalysisPage'
import { MarketDashboard }   from './pages/MarketDashboard'
import { WatchlistPage }     from './pages/WatchlistPage'
import { PortfolioPage }     from './pages/PortfolioPage'
import { AlertsPage }         from './pages/AlertsPage'
import { EarningsPage }       from './pages/EarningsPage'
import { SectorHeatmapPage }  from './pages/SectorHeatmapPage'
import { OptionsPage }        from './pages/OptionsPage'
import { ScreenerPage }      from './pages/ScreenerPage'
import { JournalPage }       from './pages/JournalPage'

// Silently refresh the user object in the background after mount.
// If the token is stale, the 401 interceptor in client.ts handles the redirect.
function SessionRefresh() {
  const { token, setAuth } = useAuthStore()
  useEffect(() => {
    if (!token) return
    apiMe()
      .then(u => setAuth(token, u))
      .catch(() => {/* 401 interceptor handles redirect */})
  }, [])
  return null
}

function AuthGuard({ children }: { children: React.ReactNode }) {
  const { token } = useAuthStore()
  const location  = useLocation()
  if (!token) return <Navigate to="/login" state={{ from: location }} replace />
  return <>{children}</>
}

function AdminGuard({ children }: { children: React.ReactNode }) {
  const { user } = useAuthStore()
  if (user?.role !== 'admin') return <Navigate to="/research" replace />
  return <>{children}</>
}

export default function App() {
  return (
    <BrowserRouter>
      <SessionRefresh />
      <Routes>
        <Route path="/login" element={<AuthPage />} />
        <Route path="/" element={
          <AuthGuard>
            <AppLayout />
          </AuthGuard>
        }>
          <Route index element={<Navigate to="/market" replace />} />
          <Route path="market"    element={<MarketDashboard />} />
          <Route path="research"  element={<ResearchDashboard />} />
          <Route path="stocks"    element={<StockAnalysisPage />} />
          <Route path="watchlist" element={<WatchlistPage />} />
          <Route path="portfolio" element={<PortfolioPage />} />
          <Route path="alerts"    element={<AlertsPage />} />
          <Route path="earnings"  element={<EarningsPage />} />
          <Route path="sectors"   element={<SectorHeatmapPage />} />
          <Route path="options"   element={<OptionsPage />} />
          <Route path="screener"  element={<ScreenerPage />} />
          <Route path="journal"   element={<JournalPage />} />
          <Route path="admin"     element={<AdminGuard><AdminPanel /></AdminGuard>} />
          <Route path="profile"   element={<ProfilePage />} />
        </Route>
        <Route path="*" element={<Navigate to="/market" replace />} />
      </Routes>
    </BrowserRouter>
  )
}
