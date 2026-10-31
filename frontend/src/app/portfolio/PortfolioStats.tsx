import type { ReactNode } from 'react'
import { Card, CardContent } from '@/components/ui/card'
import { changeColor, formatRate, formatWon } from '@/lib/format'
import { formatMaskedNumber } from '@/hooks/useAmountVisibility'
import type { Portfolio } from '@/types/api'
import { formatSignedWon, portfolioProfit } from './format'

const MASK = '••••••'

// 전일대비: +12,345원 (+0.12%)
function DailyChange({ p }: { p: Portfolio }) {
  return (
    <>
      {formatSignedWon(p.daily_change_amount ?? 0)}
      <span className="font-normal text-xs ml-0.5">
        ({formatRate(p.daily_change_rate ?? 0)})
      </span>
    </>
  )
}

/** 목록 카드의 평가금액·투자원금·수익금·수익률·전일대비 (스냅샷이 꺼져 있거나 아직 값이 없으면 '-') */
export function PortfolioCardStats({ portfolio: p, amountVisible }: { portfolio: Portfolio; amountVisible: boolean }) {
  const hasData = p.snapshot_enabled && p.current_value != null && p.current_value_date
  const profit = portfolioProfit(p)
  return (
    <div className="space-y-2">
      {/* 평가금액 */}
      <div>
        <p className="text-xs text-muted-foreground">평가금액</p>
        <p className="text-xl font-bold font-mono">
          {hasData ? <>{formatMaskedNumber(p.current_value!, amountVisible)}{amountVisible && '원'}</> : '-'}
        </p>
      </div>

      {/* 투자원금 / 수익금 */}
      <div className="grid grid-cols-2 gap-2">
        <div>
          <p className="text-xs text-muted-foreground">투자원금</p>
          <p className="text-sm font-mono">
            {!hasData || p.invested_amount == null ? '-' : !amountVisible ? MASK : `${formatWon(p.invested_amount)}원`}
          </p>
        </div>
        <div>
          <p className="text-xs text-muted-foreground">수익금</p>
          {!hasData || profit == null ? (
            <p className="text-sm font-mono">-</p>
          ) : (
            <p className={`text-sm font-mono ${changeColor(profit)}`}>
              {amountVisible ? formatSignedWon(profit) : MASK}
            </p>
          )}
        </div>
      </div>

      {/* 수익률 / 전일대비 */}
      <div className="grid grid-cols-2 gap-2">
        <div>
          <p className="text-xs text-muted-foreground">수익률</p>
          <p className={`text-sm font-mono font-semibold ${hasData ? changeColor(p.investment_return_rate) : ''}`}>
            {!hasData || p.investment_return_rate == null ? '-' : amountVisible ? formatRate(p.investment_return_rate) : MASK}
          </p>
        </div>
        <div>
          <p className="text-xs text-muted-foreground">전일대비</p>
          <p className={`text-sm font-mono font-semibold ${hasData ? changeColor(p.daily_change_rate) : ''}`}>
            {!hasData ? '-' : amountVisible ? <DailyChange p={p} /> : MASK}
          </p>
        </div>
      </div>
    </div>
  )
}

/** 상세 화면 위의 한 줄 요약. children은 오른쪽 끝(예수금) */
export function PortfolioSummaryBar({ portfolio: p, children }: { portfolio: Portfolio; children: ReactNode }) {
  if (p.current_value == null) return null
  const profit = portfolioProfit(p)
  return (
    <Card>
      <CardContent className="py-3">
        <div className="flex flex-wrap items-center gap-6">
          <div className="flex items-center gap-1.5">
            <span className="text-sm text-muted-foreground">평가금액</span>
            <span className="text-lg font-bold font-mono">{formatWon(p.current_value)}원</span>
          </div>
          {p.invested_amount != null && (
            <div className="flex items-center gap-1.5">
              <span className="text-sm text-muted-foreground">투자원금</span>
              <span className="text-sm font-mono">{formatWon(p.invested_amount)}원</span>
            </div>
          )}
          {profit != null && (
            <div className="flex items-center gap-1.5">
              <span className="text-sm text-muted-foreground">수익금</span>
              <span className={`text-sm font-mono font-semibold ${changeColor(profit)}`}>
                {formatSignedWon(profit)}
              </span>
            </div>
          )}
          {p.investment_return_rate != null && (
            <div className="flex items-center gap-1.5">
              <span className="text-sm text-muted-foreground">수익률</span>
              <span className={`text-sm font-mono font-semibold ${changeColor(p.investment_return_rate)}`}>
                {formatRate(p.investment_return_rate)}
              </span>
            </div>
          )}
          {p.daily_change_amount != null && (
            <div className="flex items-center gap-1.5">
              <span className="text-sm text-muted-foreground">전일대비</span>
              <span className={`text-sm font-mono font-semibold ${changeColor(p.daily_change_rate)}`}>
                <DailyChange p={p} />
              </span>
            </div>
          )}
          <div className="flex items-center gap-1.5 ml-auto">
            <span className="text-sm text-muted-foreground">예수금</span>
            {children}
          </div>
        </div>
      </CardContent>
    </Card>
  )
}
