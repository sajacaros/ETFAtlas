import { useMemo, useState } from 'react'
import {
  Table,
  TableBody,
  TableCell,
  TableFooter,
  TableHead,
  TableHeader,
  TableRow,
} from '@/components/ui/table'
import { Badge } from '@/components/ui/badge'
import { Input } from '@/components/ui/input'
import { Button } from '@/components/ui/button'
import { Trash2, ArrowUp, ArrowDown } from 'lucide-react'
import type { CalculationRow, TargetAllocationItem, HoldingItem } from '@/types/api'

interface PortfolioTableProps {
  rows: CalculationRow[]
  totalWeight: number
  totalHoldingAmount: number
  totalAdjustmentAmount: number
  targetAllocations: TargetAllocationItem[]
  holdings: HoldingItem[]
  isEditing: boolean
  onUpdateWeight: (targetId: number, weight: number) => void
  onUpdateQuantity: (ticker: string, quantity: number, holdingId?: number) => void
  onDeleteTicker: (ticker: string, targetId?: number, holdingId?: number) => void
}

function formatNumber(n: number): string {
  return new Intl.NumberFormat('ko-KR').format(Math.round(n))
}

type SortKey =
  | 'name'
  | 'target_weight'
  | 'current_weight'
  | 'current_price'
  | 'target_amount'
  | 'target_quantity'
  | 'holding_quantity'
  | 'holding_amount'
  | 'required_quantity'
  | 'adjustment_amount'
  | 'status'

type SortDir = 'asc' | 'desc'

const STATUS_ORDER: Record<string, number> = { BUY: 0, SELL: 1, HOLD: 2 }

export default function PortfolioTable({
  rows,
  totalWeight,
  totalHoldingAmount,
  totalAdjustmentAmount,
  targetAllocations,
  holdings,
  isEditing,
  onUpdateWeight,
  onUpdateQuantity,
  onDeleteTicker,
}: PortfolioTableProps) {
  const [editingWeight, setEditingWeight] = useState<Record<string, string>>({})
  const [editingQty, setEditingQty] = useState<Record<string, string>>({})
  const [sortKey, setSortKey] = useState<SortKey | null>(null)
  const [sortDir, setSortDir] = useState<SortDir>('asc')

  const targetMap = new Map(targetAllocations.map((t) => [t.ticker, t]))
  const holdingMap = new Map(holdings.map((h) => [h.ticker, h]))

  const handleSort = (key: SortKey) => {
    if (sortKey === key) {
      if (sortDir === 'asc') {
        setSortDir('desc')
      } else {
        setSortKey(null)
        setSortDir('asc')
      }
    } else {
      setSortKey(key)
      setSortDir('asc')
    }
  }

  const sortedRows = useMemo(() => {
    if (!sortKey) return rows
    return [...rows].sort((a, b) => {
      let cmp = 0
      if (sortKey === 'name') {
        cmp = a.name.localeCompare(b.name, 'ko')
      } else if (sortKey === 'current_weight') {
        const aw = totalHoldingAmount > 0 ? Number(a.holding_amount) / totalHoldingAmount : 0
        const bw = totalHoldingAmount > 0 ? Number(b.holding_amount) / totalHoldingAmount : 0
        cmp = aw - bw
      } else if (sortKey === 'status') {
        cmp = (STATUS_ORDER[a.status] ?? 3) - (STATUS_ORDER[b.status] ?? 3)
      } else {
        cmp = Number(a[sortKey]) - Number(b[sortKey])
      }
      return sortDir === 'asc' ? cmp : -cmp
    })
  }, [rows, sortKey, sortDir, totalHoldingAmount])

  const SortableHead = ({
    label,
    sortField,
    className,
  }: {
    label: string
    sortField: SortKey
    className?: string
  }) => (
    <TableHead
      className={`${className ?? ''} cursor-pointer select-none hover:bg-muted/50`}
      onClick={() => handleSort(sortField)}
    >
      <span className="inline-flex items-center gap-1">
        {label}
        {sortKey === sortField &&
          (sortDir === 'asc' ? (
            <ArrowUp className="w-3 h-3" />
          ) : (
            <ArrowDown className="w-3 h-3" />
          ))}
      </span>
    </TableHead>
  )

  const handleWeightBlur = (ticker: string) => {
    const val = editingWeight[ticker]
    if (val === undefined) return
    const target = targetMap.get(ticker)
    if (target) {
      onUpdateWeight(target.id, parseFloat(val))
    }
    setEditingWeight((prev) => {
      const next = { ...prev }
      delete next[ticker]
      return next
    })
  }

  const handleQtyBlur = (ticker: string) => {
    const val = editingQty[ticker]
    if (val === undefined) return
    const holding = holdingMap.get(ticker)
    const qty = parseInt(val, 10)
    if (!isNaN(qty)) {
      onUpdateQuantity(ticker, qty, holding?.id)
    }
    setEditingQty((prev) => {
      const next = { ...prev }
      delete next[ticker]
      return next
    })
  }

  const handleKeyDown = (e: React.KeyboardEvent, onBlur: () => void) => {
    if (e.key === 'Enter') {
      onBlur()
      ;(e.target as HTMLInputElement).blur()
    }
  }

  const weightIsWarning = Math.abs(totalWeight - 100) > 0.001

  return (
    <Table>
      <TableHeader>
        <TableRow>
          <TableHead className="w-[80px]">종목코드</TableHead>
          <SortableHead label="종목명" sortField="name" />
          <SortableHead label="목표 비중(%)" sortField="target_weight" className="text-right w-[90px]" />
          <SortableHead label="현재 비중(%)" sortField="current_weight" className="text-right w-[70px]" />
          <SortableHead label="현재가" sortField="current_price" className="text-right" />
          <SortableHead label="목표 금액" sortField="target_amount" className="text-right" />
          <SortableHead label="목표 수량" sortField="target_quantity" className="text-right" />
          <SortableHead label="보유 수량" sortField="holding_quantity" className="text-right w-[100px]" />
          <SortableHead label="평가 금액" sortField="holding_amount" className="text-right" />
          <SortableHead label="필요 수량" sortField="required_quantity" className="text-right" />
          <SortableHead label="가감 금액" sortField="adjustment_amount" className="text-right" />
          <SortableHead label="상태" sortField="status" className="text-center w-[80px]" />
          {isEditing && <TableHead className="w-[40px]"></TableHead>}
        </TableRow>
      </TableHeader>
      <TableBody>
        {rows.length === 0 ? (
          <TableRow>
            <TableCell colSpan={isEditing ? 13 : 12} className="text-center text-muted-foreground py-8">
              종목을 추가해주세요
            </TableCell>
          </TableRow>
        ) : (
          sortedRows.map((row) => {
            const target = targetMap.get(row.ticker)
            const holding = holdingMap.get(row.ticker)

            return (
              <TableRow key={row.ticker}>
                <TableCell className="font-mono text-xs">{row.ticker}</TableCell>
                <TableCell className="text-sm">{row.name}</TableCell>
                <TableCell className="text-right">
                  {target ? (
                    isEditing ? (
                      <Input
                        type="number"
                        step="0.1"
                        min="0"
                        max="100"
                        className="w-20 text-right h-8 ml-auto"
                        value={editingWeight[row.ticker] ?? Number(row.target_weight).toFixed(1)}
                        onChange={(e) =>
                          setEditingWeight((prev) => ({ ...prev, [row.ticker]: e.target.value }))
                        }
                        onBlur={() => handleWeightBlur(row.ticker)}
                        onKeyDown={(e) => handleKeyDown(e, () => handleWeightBlur(row.ticker))}
                      />
                    ) : (
                      <span className="font-mono text-sm">{Number(row.target_weight).toFixed(1)}</span>
                    )
                  ) : (
                    <span className="text-muted-foreground">-</span>
                  )}
                </TableCell>
                <TableCell className="text-right font-mono text-sm text-muted-foreground">
                  {totalHoldingAmount > 0
                    ? (row.holding_amount / totalHoldingAmount * 100).toFixed(1)
                    : '-'}
                </TableCell>
                <TableCell className="text-right font-mono">{formatNumber(row.current_price)}</TableCell>
                <TableCell className="text-right font-mono">{formatNumber(row.target_amount)}</TableCell>
                <TableCell className="text-right font-mono">{formatNumber(row.target_quantity)}</TableCell>
                <TableCell className="text-right">
                  {isEditing ? (
                    <Input
                      type="number"
                      step="1"
                      min="0"
                      className="w-24 text-right h-8 ml-auto"
                      value={editingQty[row.ticker] ?? String(Math.round(Number(row.holding_quantity)))}
                      onChange={(e) =>
                        setEditingQty((prev) => ({ ...prev, [row.ticker]: e.target.value }))
                      }
                      onBlur={() => handleQtyBlur(row.ticker)}
                      onKeyDown={(e) => handleKeyDown(e, () => handleQtyBlur(row.ticker))}
                    />
                  ) : (
                    <span className="font-mono text-sm">{formatNumber(Math.round(Number(row.holding_quantity)))}</span>
                  )}
                </TableCell>
                <TableCell className="text-right font-mono">{formatNumber(row.holding_amount)}</TableCell>
                <TableCell
                  className={`text-right font-mono ${
                    row.required_quantity > 0
                      ? 'text-green-600'
                      : row.required_quantity < 0
                        ? 'text-red-600'
                        : ''
                  }`}
                >
                  {row.required_quantity > 0 ? '+' : ''}
                  {formatNumber(row.required_quantity)}
                </TableCell>
                <TableCell
                  className={`text-right font-mono ${
                    row.adjustment_amount > 0
                      ? 'text-green-600'
                      : row.adjustment_amount < 0
                        ? 'text-red-600'
                        : ''
                  }`}
                >
                  {row.adjustment_amount > 0 ? '+' : ''}
                  {formatNumber(row.adjustment_amount)}
                </TableCell>
                <TableCell className="text-center">
                  <Badge
                    className={`whitespace-nowrap ${
                      row.status === 'BUY'
                        ? 'bg-green-100 text-green-700 hover:bg-green-100'
                        : row.status === 'SELL'
                          ? 'bg-red-100 text-red-700 hover:bg-red-100'
                          : 'bg-gray-100 text-gray-600 hover:bg-gray-100'
                    }`}
                  >
                    {row.status === 'BUY' ? '매수' : row.status === 'SELL' ? '매도' : '유지'}
                  </Badge>
                </TableCell>
                {isEditing && (
                  <TableCell>
                    <Button
                      variant="ghost"
                      size="sm"
                      className="h-8 w-8 p-0 text-muted-foreground hover:text-destructive"
                      onClick={() => onDeleteTicker(row.ticker, target?.id, holding?.id)}
                    >
                      <Trash2 className="w-3.5 h-3.5" />
                    </Button>
                  </TableCell>
                )}
              </TableRow>
            )
          })
        )}
      </TableBody>
      {rows.length > 0 && (
        <TableFooter>
          <TableRow>
            <TableCell colSpan={2} className="font-semibold">
              합계
            </TableCell>
            <TableCell className={`text-right font-semibold ${weightIsWarning ? 'text-red-600' : ''}`}>
              {Number(totalWeight).toFixed(1)}%
            </TableCell>
            <TableCell className="text-right font-semibold text-muted-foreground">
              {totalHoldingAmount > 0 ? '100.0' : '-'}
            </TableCell>
            <TableCell />
            <TableCell />
            <TableCell />
            <TableCell />
            <TableCell className="text-right font-mono font-semibold">
              {formatNumber(totalHoldingAmount)}
            </TableCell>
            <TableCell />
            <TableCell
              className={`text-right font-mono font-semibold ${
                totalAdjustmentAmount > 0
                  ? 'text-green-600'
                  : totalAdjustmentAmount < 0
                    ? 'text-red-600'
                    : ''
              }`}
            >
              {totalAdjustmentAmount > 0 ? '+' : ''}
              {formatNumber(totalAdjustmentAmount)}
            </TableCell>
            <TableCell />
            {isEditing && <TableCell />}
          </TableRow>
        </TableFooter>
      )}
    </Table>
  )
}
