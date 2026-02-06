import { Routes, Route } from 'react-router-dom'
import { AuthProvider } from './hooks/useAuth'
import Header from './components/Header'
import HomePage from './app/HomePage'
import ETFDetailPage from './app/ETFDetailPage'
import WatchlistPage from './app/WatchlistPage'
import AIPage from './app/AIPage'
import PortfolioPage from './app/PortfolioPage'
import LoginPage from './app/LoginPage'
import AuthCallbackPage from './app/AuthCallbackPage'
import { Toaster } from './components/ui/toaster'

function App() {
  return (
    <AuthProvider>
      <div className="min-h-screen bg-background">
        <Header />
        <main className="container mx-auto py-6 px-4">
          <Routes>
            <Route path="/" element={<HomePage />} />
            <Route path="/etf/:code" element={<ETFDetailPage />} />
            <Route path="/watchlist" element={<WatchlistPage />} />
            <Route path="/portfolio" element={<PortfolioPage />} />
            <Route path="/ai" element={<AIPage />} />
            <Route path="/login" element={<LoginPage />} />
            <Route path="/auth/callback" element={<AuthCallbackPage />} />
          </Routes>
        </main>
        <Toaster />
      </div>
    </AuthProvider>
  )
}

export default App
