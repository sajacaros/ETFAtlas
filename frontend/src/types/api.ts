export interface User {
  id: number
  email: string
  name: string | null
  picture: string | null
}

export interface ETF {
  code: string
  name: string
  issuer: string | null
  net_assets: number | null
  expense_ratio: number | null
}

export interface Holding {
  stock_code: string
  stock_name: string
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
  market_cap: number | null
}

export interface WatchlistItem {
  etf_code: string
  etf_name: string
  category: string | null
}

// Portfolio types
export type CalculationBase = 'CURRENT_TOTAL' | 'TARGET_AMOUNT'
export type AdjustmentStatus = 'BUY' | 'SELL' | 'HOLD'

export interface Portfolio {
  id: number
  name: string
  calculation_base: CalculationBase
  target_total_amount: number | null
  display_order: number
  current_value: number | null
  current_value_date: string | null
  daily_change_amount: number | null
  daily_change_rate: number | null
  invested_amount: number | null
  investment_return_rate: number | null
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
  avg_price: number | null
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
  avg_price: number | null
  profit_loss_rate: number | null
  profit_loss_amount: number | null
  price_change_rate: number | null
}

export interface CalculationResult {
  rows: CalculationRow[]
  base_amount: number
  total_weight: number
  total_holding_amount: number
  total_adjustment_amount: number
  total_profit_loss_amount: number | null
  weight_warning: string | null
}

// Tag types
export interface Tag {
  name: string
  etf_count: number
}

export interface TagETF {
  code: string
  name: string
  net_assets: number | null
  return_1d: number | null
  return_1w: number | null
  return_1m: number | null
  market_cap_change_1w: number | null
}

export interface TagHolding {
  stock_code: string
  stock_name: string
  weight: number
}

// Total Holdings types
export interface TotalHoldingItem {
  ticker: string
  name: string
  quantity: number
  current_price: number
  value: number
  weight: number
}

export interface TotalHoldingsResponse {
  holdings: TotalHoldingItem[]
  total_value: number
}

// Chat types
export interface ChatMessage {
  role: 'user' | 'assistant'
  content: string
}

export interface ToolCall {
  name: string
  arguments: string
}

export interface ChatStep {
  step_number: number
  code: string
  observations: string
  tool_calls: ToolCall[]
  error: string | null
}

export interface ChatResponse {
  answer: string
  steps: ChatStep[]
}

// Watchlist change types
export interface WatchlistChange {
  etf_code: string
  etf_name: string
  stock_code: string
  stock_name: string
  change_type: 'added' | 'removed' | 'increased' | 'decreased'
  current_weight: number
  previous_weight: number
  weight_change: number
}

// Similar ETF types
export interface SimilarETF {
  etf_code: string
  name: string
  overlap: number
  similarity: number
}

// Dashboard types
export interface DashboardSummaryItem {
  amount: number
  rate: number
}

export interface DashboardSummary {
  current_value: number
  cumulative: DashboardSummaryItem
  daily: DashboardSummaryItem | null
  monthly: DashboardSummaryItem | null
  yearly: DashboardSummaryItem | null
  ytd: DashboardSummaryItem | null
  invested_amount: number | null
  investment_return: DashboardSummaryItem | null
}

export interface ChartDataPoint {
  date: string
  total_value: number
  cumulative_rate: number
}

export interface DashboardResponse {
  summary: DashboardSummary
  chart_data: ChartDataPoint[]
}
