import api from './client'
import type {
  AccountType,
  Portfolio,
  PortfolioDetail,
  CalculationResult,
  DashboardResponse,
  TotalHoldingsResponse,
  SharedPortfolioListItem,
  SharedPortfolioDetail,
  SharedReturnsResponse,
  SharedReturnsSummary,
  ShareCreateResponse,
  RiskAnalysisResponse,
} from '@/types/api'

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
  create: async (params: { name: string; account_types?: AccountType[]; calculation_base: string; target_total_amount?: number | null; targets?: { ticker: string; target_weight: number }[] }) => {
    const { data } = await api.post<Portfolio>('/portfolios/', params)
    return data
  },
  update: async (id: number, params: { name?: string; account_types?: AccountType[]; calculation_base?: string; target_total_amount?: number | null; snapshot_enabled?: boolean }) => {
    const { data } = await api.put<Portfolio>(`/portfolios/${id}`, params)
    return data
  },
  delete: async (id: number) => {
    await api.delete(`/portfolios/${id}`)
  },
  duplicate: async (id: number) => {
    const { data } = await api.post<Portfolio>(`/portfolios/${id}/duplicate`)
    return data
  },
  // 편집 화면의 변경(이름·설정·목표 비중·보유 수량)을 한 번에 저장한다
  batchUpdate: async (id: number, params: {
    name?: string;
    account_types?: AccountType[];
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
  share: async (portfolioId: number) => {
    const { data } = await api.post<ShareCreateResponse>(`/portfolios/${portfolioId}/share`)
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
  delete: async (shareToken: string) => {
    await api.delete(`/shared/${shareToken}`)
  },
}
