import { Routes, Route } from 'react-router-dom'
import { AuthProvider } from './hooks/useAuth'
import { NotificationProvider } from './hooks/useNotification'
import { AmountVisibilityProvider } from './hooks/useAmountVisibility'
import Header from './components/Header'
import HomePage from './app/HomePage'
import ETFDetailPage from './app/ETFDetailPage'
import ChatPage from './app/ChatPage'
import PortfolioPage from './app/PortfolioPage'
import PortfolioDashboardPage from './app/PortfolioDashboardPage'
import WatchlistChangesPage from './app/WatchlistChangesPage'
import AdminPage from './app/AdminPage'
import LoginPage from './app/LoginPage'
import AuthCallbackPage from './app/AuthCallbackPage'
import { Toaster } from './components/ui/toaster'

function App() {
  return (
    <AuthProvider>
      <NotificationProvider>
      <AmountVisibilityProvider>
      <div className="min-h-screen bg-background">
        <Header />
        <main className="container mx-auto py-6 px-4">
          <Routes>
            <Route path="/" element={<HomePage />} />
            <Route path="/etf/:code" element={<ETFDetailPage />} />
            <Route path="/portfolio" element={<PortfolioPage />} />
            <Route path="/portfolio/dashboard" element={<PortfolioDashboardPage />} />
            <Route path="/portfolio/:id/dashboard" element={<PortfolioDashboardPage />} />
            <Route path="/watchlist/changes" element={<WatchlistChangesPage />} />
            <Route path="/chat" element={<ChatPage />} />
            <Route path="/admin" element={<AdminPage />} />
            <Route path="/login" element={<LoginPage />} />
            <Route path="/auth/callback" element={<AuthCallbackPage />} />
          </Routes>
        </main>
        <Toaster />
      </div>
      </AmountVisibilityProvider>
      </NotificationProvider>
    </AuthProvider>
  )
}

export default App
