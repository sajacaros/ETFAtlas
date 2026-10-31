import { Eye, EyeOff } from 'lucide-react'
import { Card, CardContent } from '@/components/ui/card'
import { changeColor, formatRate } from '@/lib/format'
import { formatMaskedNumber } from '@/hooks/useAmountVisibility'
import type { DashboardSummary } from '@/types/api'
import { formatShortDateTime, formatSignedWon } from './format'

/** 목록 위의 전체 포트폴리오 합계 (총 평가금액·전일대비·YTD) */
export default function TotalSummaryCard({
  summary,
  amountVisible,
  onToggleAmount,
}: {
  summary: DashboardSummary
  amountVisible: boolean
  onToggleAmount: () => void
}) {
  return (
    <Card>
      <CardContent className="py-4">
        {summary.snapshot_date && (
          <p className="text-xs text-muted-foreground mb-2">
            {summary.updated_at && `기준: ${formatShortDateTime(summary.updated_at)}`}
          </p>
        )}
        <div className="flex flex-wrap items-center gap-6">
          <div>
            <div className="flex items-center gap-1">
              <p className="text-sm text-muted-foreground">
                총 평가금액
              </p>
              <button
                onClick={onToggleAmount}
                className="text-muted-foreground hover:text-foreground transition-colors p-0.5"
                aria-label={amountVisible ? '금액 숨기기' : '금액 보기'}
              >
                {amountVisible ? <Eye className="w-4 h-4" /> : <EyeOff className="w-4 h-4" />}
              </button>
            </div>
            <p className="text-2xl font-bold font-mono">
              {formatMaskedNumber(summary.current_value, amountVisible)}{amountVisible && '원'}
            </p>
          </div>
          {summary.daily && (
            <div>
              <p className="text-sm text-muted-foreground">전일대비</p>
              <p className={`text-lg font-mono font-semibold ${changeColor(summary.daily.amount)}`}>
                {amountVisible ? (
                  <>
                    {formatSignedWon(summary.daily.amount)}
                    <span className="text-sm ml-1">
                      ({formatRate(summary.daily.rate)})
                    </span>
                  </>
                ) : (
                  '••••••'
                )}
              </p>
            </div>
          )}
          {summary.ytd && (
            <div>
              <p className="text-sm text-muted-foreground">YTD</p>
              <p className={`text-lg font-mono font-semibold ${changeColor(summary.ytd.amount)}`}>
                {formatRate(summary.ytd.rate)}
              </p>
            </div>
          )}
        </div>
      </CardContent>
    </Card>
  )
}
