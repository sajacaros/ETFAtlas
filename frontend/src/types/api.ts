export interface User {
  id: number
  email: string
  name: string | null
  picture: string | null
}

export interface ETF {
  id: number
  code: string
  name: string
  issuer: string | null
  category: string | null
  net_assets: number | null
  expense_ratio: number | null
  inception_date: string | null
}

export interface Stock {
  code: string
  name: string
  sector: string | null
}

export interface Holding {
  stock_code: string
  stock_name: string
  sector: string | null
  weight: number
  shares: number | null
  recorded_at: string
}

export interface HoldingChange {
  stock_code: string
  stock_name: string
  change_type: 'added' | 'removed' | 'increased' | 'decreased'
  current_weight: number
  previous_weight: number
  weight_change: number
}

export interface Price {
  date: string
  open: number | null
  high: number | null
  low: number | null
  close: number | null
  volume: number | null
}

export interface ETFByStock {
  etf_code: string
  etf_name: string
  issuer: string | null
  category: string | null
  weight: number
}

export interface Watchlist {
  id: number
  name: string
  items: WatchlistItem[]
}

export interface WatchlistItem {
  id: number
  etf_code: string
  etf_name: string
  category: string | null
}

export interface Signal {
  etf_code: string
  etf_name: string
  signal_type: 'buy' | 'sell' | 'hold'
  confidence: number
  reason: string
}

export interface Insight {
  title: string
  content: string
  etfs: string[]
}

export interface RecommendationResponse {
  signals: Signal[]
  insights: Insight[]
  summary: string
}

// Portfolio types
export type CalculationBase = 'CURRENT_TOTAL' | 'TARGET_AMOUNT'
export type AdjustmentStatus = 'BUY' | 'SELL' | 'HOLD'

export interface Portfolio {
  id: number
  name: string
  calculation_base: CalculationBase
  target_total_amount: number | null
}

export interface TargetAllocationItem {
  id: number
  portfolio_id: number
  ticker: string
  target_weight: number
}

export interface HoldingItem {
  id: number
  portfolio_id: number
  ticker: string
  quantity: number
}

export interface PortfolioDetail {
  id: number
  name: string
  calculation_base: CalculationBase
  target_total_amount: number | null
  target_allocations: TargetAllocationItem[]
  holdings: HoldingItem[]
}

export interface CalculationRow {
  ticker: string
  name: string
  target_weight: number
  current_price: number
  target_amount: number
  target_quantity: number
  holding_quantity: number
  holding_amount: number
  required_quantity: number
  adjustment_amount: number
  status: AdjustmentStatus
}

export interface CalculationResult {
  rows: CalculationRow[]
  base_amount: number
  total_weight: number
  total_holding_amount: number
  total_adjustment_amount: number
  weight_warning: string | null
}
