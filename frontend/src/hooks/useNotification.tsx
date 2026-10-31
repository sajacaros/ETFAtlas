import { createContext, useContext, useState, useEffect, useCallback, ReactNode } from 'react'
import { notificationApi } from '@/lib/api'
import { useAuth } from '@/hooks/useAuth'

interface NotificationContextType {
  hasNew: boolean
  markChecked: () => Promise<void>
}

const NotificationContext = createContext<NotificationContextType | undefined>(undefined)

export function NotificationProvider({ children }: { children: ReactNode }) {
  const { isAuthenticated } = useAuth()
  const [hasNew, setHasNew] = useState(false)

  const refreshStatus = useCallback(() => {
    notificationApi.getStatus().then((s) => setHasNew(s.has_new)).catch(() => {})
  }, [])

  // 초기 상태 확인
  useEffect(() => {
    if (!isAuthenticated) {
      setHasNew(false)
      return
    }
    refreshStatus()
  }, [isAuthenticated, refreshStatus])

  // SSE 연결 — 끊기면 다시 잇고, 다시 이어지면 끊긴 동안 온 알림을 놓치지 않게 상태를 다시 조회한다
  useEffect(() => {
    if (!isAuthenticated) return

    // 같은 출처라 세션 쿠키가 자동으로 붙는다
    const API_URL = import.meta.env.VITE_API_URL || ''
    let es: EventSource | null = null
    let retryTimer: ReturnType<typeof setTimeout> | undefined
    let retryDelay = 1000
    let connectedOnce = false
    let disposed = false

    const connect = () => {
      es = new EventSource(`${API_URL}/api/notifications/stream`)
      es.onopen = () => {
        retryDelay = 1000
        if (connectedOnce) refreshStatus()
        connectedOnce = true
      }
      es.onmessage = () => {
        setHasNew(true)
      }
      // 네트워크가 잠깐 끊기면 브라우저가 알아서 다시 잇는다(CONNECTING).
      // 서버가 오류로 응답해 완전히 닫혔을 때만(CLOSED) 간격을 늘려 가며 직접 다시 연다
      es.onerror = () => {
        if (!es || es.readyState !== EventSource.CLOSED || disposed) return
        es.close()
        retryTimer = setTimeout(connect, retryDelay)
        retryDelay = Math.min(retryDelay * 2, 30000)
      }
    }
    connect()

    return () => {
      disposed = true
      clearTimeout(retryTimer)
      es?.close()
    }
  }, [isAuthenticated, refreshStatus])

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
