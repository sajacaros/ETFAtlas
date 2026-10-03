import { Routes, Route, Navigate, useLocation } from 'react-router-dom'
import type { ReactNode } from 'react'
import { AuthProvider, useAuth } from './hooks/useAuth'
import { NotificationProvider } from './hooks/useNotification'
import { AmountVisibilityProvider } from './hooks/useAmountVisibility'
import Header from './components/Header'
import HomePage from './app/HomePage'
import ETFDetailPage from './app/ETFDetailPage'
import ChatPage from './app/ChatPage'
import PortfolioPage from './app/PortfolioPage'
import PortfolioDashboardPage from './app/PortfolioDashboardPage'
import WatchlistChangesPage from './app/WatchlistChangesPage'
import SharedPortfoliosPage from '@/app/SharedPortfoliosPage'
import SharedPortfolioDetailPage from '@/app/SharedPortfolioDetailPage'
import AdminPage from './app/AdminPage'
import LoginPage from './app/LoginPage'
import SetupPage from './app/SetupPage'
import InvitePage from './app/InvitePage'
import { Toaster } from './components/ui/toaster'

// 최초 설치(사용자 0명) 상태면 모든 경로를 /setup으로 보낸다
function SetupGuard({ children }: { children: ReactNode }) {
  const { setupRequired } = useAuth()
  const location = useLocation()
  if (setupRequired && location.pathname !== '/setup') {
    return <Navigate to="/setup" replace />
  }
  return <>{children}</>
}

// 로그인하지 않았으면 /login으로 보낸다 (/login, /setup, /invite/* 제외). 로그인 후 돌아올 경로는 state.from에 담는다
const PUBLIC_PATHS = ['/login', '/setup']

const isPublicPath = (pathname: string) => PUBLIC_PATHS.includes(pathname) || pathname.startsWith('/invite/')

function AuthGuard({ children }: { children: ReactNode }) {
  const { isAuthenticated, isLoading } = useAuth()
  const location = useLocation()
  if (isPublicPath(location.pathname)) return <>{children}</>
  if (isLoading) {
    return (
      <div className="flex items-center justify-center min-h-[60vh]">
        <div className="text-muted-foreground">로딩 중...</div>
      </div>
    )
  }
  if (!isAuthenticated) {
    return <Navigate to="/login" replace state={{ from: location }} />
  }
  return <>{children}</>
}

function App() {
  return (
    <AuthProvider>
      <NotificationProvider>
      <AmountVisibilityProvider>
      <div className="min-h-screen bg-background">
        <Header />
        <main className="container mx-auto py-6 px-4">
          <SetupGuard>
          <AuthGuard>
          <Routes>
            <Route path="/" element={<HomePage />} />
            <Route path="/etf/:code" element={<ETFDetailPage />} />
            <Route path="/portfolio" element={<PortfolioPage />} />
            <Route path="/portfolio/dashboard" element={<PortfolioDashboardPage />} />
            <Route path="/portfolio/:id/dashboard" element={<PortfolioDashboardPage />} />
            <Route path="/watchlist/changes" element={<WatchlistChangesPage />} />
            <Route path="/shared" element={<SharedPortfoliosPage />} />
            <Route path="/shared/:shareToken" element={<SharedPortfolioDetailPage />} />
            <Route path="/chat" element={<ChatPage />} />
            <Route path="/admin" element={<AdminPage />} />
            <Route path="/login" element={<LoginPage />} />
            <Route path="/setup" element={<SetupPage />} />
            <Route path="/invite/:token" element={<InvitePage />} />
          </Routes>
          </AuthGuard>
          </SetupGuard>
        </main>
        <Toaster />
      </div>
      </AmountVisibilityProvider>
      </NotificationProvider>
    </AuthProvider>
  )
}

export default App
