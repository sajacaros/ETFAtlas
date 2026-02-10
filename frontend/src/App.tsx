import { Routes, Route } from 'react-router-dom'
import { AuthProvider } from './hooks/useAuth'
import { AmountVisibilityProvider } from './hooks/useAmountVisibility'
import Header from './components/Header'
import HomePage from './app/HomePage'
import ETFDetailPage from './app/ETFDetailPage'
import WatchlistPage from './app/WatchlistPage'
import AIPage from './app/AIPage'
import PortfolioPage from './app/PortfolioPage'
import PortfolioDashboardPage from './app/PortfolioDashboardPage'
import LoginPage from './app/LoginPage'
import AuthCallbackPage from './app/AuthCallbackPage'
import { Toaster } from './components/ui/toaster'

function App() {
  return (
    <AuthProvider>
      <AmountVisibilityProvider>
      <div className="min-h-screen bg-background">
        <Header />
        <main className="container mx-auto py-6 px-4">
          <Routes>
            <Route path="/" element={<HomePage />} />
            <Route path="/etf/:code" element={<ETFDetailPage />} />
            <Route path="/watchlist" element={<WatchlistPage />} />
            <Route path="/portfolio" element={<PortfolioPage />} />
            <Route path="/portfolio/dashboard" element={<PortfolioDashboardPage />} />
            <Route path="/portfolio/:id/dashboard" element={<PortfolioDashboardPage />} />
            <Route path="/ai" element={<AIPage />} />
            <Route path="/login" element={<LoginPage />} />
            <Route path="/auth/callback" element={<AuthCallbackPage />} />
          </Routes>
        </main>
        <Toaster />
      </div>
      </AmountVisibilityProvider>
    </AuthProvider>
  )
}

export default App
