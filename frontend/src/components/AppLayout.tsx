import { useEffect, useState } from 'react'
import type { ReactNode } from 'react'
import { Link, NavLink, useLocation } from 'react-router-dom'
import * as DialogPrimitive from '@radix-ui/react-dialog'
import { useAuth } from '@/hooks/useAuth'
import { useNotification } from '@/hooks/useNotification'
import { useTheme } from '@/hooks/useTheme'
import { Switch } from '@/components/ui/switch'
import {
  Search,
  PieChart,
  LogOut,
  MessageCircle,
  Bell,
  BookOpen,
  Shield,
  Share2,
  Menu,
  X,
  PanelLeftClose,
  PanelLeftOpen,
  Globe2,
  Gamepad2,
  Layers,
} from 'lucide-react'
import type { LucideIcon } from 'lucide-react'
import StoryDialog from '@/components/StoryDialog'
import { cn } from '@/lib/utils'

const COLLAPSED_KEY = 'sidebar-collapsed'

interface NavItem {
  to: string
  label: string
  icon: LucideIcon
  end?: boolean
  dot?: boolean
}

function LogoMark() {
  return (
    <span className="flex h-8 w-8 shrink-0 items-center justify-center rounded-lg logo-mark bg-gradient-to-br from-indigo-500 to-violet-600 text-white shadow-sm shadow-indigo-500/30">
      <Globe2 className="h-[18px] w-[18px]" />
    </span>
  )
}

function Logo() {
  return (
    <Link to="/" className="flex items-center gap-2.5 min-w-0">
      <LogoMark />
      <span className="truncate text-[15px] font-bold tracking-tight">ETF Atlas</span>
    </Link>
  )
}

function NavItemLink({ item, collapsed }: { item: NavItem; collapsed: boolean }) {
  const Icon = item.icon
  return (
    <NavLink
      to={item.to}
      end={item.end}
      title={collapsed ? item.label : undefined}
      className={({ isActive }) =>
        cn(
          'group relative flex h-9 items-center gap-3 rounded-lg px-2.5 text-sm font-medium transition-colors',
          collapsed && 'justify-center px-0',
          isActive
            ? 'bg-accent text-accent-foreground'
            : 'text-muted-foreground hover:bg-muted hover:text-foreground',
        )
      }
    >
      {({ isActive }) => (
        <>
          {isActive && <span className="absolute -left-3 top-1.5 bottom-1.5 w-1 rounded-r-full bg-primary" />}
          <span className="relative">
            <Icon className="h-[18px] w-[18px] shrink-0" />
            {item.dot && collapsed && (
              <span className="absolute -right-1 -top-1 h-2 w-2 rounded-full bg-red-500 ring-2 ring-[hsl(var(--sidebar))]" />
            )}
          </span>
          {!collapsed && <span className="truncate">{item.label}</span>}
          {item.dot && !collapsed && <span className="ml-auto h-2 w-2 rounded-full bg-red-500" />}
        </>
      )}
    </NavLink>
  )
}

function SidebarBody({
  collapsed,
  onToggleCollapse,
  onOpenStory,
}: {
  collapsed: boolean
  onToggleCollapse?: () => void
  onOpenStory: () => void
}) {
  const { user, logout } = useAuth()
  const { hasNew } = useNotification()
  const { theme, toggle: toggleTheme } = useTheme()

  const mainItems: NavItem[] = [
    { to: '/', label: 'ETF 검색', icon: Search, end: true },
    { to: '/portfolio', label: '포트폴리오', icon: PieChart },
    { to: '/composition', label: '구성종목 분석', icon: Layers },
    { to: '/shared', label: '공유 포트폴리오', icon: Share2 },
    { to: '/watchlist/changes', label: '비중 변화', icon: Bell, dot: hasNew },
    { to: '/chat', label: 'ETF 챗봇', icon: MessageCircle },
  ]
  const adminItems: NavItem[] = user?.is_admin ? [{ to: '/admin', label: '관리', icon: Shield }] : []

  const displayName = user?.name || user?.username || ''
  const initial = displayName.charAt(0).toUpperCase() || '?'

  return (
    <div className="flex h-full flex-col">
      <div className={cn('flex h-16 items-center justify-between gap-2 px-4', collapsed && 'justify-center px-0')}>
        {collapsed && onToggleCollapse ? (
          // 접힌 상태에선 로고 자리에 마우스를 올리면 펼치기 아이콘으로 바뀐다
          <button
            onClick={onToggleCollapse}
            title="사이드바 펼치기"
            aria-label="사이드바 펼치기"
            className="group relative flex h-9 w-9 items-center justify-center rounded-lg hover:bg-muted"
          >
            <span className="transition-opacity group-hover:opacity-0">
              <LogoMark />
            </span>
            <PanelLeftOpen className="absolute h-[18px] w-[18px] text-muted-foreground opacity-0 transition-opacity group-hover:opacity-100" />
          </button>
        ) : (
          <>
            <Logo />
            {onToggleCollapse && (
              <button
                onClick={onToggleCollapse}
                title="사이드바 접기"
                aria-label="사이드바 접기"
                className="rounded-lg p-1.5 text-muted-foreground transition-colors hover:bg-muted hover:text-foreground"
              >
                <PanelLeftClose className="h-[18px] w-[18px]" />
              </button>
            )}
          </>
        )}
      </div>

      <nav className={cn('flex-1 overflow-y-auto px-3 py-2', collapsed && 'px-2')}>
        {!collapsed && (
          <div className="px-2.5 pb-2 text-[11px] font-semibold uppercase tracking-wider text-muted-foreground/70">
            메뉴
          </div>
        )}
        <div className="space-y-0.5">
          {mainItems.map((item) => (
            <NavItemLink key={item.to} item={item} collapsed={collapsed} />
          ))}
        </div>

        {adminItems.length > 0 && (
          <>
            {collapsed ? (
              <div className="mx-2 my-3 h-px bg-border" />
            ) : (
              <div className="px-2.5 pb-2 pt-6 text-[11px] font-semibold uppercase tracking-wider text-muted-foreground/70">
                설정
              </div>
            )}
            <div className="space-y-0.5">
              {adminItems.map((item) => (
                <NavItemLink key={item.to} item={item} collapsed={collapsed} />
              ))}
            </div>
          </>
        )}
      </nav>

      <div className={cn('space-y-0.5 px-3 pb-2', collapsed && 'px-2')}>
        {collapsed ? (
          <button
            onClick={toggleTheme}
            title={theme === 'gameboy' ? '기본 테마로' : '게임보이 테마로'}
            className={cn(
              'flex h-9 w-full items-center justify-center rounded-lg text-muted-foreground transition-colors hover:bg-muted hover:text-foreground',
              theme === 'gameboy' && 'text-primary',
            )}
          >
            <Gamepad2 className="h-[18px] w-[18px] shrink-0" />
          </button>
        ) : (
          <label className="flex h-9 w-full cursor-pointer items-center gap-3 rounded-lg px-2.5 text-sm font-medium text-muted-foreground transition-colors hover:bg-muted hover:text-foreground">
            <Gamepad2 className="h-[18px] w-[18px] shrink-0" />
            <span className="flex-1">게임보이 테마</span>
            <Switch checked={theme === 'gameboy'} onCheckedChange={toggleTheme} />
          </label>
        )}
        <button
          onClick={onOpenStory}
          title={collapsed ? 'Story' : undefined}
          className={cn(
            'flex h-9 w-full items-center gap-3 rounded-lg px-2.5 text-sm font-medium text-muted-foreground transition-colors hover:bg-muted hover:text-foreground',
            collapsed && 'justify-center px-0',
          )}
        >
          <BookOpen className="h-[18px] w-[18px] shrink-0" />
          {!collapsed && 'Story'}
        </button>
      </div>

      <div className={cn('border-t p-3', collapsed && 'p-2')}>
        <div className="flex items-center gap-1">
          <NavLink
            to="/profile"
            title={collapsed ? '프로필 설정' : undefined}
            className={({ isActive }) =>
              cn(
                'flex min-w-0 flex-1 items-center gap-3 rounded-lg p-1.5 transition-colors hover:bg-muted focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring',
                collapsed && 'justify-center',
                isActive && 'bg-accent text-accent-foreground hover:bg-accent',
              )
            }
          >
            <span className="flex h-8 w-8 shrink-0 items-center justify-center rounded-full bg-gradient-to-br from-slate-700 to-slate-900 text-xs font-semibold text-white">
              {initial}
            </span>
            {!collapsed && (
              <span className="min-w-0 flex-1">
                <span className="block truncate text-sm font-medium">{displayName}</span>
                <span className="block truncate text-xs text-muted-foreground">프로필 설정</span>
              </span>
            )}
          </NavLink>
          {!collapsed && (
            <button
              onClick={logout}
              title="로그아웃"
              aria-label="로그아웃"
              className="shrink-0 rounded-lg p-2 text-muted-foreground transition-colors hover:bg-muted hover:text-foreground"
            >
              <LogOut className="h-4 w-4" />
            </button>
          )}
        </div>
      </div>
    </div>
  )
}

export default function AppLayout({ children }: { children: ReactNode }) {
  const location = useLocation()
  const [storyOpen, setStoryOpen] = useState(false)
  const [mobileOpen, setMobileOpen] = useState(false)
  const [collapsed, setCollapsed] = useState(() => {
    try {
      return localStorage.getItem(COLLAPSED_KEY) === '1'
    } catch {
      return false
    }
  })

  // 모바일 드로어는 페이지를 옮기면 닫는다
  useEffect(() => {
    setMobileOpen(false)
  }, [location.pathname])

  const toggleCollapse = () => {
    setCollapsed((prev) => {
      const next = !prev
      try {
        localStorage.setItem(COLLAPSED_KEY, next ? '1' : '0')
      } catch {
        // 저장소를 못 쓰면 이번 세션에만 적용한다
      }
      return next
    })
  }

  return (
    <div className="min-h-screen bg-background">
      {/* Sidebar (desktop) */}
      <aside
        className={cn(
          'fixed inset-y-0 left-0 z-30 hidden border-r bg-[hsl(var(--sidebar))] transition-[width] duration-200 lg:block',
          collapsed ? 'w-[68px]' : 'w-60',
        )}
      >
        <SidebarBody
          collapsed={collapsed}
          onToggleCollapse={toggleCollapse}
          onOpenStory={() => setStoryOpen(true)}
        />
      </aside>

      {/* Top bar (mobile) */}
      <header className="sticky top-0 z-30 flex h-14 items-center gap-3 border-b bg-[hsl(var(--sidebar))]/90 px-4 backdrop-blur lg:hidden">
        <button
          onClick={() => setMobileOpen(true)}
          className="-ml-1.5 rounded-lg p-1.5 text-muted-foreground hover:bg-muted hover:text-foreground"
          aria-label="메뉴 열기"
        >
          <Menu className="h-5 w-5" />
        </button>
        <Logo />
      </header>

      {/* Drawer (mobile) */}
      <DialogPrimitive.Root open={mobileOpen} onOpenChange={setMobileOpen}>
        <DialogPrimitive.Portal>
          <DialogPrimitive.Overlay className="fixed inset-0 z-50 bg-slate-950/40 backdrop-blur-[2px] data-[state=open]:animate-in data-[state=closed]:animate-out data-[state=closed]:fade-out-0 data-[state=open]:fade-in-0 lg:hidden" />
          <DialogPrimitive.Content className="fixed inset-y-0 left-0 z-50 w-72 max-w-[85vw] border-r bg-[hsl(var(--sidebar))] shadow-2xl duration-200 data-[state=open]:animate-in data-[state=closed]:animate-out data-[state=closed]:slide-out-to-left data-[state=open]:slide-in-from-left lg:hidden">
            <DialogPrimitive.Title className="sr-only">메뉴</DialogPrimitive.Title>
            <DialogPrimitive.Close
              className="absolute right-3 top-4 rounded-lg p-1.5 text-muted-foreground hover:bg-muted hover:text-foreground"
              aria-label="메뉴 닫기"
            >
              <X className="h-5 w-5" />
            </DialogPrimitive.Close>
            <SidebarBody
              collapsed={false}
              onOpenStory={() => {
                setMobileOpen(false)
                setStoryOpen(true)
              }}
            />
          </DialogPrimitive.Content>
        </DialogPrimitive.Portal>
      </DialogPrimitive.Root>

      <div className={cn('transition-[padding] duration-200', collapsed ? 'lg:pl-[68px]' : 'lg:pl-60')}>
        <main className="w-full max-w-[1600px] px-4 py-6 lg:px-8 lg:py-8">{children}</main>
      </div>

      <StoryDialog open={storyOpen} onOpenChange={setStoryOpen} />
    </div>
  )
}

// 로그인·초대 등 사이드바 없이 보여 줄 화면
export function PublicLayout({ children }: { children: ReactNode }) {
  return (
    <div className="relative min-h-screen overflow-hidden bg-background">
      <div className="pointer-events-none absolute inset-0 bg-[radial-gradient(60rem_30rem_at_50%_-10%,hsl(var(--primary)/0.12),transparent)]" />
      <div className="relative flex min-h-screen flex-col justify-center px-4 py-10">{children}</div>
    </div>
  )
}
