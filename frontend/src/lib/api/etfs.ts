import api from './client'
import type {
  ETF,
  ETFListItem,
  Holding,
  HoldingChange,
  Price,
  WatchlistItem,
  ActiveChangesResponse,
  Tag,
  TagHolding,
  SimilarETF,
  CompositionResponse,
} from '@/types/api'

// ETFs
export const etfsApi = {
  getLatestDate: async () => {
    const { data } = await api.get<{ date: string | null }>('/etfs/latest-date')
    return data.date
  },
  getTop: async (limit = 20, sort = 'market_cap', offset = 0, active?: boolean) => {
    const { data } = await api.get<ETFListItem[]>('/etfs/top', { params: { limit, sort, offset, active } })
    return data
  },
  search: async (query: string, limit = 20) => {
    const { data } = await api.get<ETF[]>('/etfs/search', { params: { q: query, limit } })
    return data
  },
  searchUniverse: async (query: string, limit = 20, offset = 0) => {
    const { data } = await api.get<ETFListItem[]>('/etfs/search/universe', { params: { q: query, limit, offset } })
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
  getActiveChanges: async (baseDate?: string, period = '1d') => {
    const params: Record<string, string> = { period }
    if (baseDate) params.base_date = baseDate
    const { data } = await api.get<ActiveChangesResponse>('/etfs/active/changes', { params })
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
  getComposition: async (items: { code: string; weight: number }[], signal?: AbortSignal) => {
    const { data } = await api.post<CompositionResponse>('/etfs/composition', { items }, { signal })
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
    const { data } = await api.get<ETFListItem[]>('/watchlist/etfs')
    return data
  },
  add: async (etfCode: string) => {
    const { data } = await api.post<WatchlistItem>(`/watchlist/${etfCode}`)
    return data
  },
  remove: async (etfCode: string) => {
    await api.delete(`/watchlist/${etfCode}`)
  },
}

// Tags
export const tagsApi = {
  getAll: async () => {
    const { data } = await api.get<Tag[]>('/tags/')
    return data
  },
  getETFs: async (name: string) => {
    const { data } = await api.get<ETFListItem[]>(`/tags/${encodeURIComponent(name)}/etfs`)
    return data
  },
  getHoldings: async (name: string, etfCode: string) => {
    const { data } = await api.get<TagHolding[]>(`/tags/${encodeURIComponent(name)}/etfs/${etfCode}/holdings`)
    return data
  },
}
