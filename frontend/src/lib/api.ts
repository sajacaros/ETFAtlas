import axios from 'axios'
import type {
  User,
  RegisterPayload,
  ETF,
  Holding,
  HoldingChange,
  Price,
  WatchlistItem,
  WatchlistChangesResponse,
  Portfolio,
  PortfolioDetail,
  TargetAllocationItem,
  HoldingItem,
  CalculationResult,
  DashboardResponse,
  TotalHoldingsResponse,
  Tag,
  TagETF,
  TagHolding,
  SimilarETF,
  ChatResponse,
  ChatSessionSummary,
  ChatSessionDetail,
  ChatStep,
  MatchedCodeExample,
  AdminCodeExampleList,
  AdminChatLogList,
  AdminETFTag,
  AdminETFTagList,
  AdminDiscordSettings,
  AdminAISettings,
  AdminAISettingField,
  AdminAITestResult,
  AdminInvitation,
  AdminMember,
  SharedPortfolioListItem,
  SharedPortfolioDetail,
  SharedReturnsResponse,
  SharedReturnsSummary,
  ShareToggleResponse,
  RiskAnalysisResponse,
} from '@/types/api'

const API_URL = import.meta.env.VITE_API_URL || ''

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

// Auth
export const authApi = {
  getSetupStatus: async () => {
    const { data } = await api.get<{ setup_required: boolean }>('/auth/setup-status')
    return data
  },
  setup: async (payload: RegisterPayload) => {
    const { data } = await api.post<User>('/auth/setup', payload)
    return data
  },
  getInvitationStatus: async (inviteToken: string) => {
    const { data } = await api.get<{ valid: boolean }>(`/auth/invitations/${encodeURIComponent(inviteToken)}`)
    return data
  },
  register: async (payload: RegisterPayload, inviteToken: string) => {
    const { data } = await api.post<User>('/auth/register', {
      ...payload,
      invite_token: inviteToken,
    })
    return data
  },
  getPasswordResetStatus: async (resetToken: string) => {
    const { data } = await api.get<{ valid: boolean; username: string | null }>(
      `/auth/password-resets/${encodeURIComponent(resetToken)}`,
    )
    return data
  },
  resetPassword: async (resetToken: string, password: string) => {
    await api.post('/auth/password-reset', { token: resetToken, password })
  },
  login: async (username: string, password: string) => {
    const { data } = await api.post<User>('/auth/login', { username, password })
    return data
  },
  logout: async () => {
    await api.post('/auth/logout')
  },
  getMe: async () => {
    const { data } = await api.get<User>('/auth/me')
    return data
  },
  updateProfile: async (name: string) => {
    const { data } = await api.patch<User>('/auth/me', { name })
    return data
  },
  changePassword: async (currentPassword: string, password: string) => {
    await api.post('/auth/password', { current_password: currentPassword, password })
  },
}

// ETFs
export const etfsApi = {
  getLatestDate: async () => {
    const { data } = await api.get<{ date: string | null }>('/etfs/latest-date')
    return data.date
  },
  getTop: async (limit = 20, sort = 'market_cap', offset = 0) => {
    const { data } = await api.get<{ code: string; name: string; net_assets: number | null; close_price: number | null; return_1d: number | null; return_1w: number | null; return_1m: number | null; market_cap_change_1w: number | null }[]>('/etfs/top', { params: { limit, sort, offset } })
    return data
  },
  search: async (query: string, limit = 20) => {
    const { data } = await api.get<ETF[]>('/etfs/search', { params: { q: query, limit } })
    return data
  },
  searchUniverse: async (query: string, limit = 20, offset = 0) => {
    const { data } = await api.get<{ code: string; name: string; net_assets: number | null; close_price: number | null; return_1d: number | null; return_1w: number | null; return_1m: number | null; market_cap_change_1w: number | null }[]>('/etfs/search/universe', { params: { q: query, limit, offset } })
    return data
  },
  get: async (code: string) => {
    const { data } = await api.get<ETF>(`/etfs/${code}`)
    return data
  },
  getHoldings: async (code: string, date?: string) => {
    const { data } = await api.get<Holding[]>(`/etfs/${code}/holdings`, { params: { date } })
    return data
  },
  getChanges: async (code: string, period = '1d') => {
    const { data } = await api.get<HoldingChange[]>(`/etfs/${code}/changes`, { params: { period } })
    return data
  },
  getPrices: async (code: string, days = 365) => {
    const { data } = await api.get<Price[]>(`/etfs/${code}/prices`, { params: { days } })
    return data
  },
  getTags: async (code: string) => {
    const { data } = await api.get<string[]>(`/etfs/${code}/tags`)
    return data
  },
  getSimilar: async (code: string, minOverlap = 5) => {
    const { data } = await api.get<SimilarETF[]>(`/etfs/${code}/similar`, { params: { min_overlap: minOverlap } })
    return data
  },
}

// Watchlist (즐겨찾기)
export const watchlistApi = {
  getAll: async () => {
    const { data } = await api.get<WatchlistItem[]>('/watchlist/')
    return data
  },
  getCodes: async () => {
    const { data } = await api.get<string[]>('/watchlist/codes')
    return data
  },
  getETFs: async () => {
    const { data } = await api.get<{ code: string; name: string; net_assets: number | null; close_price: number | null; return_1d: number | null; return_1w: number | null; return_1m: number | null; market_cap_change_1w: number | null }[]>('/watchlist/etfs')
    return data
  },
  add: async (etfCode: string) => {
    const { data } = await api.post<WatchlistItem>(`/watchlist/${etfCode}`)
    return data
  },
  remove: async (etfCode: string) => {
    await api.delete(`/watchlist/${etfCode}`)
  },
  getChanges: async (period = '1d', baseDate?: string) => {
    const params: Record<string, string> = { period }
    if (baseDate) params.base_date = baseDate
    const { data } = await api.get<WatchlistChangesResponse>('/watchlist/changes', { params })
    return data
  },
}

// Portfolio
export const portfolioApi = {
  getAll: async () => {
    const { data } = await api.get<Portfolio[]>('/portfolios/')
    return data
  },
  get: async (id: number) => {
    const { data } = await api.get<PortfolioDetail>(`/portfolios/${id}`)
    return data
  },
  create: async (params: { name: string; calculation_base: string; target_total_amount?: number | null }) => {
    const { data } = await api.post<Portfolio>('/portfolios/', params)
    return data
  },
  update: async (id: number, params: { name?: string; calculation_base?: string; target_total_amount?: number | null; snapshot_enabled?: boolean }) => {
    const { data } = await api.put<Portfolio>(`/portfolios/${id}`, params)
    return data
  },
  delete: async (id: number) => {
    await api.delete(`/portfolios/${id}`)
  },
  batchUpdate: async (id: number, params: {
    name?: string;
    calculation_base?: string;
    target_total_amount?: number | null;
    targets: { ticker: string; target_weight: number }[];
    holdings: { ticker: string; quantity: number; avg_price?: number | null }[];
  }) => {
    const { data } = await api.put<PortfolioDetail>(`/portfolios/${id}/batch`, params)
    return data
  },
  reorder: async (orders: { id: number; display_order: number }[]) => {
    await api.put('/portfolios/reorder', { orders })
  },
  addTarget: async (portfolioId: number, params: { ticker: string; target_weight: number }) => {
    const { data } = await api.post<TargetAllocationItem>(`/portfolios/${portfolioId}/targets`, params)
    return data
  },
  updateTarget: async (portfolioId: number, targetId: number, params: { target_weight: number }) => {
    const { data } = await api.put<TargetAllocationItem>(`/portfolios/${portfolioId}/targets/${targetId}`, params)
    return data
  },
  deleteTarget: async (portfolioId: number, targetId: number) => {
    await api.delete(`/portfolios/${portfolioId}/targets/${targetId}`)
  },
  addHolding: async (portfolioId: number, params: { ticker: string; quantity: number; avg_price?: number }) => {
    const { data } = await api.post<HoldingItem>(`/portfolios/${portfolioId}/holdings`, params)
    return data
  },
  updateHolding: async (portfolioId: number, holdingId: number, params: { quantity?: number; avg_price?: number }) => {
    const { data } = await api.put<HoldingItem>(`/portfolios/${portfolioId}/holdings/${holdingId}`, params)
    return data
  },
  deleteHolding: async (portfolioId: number, holdingId: number) => {
    await api.delete(`/portfolios/${portfolioId}/holdings/${holdingId}`)
  },
  calculate: async (portfolioId: number) => {
    const { data } = await api.get<CalculationResult>(`/portfolios/${portfolioId}/calculate`)
    return data
  },
  getDashboard: async (portfolioId: number) => {
    const { data } = await api.get<DashboardResponse>(`/portfolios/${portfolioId}/dashboard`)
    return data
  },
  getTotalDashboard: async () => {
    const { data } = await api.get<DashboardResponse>('/portfolios/dashboard/total')
    return data
  },
  getTotalHoldings: async () => {
    const { data } = await api.get<TotalHoldingsResponse>('/portfolios/dashboard/total/holdings')
    return data
  },
  toggleShare: async (portfolioId: number, isShared: boolean) => {
    const { data } = await api.put<ShareToggleResponse>(`/portfolios/${portfolioId}/share`, { is_shared: isShared })
    return data
  },
  getRiskAnalysis: async (portfolioId: number, period: string = '3m') => {
    const { data } = await api.get<RiskAnalysisResponse>(`/portfolios/${portfolioId}/risk-analysis`, { params: { period } })
    return data
  },
}

// Shared Portfolios
export const sharedApi = {
  getAll: async () => {
    const { data } = await api.get<SharedPortfolioListItem[]>('/shared/')
    return data
  },
  get: async (shareToken: string) => {
    const { data } = await api.get<SharedPortfolioDetail>(`/shared/${shareToken}`)
    return data
  },
  getReturns: async (shareToken: string, period: string = '1m') => {
    const { data } = await api.get<SharedReturnsResponse>(`/shared/${shareToken}/returns`, { params: { period } })
    return data
  },
  getReturnsSummary: async (shareToken: string) => {
    const { data } = await api.get<SharedReturnsSummary>(`/shared/${shareToken}/returns-summary`)
    return data
  },
}

// Tags
export const tagsApi = {
  getAll: async () => {
    const { data } = await api.get<Tag[]>('/tags/')
    return data
  },
  getETFs: async (name: string) => {
    const { data } = await api.get<TagETF[]>(`/tags/${encodeURIComponent(name)}/etfs`)
    return data
  },
  getHoldings: async (name: string, etfCode: string) => {
    const { data } = await api.get<TagHolding[]>(`/tags/${encodeURIComponent(name)}/etfs/${etfCode}/holdings`)
    return data
  },
}

// Chat
// 도구 실행 전 준비 단계: 질문 재작성(맥락이 있을 때만) → 참고 예시 검색 → 에이전트 실행
export type ChatStage = 'refining' | 'searching_examples' | 'thinking'

export interface ChatStreamHandlers {
  onSession?: (session: { session_id: number; title: string }) => void
  onRefinedQuestion?: (question: string) => void
  onStatus?: (stage: ChatStage) => void
  onStepStart?: (step: Pick<ChatStep, 'step_number' | 'code' | 'tool_calls'>) => void
  onStep: (step: ChatStep) => void
  onAnswer: (answer: string) => void
  onError: (error: string) => void
  onMatchedExamples?: (examples: MatchedCodeExample[]) => void
  onDone?: () => void
}

export const chatApi = {
  sendMessage: async (message: string, sessionId: number | null) => {
    const { data } = await api.post<ChatResponse>('/chat/message', { message, session_id: sessionId })
    return data
  },
  listSessions: async () => {
    const { data } = await api.get<ChatSessionSummary[]>('/chat/sessions')
    return data
  },
  getSession: async (id: number) => {
    const { data } = await api.get<ChatSessionDetail>(`/chat/sessions/${id}`)
    return data
  },
  renameSession: async (id: number, title: string) => {
    const { data } = await api.patch<{ id: number; title: string }>(`/chat/sessions/${id}`, { title })
    return data
  },
  deleteSession: async (id: number) => {
    await api.delete(`/chat/sessions/${id}`)
  },
  // 실행 중인 도구는 결과까지 기다리고 다음 단계부터 멈춘다 (결과는 열려 있는 스트림으로 온다)
  stopMessage: async (sessionId: number) => {
    await api.post(`/chat/sessions/${sessionId}/stop`)
  },
  // sessionId가 null이면 서버가 새 세션을 만들고 onSession으로 알려준다
  streamMessage: (message: string, sessionId: number | null, handlers: ChatStreamHandlers) => {
    const abortController = new AbortController()
    const baseUrl = `${API_URL}/api`

    fetch(`${baseUrl}/chat/message/stream`, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
      },
      body: JSON.stringify({ message, session_id: sessionId }),
      signal: abortController.signal,
    })
      .then(async (response) => {
        if (!response.ok) {
          handlers.onError(`서버 오류 (${response.status})`)
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
          const lines = buffer.split('\n\n')
          buffer = lines.pop() || ''

          for (const line of lines) {
            if (line.startsWith(':')) continue  // 연결 유지용 heartbeat
            const data = line.replace(/^data: /, '').trim()
            if (!data || data === '[DONE]') continue
            try {
              const event = JSON.parse(data)
              if (event.type === 'session') handlers.onSession?.(event.data)
              else if (event.type === 'refined_question') handlers.onRefinedQuestion?.(event.data.question)
              else if (event.type === 'status') handlers.onStatus?.(event.data.stage)
              else if (event.type === 'step_start') handlers.onStepStart?.(event.data)
              else if (event.type === 'step') handlers.onStep(event.data)
              else if (event.type === 'answer') handlers.onAnswer(event.data.answer)
              else if (event.type === 'error') handlers.onError(event.data.message)
              else if (event.type === 'matched_examples') handlers.onMatchedExamples?.(event.data.examples)
            } catch { /* ignore parse errors */ }
          }
        }
        handlers.onDone?.()
      })
      .catch((err) => {
        if (err.name !== 'AbortError') handlers.onError(err.message)
      })

    return abortController
  },
}

// Notification
export const notificationApi = {
  getStatus: async () => {
    const { data } = await api.get<{ has_new: boolean; latest_collected_at: string | null }>(
      '/notifications/status'
    )
    return data
  },
  check: async () => {
    const { data } = await api.post<{ checked_at: string }>('/notifications/check')
    return data
  },
}

// Admin
export const adminApi = {
  listCodeExamples: async (status?: string, skip = 0, limit = 50) => {
    const params: Record<string, string | number> = { skip, limit }
    if (status) params.status = status
    const { data } = await api.get<AdminCodeExampleList>('/admin/code-examples', { params })
    return data
  },
  createCodeExample: async (body: { question: string; code: string; description?: string }) => {
    const { data } = await api.post('/admin/code-examples', body)
    return data
  },
  updateCodeExample: async (id: number, body: { question?: string; code?: string; description?: string }) => {
    const { data } = await api.put(`/admin/code-examples/${id}`, body)
    return data
  },
  archiveCodeExample: async (id: number) => {
    const { data } = await api.delete(`/admin/code-examples/${id}`)
    return data
  },
  searchSimilarExamples: async (q: string, topK = 5, generalize = false) => {
    const { data } = await api.get<{ query: string; query_generalized: string | null; results: Array<{ id: number; question: string; question_generalized: string | null; description: string | null; distance: number }> }>(
      '/admin/code-examples/search', { params: { q, top_k: topK, generalize } }
    )
    return data
  },
  listChatLogs: async (status?: string, skip = 0, limit = 50) => {
    const params: Record<string, string | number> = { skip, limit }
    if (status) params.status = status
    const { data } = await api.get<AdminChatLogList>('/admin/chat-logs', { params })
    return data
  },
  reviewChatLog: async (id: number, action: string) => {
    const { data } = await api.post(`/admin/chat-logs/${id}/review`, { action })
    return data
  },
  embedChatLog: async (id: number, body: { question?: string; code?: string; description?: string }) => {
    const { data } = await api.post(`/admin/chat-logs/${id}/embed`, body)
    return data
  },
  withdrawChatLog: async (id: number) => {
    const { data } = await api.post(`/admin/chat-logs/${id}/withdraw`)
    return data
  },
  listETFTags: async () => {
    const { data } = await api.get<AdminETFTagList>('/admin/etf-tags')
    return data
  },
  // tags=null: 수동 지정 해제 (다음 태깅 때 자동으로 다시 계산)
  updateETFTags: async (code: string, tags: string[] | null) => {
    const { data } = await api.put<AdminETFTag>(`/admin/etf-tags/${code}`, { tags })
    return data
  },
  getDiscordSettings: async () => {
    const { data } = await api.get<AdminDiscordSettings>('/admin/settings/discord')
    return data
  },
  // webhook_url: undefined면 기존 주소 유지, ''면 삭제
  updateDiscordSettings: async (body: { enabled: boolean; threshold: number; webhook_url?: string }) => {
    const { data } = await api.put<AdminDiscordSettings>('/admin/settings/discord', body)
    return data
  },
  testDiscordWebhook: async () => {
    const { data } = await api.post<{ ok: boolean }>('/admin/settings/discord/test')
    return data
  },
  getAISettings: async () => {
    const { data } = await api.get<AdminAISettings>('/admin/settings/ai')
    return data
  },
  // 항목이 없으면 기존 값 유지, ''면 지우고 서버 환경변수로 되돌림
  updateAISettings: async (body: Partial<Record<AdminAISettingField, string>>) => {
    const { data } = await api.put<AdminAISettings>('/admin/settings/ai', body)
    return data
  },
  testAISettings: async () => {
    const { data } = await api.post<AdminAITestResult>('/admin/settings/ai/test')
    return data
  },
  listInvitations: async () => {
    const { data } = await api.get<AdminInvitation[]>('/admin/invitations')
    return data
  },
  createInvitation: async () => {
    const { data } = await api.post<AdminInvitation>('/admin/invitations')
    return data
  },
  deleteInvitation: async (id: number) => {
    await api.delete(`/admin/invitations/${id}`)
  },
  listMembers: async () => {
    const { data } = await api.get<AdminMember[]>('/admin/members')
    return data
  },
  updateMemberRole: async (userId: number, isAdmin: boolean) => {
    await api.put(`/admin/members/${userId}/role`, { is_admin: isAdmin })
  },
  logoutMember: async (userId: number) => {
    const { data } = await api.post<{ revoked: number }>(`/admin/members/${userId}/logout`)
    return data
  },
  deleteMember: async (userId: number) => {
    await api.delete(`/admin/members/${userId}`)
  },
  createPasswordReset: async (userId: number) => {
    const { data } = await api.post<{ token: string; expires_at: string }>(`/admin/members/${userId}/password-reset`)
    return data
  },
}

export default api
