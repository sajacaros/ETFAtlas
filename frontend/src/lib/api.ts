import axios from 'axios'
import type {
  User,
  ETF,
  Stock,
  Holding,
  HoldingChange,
  Price,
  ETFByStock,
  Watchlist,
  WatchlistItem,
  Signal,
  Insight,
  RecommendationResponse,
  Portfolio,
  PortfolioDetail,
  TargetAllocationItem,
  HoldingItem,
  CalculationResult,
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

// Stocks
export const stocksApi = {
  search: async (query: string, limit = 20) => {
    const { data } = await api.get<Stock[]>('/stocks/search', { params: { q: query, limit } })
    return data
  },
  getETFsByStock: async (code: string) => {
    const { data } = await api.get<ETFByStock[]>(`/stocks/${code}/etfs`)
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
  getChanges: async (code: string, days = 30) => {
    const { data } = await api.get<HoldingChange[]>(`/etfs/${code}/changes`, { params: { days } })
    return data
  },
  getPrices: async (code: string, days = 365) => {
    const { data } = await api.get<Price[]>(`/etfs/${code}/prices`, { params: { days } })
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

// AI
export const aiApi = {
  recommend: async (query: string, watchlistId?: number) => {
    const { data } = await api.post<RecommendationResponse>('/ai/recommend', {
      query,
      watchlist_id: watchlistId,
    })
    return data
  },
  getSignals: async () => {
    const { data } = await api.get<Signal[]>('/ai/signals')
    return data
  },
  getInsights: async () => {
    const { data } = await api.get<Insight[]>('/ai/insights')
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
  update: async (id: number, params: { name?: string; calculation_base?: string; target_total_amount?: number | null }) => {
    const { data } = await api.put<Portfolio>(`/portfolios/${id}`, params)
    return data
  },
  delete: async (id: number) => {
    await api.delete(`/portfolios/${id}`)
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
  addHolding: async (portfolioId: number, params: { ticker: string; quantity: number }) => {
    const { data } = await api.post<HoldingItem>(`/portfolios/${portfolioId}/holdings`, params)
    return data
  },
  updateHolding: async (portfolioId: number, holdingId: number, params: { quantity: number }) => {
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
}

export default api
