import { createContext, useContext, useState, useEffect, useCallback, ReactNode } from 'react'
import { notificationApi } from '@/lib/api'
import { useAuth } from '@/hooks/useAuth'
import { getToken } from '@/lib/auth'

interface NotificationContextType {
  hasNew: boolean
  markChecked: () => Promise<void>
}

const NotificationContext = createContext<NotificationContextType | undefined>(undefined)

export function NotificationProvider({ children }: { children: ReactNode }) {
  const { isAuthenticated } = useAuth()
  const [hasNew, setHasNew] = useState(false)

  // 초기 상태 확인
  useEffect(() => {
    if (!isAuthenticated) {
      setHasNew(false)
      return
    }
    notificationApi.getStatus().then((s) => setHasNew(s.has_new)).catch(() => {})
  }, [isAuthenticated])

  // SSE 연결
  useEffect(() => {
    if (!isAuthenticated) return

    const token = getToken()
    if (!token) return

    const API_URL = import.meta.env.VITE_API_URL || ''
    const es = new EventSource(`${API_URL}/api/notifications/stream?token=${token}`)

    es.onmessage = () => {
      setHasNew(true)
    }

    es.onerror = () => {
      es.close()
    }

    return () => es.close()
  }, [isAuthenticated])

  const markChecked = useCallback(async () => {
    await notificationApi.check()
    setHasNew(false)
  }, [])

  return (
    <NotificationContext.Provider value={{ hasNew, markChecked }}>
      {children}
    </NotificationContext.Provider>
  )
}

export function useNotification() {
  const context = useContext(NotificationContext)
  if (context === undefined) {
    throw new Error('useNotification must be used within a NotificationProvider')
  }
  return context
}
