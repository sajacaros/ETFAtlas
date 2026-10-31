import { Routes, Route, Navigate, useLocation } from 'react-router-dom'
import { lazy, Suspense, type ReactNode } from 'react'
import { AuthProvider, useAuth } from './hooks/useAuth'
import { NotificationProvider } from './hooks/useNotification'
import { AmountVisibilityProvider } from './hooks/useAmountVisibility'
import { ThemeProvider } from './hooks/useTheme'
import AppLayout, { PublicLayout } from './components/AppLayout'
import HomePage from './app/HomePage'
import ETFDetailPage from './app/ETFDetailPage'
import ActiveChangesPage from './app/ActiveChangesPage'
import ProfilePage from './app/ProfilePage'
import LoginPage from './app/LoginPage'
import SetupPage from './app/SetupPage'
import InvitePage from './app/InvitePage'
import PasswordResetPage from './app/PasswordResetPage'
import { Toaster } from './components/ui/toaster'

// 무거운 화면(차트·캔버스·PDF·관리자)은 처음 열 때 따로 받는다
const ChatPage = lazy(() => import('./app/ChatPage'))
const CompositionPage = lazy(() => import('./app/CompositionPage'))
const FlowPage = lazy(() => import('./app/FlowPage'))
const PortfolioPage = lazy(() => import('./app/PortfolioPage'))
const PortfolioDashboardPage = lazy(() => import('./app/PortfolioDashboardPage'))
const SharedPortfoliosPage = lazy(() => import('./app/SharedPortfoliosPage'))
const SharedPortfolioDetailPage = lazy(() => import('./app/SharedPortfolioDetailPage'))
const AdminPage = lazy(() => import('./app/admin/AdminPage'))

// 최초 설치(사용자 0명) 상태면 모든 경로를 /setup으로 보낸다
function SetupGuard({ children }: { children: ReactNode }) {
  const { setupRequired } = useAuth()
  const location = useLocation()
  if (setupRequired && location.pathname !== '/setup') {
    return <Navigate to="/setup" replace />
  }
  return <>{children}</>
}

// 로그인하지 않았으면 /login으로 보낸다 (/login, /setup, /invite/*, /reset-password/* 제외). 로그인 후 돌아올 경로는 state.from에 담는다
const PUBLIC_PATHS = ['/login', '/setup']

const isPublicPath = (pathname: string) =>
  PUBLIC_PATHS.includes(pathname) || pathname.startsWith('/invite/') || pathname.startsWith('/reset-password/')

function PageLoading() {
  return (
    <div className="flex items-center justify-center min-h-[60vh]">
      <div className="text-muted-foreground">로딩 중...</div>
    </div>
  )
}

function AuthGuard({ children }: { children: ReactNode }) {
  const { isAuthenticated, isLoading } = useAuth()
  const location = useLocation()
  if (isPublicPath(location.pathname)) return <>{children}</>
  if (isLoading) return <PageLoading />
  if (!isAuthenticated) {
    return <Navigate to="/login" replace state={{ from: location }} />
  }
  return <>{children}</>
}

// 로그인 전이거나 공개 경로면 사이드바 없이 가운데 정렬한 화면으로 보여 준다
function Shell({ children }: { children: ReactNode }) {
  const { isAuthenticated, setupRequired } = useAuth()
  const location = useLocation()
  if (setupRequired || !isAuthenticated || isPublicPath(location.pathname)) {
    return <PublicLayout>{children}</PublicLayout>
  }
  return <AppLayout>{children}</AppLayout>
}

function App() {
  return (
    <ThemeProvider>
    <AuthProvider>
      <NotificationProvider>
      <AmountVisibilityProvider>
      <Shell>
          <SetupGuard>
          <AuthGuard>
          <Suspense fallback={<PageLoading />}>
          <Routes>
            <Route path="/" element={<HomePage />} />
            <Route path="/etf/:code" element={<ETFDetailPage />} />
            <Route path="/portfolio" element={<PortfolioPage />} />
            <Route path="/portfolio/dashboard" element={<PortfolioDashboardPage />} />
            <Route path="/portfolio/:id" element={<PortfolioPage />} />
            <Route path="/portfolio/:id/dashboard" element={<PortfolioDashboardPage />} />
            <Route path="/changes" element={<ActiveChangesPage />} />
            <Route path="/composition" element={<CompositionPage />} />
            <Route path="/shared" element={<SharedPortfoliosPage />} />
            <Route path="/shared/:shareToken" element={<SharedPortfolioDetailPage />} />
            <Route path="/chat" element={<ChatPage />} />
            <Route path="/flows" element={<FlowPage />} />
            <Route path="/admin" element={<AdminPage />} />
            <Route path="/profile" element={<ProfilePage />} />
            <Route path="/login" element={<LoginPage />} />
            <Route path="/setup" element={<SetupPage />} />
            <Route path="/invite/:token" element={<InvitePage />} />
            <Route path="/reset-password/:token" element={<PasswordResetPage />} />
          </Routes>
          </Suspense>
          </AuthGuard>
          </SetupGuard>
      </Shell>
      <Toaster />
      </AmountVisibilityProvider>
      </NotificationProvider>
    </AuthProvider>
    </ThemeProvider>
  )
}

export default App
