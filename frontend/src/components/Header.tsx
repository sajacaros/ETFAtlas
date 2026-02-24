import { useState, useCallback } from 'react'
import { Link } from 'react-router-dom'
import { useAuth } from '@/hooks/useAuth'
import { useNotification } from '@/hooks/useNotification'
import { Button } from '@/components/ui/button'
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger,
} from '@/components/ui/dropdown-menu'
import { Search, PieChart, User, LogOut, MessageCircle, Bell, BookOpen, Shield, Share2 } from 'lucide-react'
import StoryDialog from '@/components/StoryDialog'

export default function Header() {
  const { user, isAuthenticated, logout } = useAuth()
  const { hasNew } = useNotification()
  const [storyOpen, setStoryOpen] = useState(false)
  const [imgError, setImgError] = useState(false)
  const handleImgError = useCallback(() => setImgError(true), [])

  return (
    <header className="border-b bg-white">
      <div className="container mx-auto px-4 h-16 flex items-center justify-between">
        <div className="flex items-center gap-8">
          <Link to="/" className="text-xl font-bold text-primary">
            ETF Atlas
          </Link>
          <nav className="hidden md:flex items-center gap-6">
            <Link
              to="/"
              className="flex items-center gap-2 text-sm text-muted-foreground hover:text-foreground"
            >
              <Search className="w-4 h-4" />
              ETF 검색
            </Link>
            <Link
              to="/portfolio"
              className="flex items-center gap-2 text-sm text-muted-foreground hover:text-foreground"
            >
              <PieChart className="w-4 h-4" />
              포트폴리오
            </Link>
            <Link
              to="/shared"
              className="flex items-center gap-2 text-sm text-muted-foreground hover:text-foreground"
            >
              <Share2 className="w-4 h-4" />
              Shared
            </Link>
            <Link
              to="/watchlist/changes"
              className="flex items-center gap-2 text-sm text-muted-foreground hover:text-foreground relative"
            >
              <Bell className="w-4 h-4" />
              비중 변화
              {hasNew && (
                <span className="absolute -top-1 -right-1 w-2 h-2 bg-red-500 rounded-full" />
              )}
            </Link>
            <Link
              to="/chat"
              className="flex items-center gap-2 text-sm text-muted-foreground hover:text-foreground"
            >
              <MessageCircle className="w-4 h-4" />
              ETF 챗봇
            </Link>
            {user?.is_admin && (
              <Link
                to="/admin"
                className="flex items-center gap-2 text-sm text-muted-foreground hover:text-foreground"
              >
                <Shield className="w-4 h-4" />
                관리
              </Link>
            )}
          </nav>
        </div>

        <div className="flex items-center gap-4">
          <button
            onClick={() => setStoryOpen(true)}
            className="hidden md:flex items-center gap-1.5 text-sm text-muted-foreground hover:text-foreground"
          >
            <BookOpen className="w-4 h-4" />
            Story
          </button>
          {isAuthenticated ? (
            <DropdownMenu>
              <DropdownMenuTrigger asChild>
                <Button variant="ghost" className="flex items-center gap-2">
                  {user?.picture && !imgError ? (
                    <img
                      src={user.picture}
                      alt={user.name || ''}
                      className="w-8 h-8 rounded-full"
                      referrerPolicy="no-referrer"
                      onError={handleImgError}
                    />
                  ) : (
                    <User className="w-5 h-5" />
                  )}
                  <span className="hidden md:inline">{user?.name}</span>
                </Button>
              </DropdownMenuTrigger>
              <DropdownMenuContent align="end">
                <DropdownMenuItem onClick={logout}>
                  <LogOut className="w-4 h-4 mr-2" />
                  로그아웃
                </DropdownMenuItem>
              </DropdownMenuContent>
            </DropdownMenu>
          ) : (
            <Link to="/login">
              <Button>로그인</Button>
            </Link>
          )}
        </div>
      </div>
      <StoryDialog open={storyOpen} onOpenChange={setStoryOpen} />
    </header>
  )
}
