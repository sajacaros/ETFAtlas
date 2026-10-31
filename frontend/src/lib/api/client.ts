import axios from 'axios'

export const API_URL = import.meta.env.VITE_API_URL || ''

const api = axios.create({
  baseURL: `${API_URL}/api`,
  headers: {
    'Content-Type': 'application/json',
  },
})

// 인증은 HttpOnly 세션 쿠키(같은 출처 /api)로 — 브라우저가 자동으로 보내므로 JS는 토큰을 다루지 않는다

// 세션이 만료·폐기되면 로그아웃시킨다 (로그인 실패 등 /auth 요청의 401은 각 화면이 처리)
export const AUTH_EXPIRED_EVENT = 'auth:expired'

api.interceptors.response.use(
  (response) => response,
  (error) => {
    const url: string = error.config?.url ?? ''
    if (error.response?.status === 401 && !url.startsWith('/auth/')) {
      window.dispatchEvent(new Event(AUTH_EXPIRED_EVENT))
    }
    return Promise.reject(error)
  }
)

export default api

/** 서버 오류 응답의 detail (검증 오류는 배열, 직접 던진 오류는 문자열). axios 오류가 아니면 undefined */
export function getErrorDetail(err: unknown): unknown {
  return axios.isAxiosError(err) ? err.response?.data?.detail : undefined
}

export interface SSEHandlers<E> {
  onEvent: (event: E) => void
  onError: (message: string) => void
  onDone?: () => void
}

/**
 * POST로 요청하고 응답을 SSE(data: {...}\n\n)로 읽는다. 중지하려면 돌려받은 AbortController를 abort한다.
 * ':'로 시작하는 줄은 연결 유지용 heartbeat라 건너뛴다
 */
export function streamSSE<E>(path: string, body: unknown, handlers: SSEHandlers<E>): AbortController {
  const abortController = new AbortController()

  fetch(`${API_URL}/api${path}`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
    signal: abortController.signal,
  })
    .then(async (response) => {
      if (!response.ok) {
        if (response.status === 401) window.dispatchEvent(new Event(AUTH_EXPIRED_EVENT))
        const errorBody = await response.json().catch(() => null)
        const detail = errorBody?.detail
        handlers.onError(typeof detail === 'string' ? detail : `서버 오류 (${response.status})`)
        return
      }
      const reader = response.body?.getReader()
      if (!reader) return
      const decoder = new TextDecoder()
      let buffer = ''

      while (true) {
        const { done, value } = await reader.read()
        if (done) break
        buffer += decoder.decode(value, { stream: true })
        const chunks = buffer.split('\n\n')
        buffer = chunks.pop() || ''

        for (const chunk of chunks) {
          if (chunk.startsWith(':')) continue  // 연결 유지용 heartbeat
          const data = chunk.replace(/^data: /, '').trim()
          if (!data || data === '[DONE]') continue
          try {
            handlers.onEvent(JSON.parse(data) as E)
          } catch { /* ignore parse errors */ }
        }
      }
    })
    .catch((err) => {
      if (err.name !== 'AbortError') handlers.onError(err.message)
    })
    .finally(() => handlers.onDone?.())

  return abortController
}
