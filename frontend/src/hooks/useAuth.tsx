import { createContext, useContext, useState, useEffect, ReactNode } from 'react'
import { authApi } from '@/lib/api'
import { setToken, getToken, removeToken } from '@/lib/auth'
import type { User, RegisterPayload } from '@/types/api'

interface AuthContextType {
  user: User | null
  isLoading: boolean
  isAuthenticated: boolean
  setupRequired: boolean
  login: (username: string, password: string) => Promise<void>
  register: (payload: RegisterPayload) => Promise<void>
  setup: (payload: RegisterPayload) => Promise<void>
  logout: () => void
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
        if (setup_required) {
          removeToken()
          return
        }
        if (getToken()) {
          setUser(await authApi.getMe())
        }
      } catch {
        removeToken()
      } finally {
        setIsLoading(false)
      }
    }
    init()
  }, [])

  const applyToken = async (accessToken: string) => {
    setToken(accessToken)
    setUser(await authApi.getMe())
  }

  const login = async (username: string, password: string) => {
    const { access_token } = await authApi.login(username, password)
    await applyToken(access_token)
  }

  const register = async (payload: RegisterPayload) => {
    const { access_token } = await authApi.register(payload)
    await applyToken(access_token)
  }

  const setup = async (payload: RegisterPayload) => {
    const { access_token } = await authApi.setup(payload)
    setSetupRequired(false)
    await applyToken(access_token)
  }

  const logout = () => {
    removeToken()
    setUser(null)
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
