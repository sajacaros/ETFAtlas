import axios from 'axios'
import type {
  User,
  ETF,
  Holding,
  HoldingChange,
  Price,
  Watchlist,
  WatchlistItem,
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
  ChatMessage,
  ChatResponse,
} from '@/types/api'

const API_URL = import.meta.env.VITE_API_URL || ''

const api = axios.create({
  baseURL: `${API_URL}/api`,
  headers: {
    'Content-Type': 'application/json',
  },
})

api.interceptors.request.use((config) => {
  const token = localStorage.getItem('token')
  if (token) {
    config.headers.Authorization = `Bearer ${token}`
  }
  return config
})

// Auth
export const authApi = {
  googleLogin: async (token: string) => {
    const { data } = await api.post<{ access_token: string }>('/auth/google', { token })
    return data
  },
  getMe: async () => {
    const { data } = await api.get<User>('/auth/me')
    return data
  },
}

// ETFs
export const etfsApi = {
  search: async (query: string, limit = 20) => {
    const { data } = await api.get<ETF[]>('/etfs/search', { params: { q: query, limit } })
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

// Watchlist
export const watchlistApi = {
  getAll: async () => {
    const { data } = await api.get<Watchlist[]>('/watchlist/')
    return data
  },
  create: async (name: string) => {
    const { data } = await api.post<Watchlist>('/watchlist/', { name })
    return data
  },
  addETF: async (watchlistId: number, etfCode: string) => {
    const { data } = await api.post<WatchlistItem>(`/watchlist/${watchlistId}/items`, {
      etf_code: etfCode,
    })
    return data
  },
  removeETF: async (watchlistId: number, itemId: number) => {
    await api.delete(`/watchlist/${watchlistId}/items/${itemId}`)
  },
  delete: async (watchlistId: number) => {
    await api.delete(`/watchlist/${watchlistId}`)
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
  update: async (id: number, params: { name?: string; calculation_base?: string; target_total_amount?: number | null }) => {
    const { data } = await api.put<Portfolio>(`/portfolios/${id}`, params)
    return data
  },
  delete: async (id: number) => {
    await api.delete(`/portfolios/${id}`)
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
  backfillSnapshots: async (portfolioId: number) => {
    const { data } = await api.post<{ created: number }>(`/portfolios/${portfolioId}/backfill-snapshots`)
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
export const chatApi = {
  sendMessage: async (message: string, history: ChatMessage[]) => {
    const { data } = await api.post<ChatResponse>('/chat/message', { message, history })
    return data
  },
  streamMessage: (
    message: string,
    history: ChatMessage[],
    onStep: (step: import('@/types/api').ChatStep) => void,
    onAnswer: (answer: string) => void,
    onError: (error: string) => void,
  ) => {
    const abortController = new AbortController()
    const baseUrl = `${API_URL}/api`

    fetch(`${baseUrl}/chat/message/stream`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ message, history }),
      signal: abortController.signal,
    })
      .then(async (response) => {
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
            const data = line.replace(/^data: /, '').trim()
            if (!data || data === '[DONE]') continue
            try {
              const event = JSON.parse(data)
              if (event.type === 'step') onStep(event.data)
              else if (event.type === 'answer') onAnswer(event.data.answer)
              else if (event.type === 'error') onError(event.data.message)
            } catch { /* ignore parse errors */ }
          }
        }
      })
      .catch((err) => {
        if (err.name !== 'AbortError') onError(err.message)
      })

    return abortController
  },
}

export default api
