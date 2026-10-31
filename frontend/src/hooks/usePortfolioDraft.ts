import { useCallback, useMemo, useReducer } from 'react'
import type {
  AccountType,
  CalculationBase,
  CalculationResult,
  CalculationRow,
  HoldingItem,
  PortfolioDetail,
  TargetAllocationItem,
} from '@/types/api'
import { DEFAULT_ACCOUNT_TYPES } from '@/lib/accountType'
import { formatWon } from '@/lib/format'

// 편집 중에 새로 넣은 종목 (저장 전이라 서버 id가 없다)
export interface AddedTicker {
  ticker: string
  name: string
  targetWeight: number
  quantity: number
  avgPrice?: number
}

interface DraftState {
  isEditing: boolean
  // 이름·목표 금액·예수금 입력값 (예수금은 보기 화면에도 그대로 보여 준다)
  name: string
  amount: string
  cash: string
  calcBase: CalculationBase
  accountTypes: AccountType[]
  added: AddedTicker[]
  deleted: string[]
  // 표에서 고친 값 (종목 코드 → 값). 저장할 때 원래 값 대신 쓴다
  weights: Record<string, number>
  quantities: Record<string, number>
  avgPrices: Record<string, number>
}

type DraftAction =
  | { type: 'sync'; detail: PortfolioDetail }
  | { type: 'begin'; detail: PortfolioDetail }
  | { type: 'end' }
  | { type: 'setName'; value: string }
  | { type: 'setCash'; value: string }
  | { type: 'setAccountTypes'; value: AccountType[] }
  | { type: 'add'; ticker: AddedTicker }
  | { type: 'setWeight'; ticker: string; value: number }
  | { type: 'setQuantity'; ticker: string; value: number }
  | { type: 'setAvgPrice'; ticker: string; value: number }
  | { type: 'delete'; ticker: string }

const EMPTY_CHANGES = { added: [], deleted: [], weights: {}, quantities: {}, avgPrices: {} }

const initialState: DraftState = {
  isEditing: false,
  name: '',
  amount: '',
  cash: '',
  calcBase: 'CURRENT_TOTAL',
  accountTypes: DEFAULT_ACCOUNT_TYPES,
  ...EMPTY_CHANGES,
}

function omit(record: Record<string, number>, key: string) {
  if (!(key in record)) return record
  const { [key]: _removed, ...rest } = record
  return rest
}

function reducer(state: DraftState, action: DraftAction): DraftState {
  switch (action.type) {
    // 서버에서 상세를 새로 받으면 이름·목표 금액·예수금 입력값을 맞춘다
    case 'sync': {
      const d = action.detail
      const cashHolding = d.holdings.find((h) => h.ticker === 'CASH')
      const cashQty = cashHolding ? Math.round(Number(cashHolding.quantity)) : 0
      return {
        ...state,
        name: d.name,
        amount: d.target_total_amount ? String(d.target_total_amount) : '',
        cash: cashQty > 0 ? formatWon(cashQty) : '',
      }
    }
    case 'begin':
      return {
        ...state,
        ...EMPTY_CHANGES,
        isEditing: true,
        calcBase: action.detail.calculation_base,
        accountTypes: action.detail.account_types,
      }
    case 'end':
      return { ...state, ...EMPTY_CHANGES, isEditing: false }
    case 'setName':
      return { ...state, name: action.value }
    case 'setCash':
      return { ...state, cash: action.value }
    case 'setAccountTypes':
      return { ...state, accountTypes: action.value }
    case 'add':
      return { ...state, added: [...state.added, action.ticker] }
    case 'setWeight':
      return { ...state, weights: { ...state.weights, [action.ticker]: action.value } }
    case 'setQuantity':
      return { ...state, quantities: { ...state.quantities, [action.ticker]: action.value } }
    case 'setAvgPrice':
      return { ...state, avgPrices: { ...state.avgPrices, [action.ticker]: action.value } }
    case 'delete': {
      // 편집 중에 새로 넣은 종목이면 넣은 것만 취소한다
      const isAdded = state.added.some((a) => a.ticker === action.ticker)
      return {
        ...state,
        added: isAdded ? state.added.filter((a) => a.ticker !== action.ticker) : state.added,
        deleted: isAdded ? state.deleted : [...state.deleted, action.ticker],
        weights: omit(state.weights, action.ticker),
        quantities: omit(state.quantities, action.ticker),
        avgPrices: omit(state.avgPrices, action.ticker),
      }
    }
  }
}

/**
 * 포트폴리오 편집 초안 — 편집 완료를 누를 때까지 서버에 보내지 않고 모아 두었다가 batchUpdate 한 번으로 저장한다.
 * displayed*는 편집 중이면 추가·삭제를 반영한 표 데이터, 아니면 서버 값 그대로다
 */
export function usePortfolioDraft(detail: PortfolioDetail | null, calcResult: CalculationResult | null) {
  const [state, dispatch] = useReducer(reducer, initialState)
  const { isEditing, added, deleted } = state

  const deletedSet = useMemo(() => new Set(deleted), [deleted])

  const displayedRows = useMemo(() => {
    if (!calcResult) return []
    if (!isEditing) return calcResult.rows
    const rows = calcResult.rows.filter(r => !deletedSet.has(r.ticker))
    const addedRows: CalculationRow[] = added.map(a => ({
      ticker: a.ticker,
      name: a.name,
      target_weight: a.targetWeight,
      current_price: 0,
      target_amount: 0,
      target_quantity: 0,
      holding_quantity: a.quantity,
      holding_amount: 0,
      required_quantity: 0,
      adjustment_amount: 0,
      status: 'HOLD' as const,
      avg_price: a.avgPrice ?? null,
      profit_loss_rate: null,
      profit_loss_amount: null,
      price_change_rate: null,
    }))
    return [...rows, ...addedRows]
  }, [isEditing, calcResult, deletedSet, added])

  const displayedTargetAllocations = useMemo((): TargetAllocationItem[] => {
    if (!detail) return []
    if (!isEditing) return detail.target_allocations
    const existing = detail.target_allocations.filter(t => !deletedSet.has(t.ticker))
    const addedTargets = added.map((a, i) => ({
      id: -(i + 1),
      portfolio_id: detail.id,
      ticker: a.ticker,
      target_weight: a.targetWeight,
    }))
    return [...existing, ...addedTargets]
  }, [isEditing, detail, deletedSet, added])

  const displayedHoldings = useMemo((): HoldingItem[] => {
    if (!detail) return []
    if (!isEditing) return detail.holdings
    const existing = detail.holdings.filter(h => !deletedSet.has(h.ticker))
    const addedHoldings = added
      .filter(a => a.quantity > 0 || a.avgPrice)
      .map((a, i) => ({
        id: -(i + 1),
        portfolio_id: detail.id,
        ticker: a.ticker,
        quantity: a.quantity,
        avg_price: a.avgPrice ?? null,
      }))
    return [...existing, ...addedHoldings]
  }, [isEditing, detail, deletedSet, added])

  // batchUpdate에 보낼 내용 — 삭제한 종목은 빼고, 고친 값이 있으면 그 값으로
  const buildBatchPayload = useCallback((d: PortfolioDetail) => {
    const { weights, quantities, avgPrices } = state
    const targets = [
      ...d.target_allocations
        .filter(t => !deletedSet.has(t.ticker))
        .map(t => ({
          ticker: t.ticker,
          target_weight: weights[t.ticker] ?? t.target_weight,
        })),
      ...added.map(a => ({
        ticker: a.ticker,
        target_weight: weights[a.ticker] ?? a.targetWeight,
      })),
    ]

    const cashAmount = parseInt(state.cash.replace(/,/g, '') || '0', 10)
    const holdings = [
      ...d.holdings
        .filter(h => !deletedSet.has(h.ticker) && h.ticker !== 'CASH')
        .map(h => ({
          ticker: h.ticker,
          quantity: quantities[h.ticker] ?? h.quantity,
          avg_price: avgPrices[h.ticker] ?? h.avg_price,
        })),
      ...added
        .filter(a => a.ticker !== 'CASH')
        .map(a => ({
          ticker: a.ticker,
          quantity: quantities[a.ticker] ?? a.quantity,
          avg_price: avgPrices[a.ticker] ?? a.avgPrice ?? null,
        })),
      ...(cashAmount > 0 ? [{ ticker: 'CASH', quantity: cashAmount, avg_price: null as number | null }] : []),
    ]

    return {
      name: state.name,
      account_types: state.accountTypes,
      calculation_base: state.calcBase,
      target_total_amount: state.amount ? parseFloat(state.amount) : null,
      targets,
      holdings,
    }
  }, [state, deletedSet, added])

  const actions = useMemo(() => ({
    sync: (d: PortfolioDetail) => dispatch({ type: 'sync', detail: d }),
    begin: (d: PortfolioDetail) => dispatch({ type: 'begin', detail: d }),
    end: () => dispatch({ type: 'end' }),
    setName: (value: string) => dispatch({ type: 'setName', value }),
    setCash: (value: string) => dispatch({ type: 'setCash', value }),
    setAccountTypes: (value: AccountType[]) => dispatch({ type: 'setAccountTypes', value }),
    addTicker: (ticker: AddedTicker) => dispatch({ type: 'add', ticker }),
    setWeight: (ticker: string, value: number) => dispatch({ type: 'setWeight', ticker, value }),
    setQuantity: (ticker: string, value: number) => dispatch({ type: 'setQuantity', ticker, value }),
    setAvgPrice: (ticker: string, value: number) => dispatch({ type: 'setAvgPrice', ticker, value }),
    deleteTicker: (ticker: string) => dispatch({ type: 'delete', ticker }),
  }), [])

  return {
    ...state,
    ...actions,
    displayedRows,
    displayedTargetAllocations,
    displayedHoldings,
    buildBatchPayload,
  }
}
