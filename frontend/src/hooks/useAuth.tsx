import { createContext, useContext, useState, useEffect, ReactNode } from 'react'
import { authApi, AUTH_EXPIRED_EVENT } from '@/lib/api'
import type { User, RegisterPayload } from '@/types/api'

interface AuthContextType {
  user: User | null
  isLoading: boolean
  isAuthenticated: boolean
  setupRequired: boolean
  login: (username: string, password: string) => Promise<void>
  register: (payload: RegisterPayload, inviteToken: string) => Promise<void>
  setup: (payload: RegisterPayload) => Promise<void>
  logout: () => Promise<void>
}

const AuthContext = createContext<AuthContextType | undefined>(undefined)

export function AuthProvider({ children }: { children: ReactNode }) {
  const [user, setUser] = useState<User | null>(null)
  const [isLoading, setIsLoading] = useState(true)
  const [setupRequired, setSetupRequired] = useState(false)

  useEffect(() => {
    const init = async () => {
      try {
        const { setup_required } = await authApi.getSetupStatus()
        setSetupRequired(setup_required)
        if (setup_required) return
        setUser(await authApi.getMe())  // 세션 쿠키가 없거나 만료면 401 → 미로그인
      } catch {
        setUser(null)
      } finally {
        setIsLoading(false)
      }
    }
    init()
  }, [])

  useEffect(() => {
    const onExpired = () => setUser(null)
    window.addEventListener(AUTH_EXPIRED_EVENT, onExpired)
    return () => window.removeEventListener(AUTH_EXPIRED_EVENT, onExpired)
  }, [])

  const login = async (username: string, password: string) => {
    setUser(await authApi.login(username, password))
  }

  const register = async (payload: RegisterPayload, inviteToken: string) => {
    setUser(await authApi.register(payload, inviteToken))
  }

  const setup = async (payload: RegisterPayload) => {
    const created = await authApi.setup(payload)
    setSetupRequired(false)
    setUser(created)
  }

  const logout = async () => {
    try {
      await authApi.logout()
    } finally {
      setUser(null)
    }
  }

  return (
    <AuthContext.Provider
      value={{
        user,
        isLoading,
        isAuthenticated: !!user,
        setupRequired,
        login,
        register,
        setup,
        logout,
      }}
    >
      {children}
    </AuthContext.Provider>
  )
}

export function useAuth() {
  const context = useContext(AuthContext)
  if (context === undefined) {
    throw new Error('useAuth must be used within an AuthProvider')
  }
  return context
}
