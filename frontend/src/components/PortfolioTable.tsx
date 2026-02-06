import { useState } from 'react'
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
import { Trash2 } from 'lucide-react'
import type { CalculationRow, TargetAllocationItem, HoldingItem } from '@/types/api'

interface PortfolioTableProps {
  rows: CalculationRow[]
  totalWeight: number
  totalHoldingAmount: number
  totalAdjustmentAmount: number
  targetAllocations: TargetAllocationItem[]
  holdings: HoldingItem[]
  onUpdateWeight: (targetId: number, weight: number) => void
  onUpdateQuantity: (holdingId: number, quantity: number) => void
  onDeleteTicker: (ticker: string, targetId?: number, holdingId?: number) => void
}

function formatNumber(n: number): string {
  return new Intl.NumberFormat('ko-KR').format(Math.round(n))
}

export default function PortfolioTable({
  rows,
  totalWeight,
  totalHoldingAmount,
  totalAdjustmentAmount,
  targetAllocations,
  holdings,
  onUpdateWeight,
  onUpdateQuantity,
  onDeleteTicker,
}: PortfolioTableProps) {
  const [editingWeight, setEditingWeight] = useState<Record<string, string>>({})
  const [editingQty, setEditingQty] = useState<Record<string, string>>({})

  const targetMap = new Map(targetAllocations.map((t) => [t.ticker, t]))
  const holdingMap = new Map(holdings.map((h) => [h.ticker, h]))

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
    if (holding) {
      onUpdateQuantity(holding.id, parseFloat(val))
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
          <TableHead>종목명</TableHead>
          <TableHead className="text-right w-[90px]">목표 비중(%)</TableHead>
          <TableHead className="text-right">현재가</TableHead>
          <TableHead className="text-right">목표 금액</TableHead>
          <TableHead className="text-right">목표 수량</TableHead>
          <TableHead className="text-right w-[100px]">보유 수량</TableHead>
          <TableHead className="text-right">평가 금액</TableHead>
          <TableHead className="text-right">필요 수량</TableHead>
          <TableHead className="text-right">가감 금액</TableHead>
          <TableHead className="text-center w-[70px]">상태</TableHead>
          <TableHead className="w-[40px]"></TableHead>
        </TableRow>
      </TableHeader>
      <TableBody>
        {rows.length === 0 ? (
          <TableRow>
            <TableCell colSpan={12} className="text-center text-muted-foreground py-8">
              종목을 추가해주세요
            </TableCell>
          </TableRow>
        ) : (
          rows.map((row) => {
            const target = targetMap.get(row.ticker)
            const holding = holdingMap.get(row.ticker)

            return (
              <TableRow key={row.ticker}>
                <TableCell className="font-mono text-xs">{row.ticker}</TableCell>
                <TableCell className="text-sm">{row.name}</TableCell>
                <TableCell className="text-right">
                  {target ? (
                    <Input
                      type="number"
                      step="0.01"
                      min="0"
                      max="100"
                      className="w-20 text-right h-8 ml-auto"
                      value={editingWeight[row.ticker] ?? String(row.target_weight)}
                      onChange={(e) =>
                        setEditingWeight((prev) => ({ ...prev, [row.ticker]: e.target.value }))
                      }
                      onBlur={() => handleWeightBlur(row.ticker)}
                      onKeyDown={(e) => handleKeyDown(e, () => handleWeightBlur(row.ticker))}
                    />
                  ) : (
                    <span className="text-muted-foreground">-</span>
                  )}
                </TableCell>
                <TableCell className="text-right font-mono">{formatNumber(row.current_price)}</TableCell>
                <TableCell className="text-right font-mono">{formatNumber(row.target_amount)}</TableCell>
                <TableCell className="text-right font-mono">{formatNumber(row.target_quantity)}</TableCell>
                <TableCell className="text-right">
                  {holding ? (
                    <Input
                      type="number"
                      step="1"
                      min="0"
                      className="w-24 text-right h-8 ml-auto"
                      value={editingQty[row.ticker] ?? String(row.holding_quantity)}
                      onChange={(e) =>
                        setEditingQty((prev) => ({ ...prev, [row.ticker]: e.target.value }))
                      }
                      onBlur={() => handleQtyBlur(row.ticker)}
                      onKeyDown={(e) => handleKeyDown(e, () => handleQtyBlur(row.ticker))}
                    />
                  ) : (
                    <span className="text-muted-foreground font-mono">0</span>
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
                    className={
                      row.status === 'BUY'
                        ? 'bg-green-100 text-green-700 hover:bg-green-100'
                        : row.status === 'SELL'
                          ? 'bg-red-100 text-red-700 hover:bg-red-100'
                          : 'bg-gray-100 text-gray-600 hover:bg-gray-100'
                    }
                  >
                    {row.status === 'BUY' ? '매수' : row.status === 'SELL' ? '매도' : '유지'}
                  </Badge>
                </TableCell>
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
              {totalWeight.toFixed(2)}%
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
            <TableCell />
          </TableRow>
        </TableFooter>
      )}
    </Table>
  )
}
