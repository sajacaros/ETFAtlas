import { useEffect, useState } from 'react'
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog'
import { Button } from '@/components/ui/button'
import { portfolioApi } from '@/lib/api'
import type { RiskAnalysisResponse } from '@/types/api'
import {
  ResponsiveContainer,
  LineChart,
  AreaChart,
  Area,
  Line,
  XAxis,
  YAxis,
  Tooltip,
  CartesianGrid,
} from 'recharts'

const PERIODS = [
  { key: '1m', label: '1M' },
  { key: '3m', label: '3M' },
  { key: '6m', label: '6M' },
  { key: '1y', label: '1Y' },
] as const

function MetricCard({ label, value, suffix = '%', colorBySign = false }: {
  label: string
  value: number | null
  suffix?: string
  colorBySign?: boolean
}) {
  if (value === null) return (
    <div className="rounded-lg border p-3 text-center">
      <p className="text-xs text-muted-foreground mb-1">{label}</p>
      <p className="text-lg font-semibold text-muted-foreground">-</p>
    </div>
  )
  let colorClass = ''
  if (colorBySign) {
    colorClass = value >= 0 ? 'text-red-500' : 'text-blue-500'
  }
  const sign = colorBySign && value >= 0 ? '+' : ''
  return (
    <div className="rounded-lg border p-3 text-center">
      <p className="text-xs text-muted-foreground mb-1">{label}</p>
      <p className={`text-lg font-semibold ${colorClass}`}>
        {sign}{value.toFixed(2)}{suffix}
      </p>
    </div>
  )
}

export default function RiskAnalysisDialog({
  open,
  onOpenChange,
  portfolioId,
}: {
  open: boolean
  onOpenChange: (open: boolean) => void
  portfolioId: number
}) {
  const [data, setData] = useState<RiskAnalysisResponse | null>(null)
  const [period, setPeriod] = useState('3m')
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    if (!open) return
    setLoading(true)
    setError(null)
    portfolioApi.getRiskAnalysis(portfolioId, period)
      .then(setData)
      .catch(() => setError('리스크 데이터를 불러올 수 없습니다'))
      .finally(() => setLoading(false))
  }, [open, portfolioId, period])

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="max-w-2xl max-h-[85vh] overflow-y-auto">
        <DialogHeader>
          <DialogTitle>포트폴리오 성과 분석</DialogTitle>
          <p className="text-sm text-muted-foreground">현재 구성 기준 가상 시뮬레이션</p>
        </DialogHeader>

        {/* Period selector */}
        <div className="flex gap-1">
          {PERIODS.map((p) => (
            <Button
              key={p.key}
              variant={period === p.key ? 'default' : 'outline'}
              size="sm"
              onClick={() => setPeriod(p.key)}
            >
              {p.label}
            </Button>
          ))}
        </div>

        {loading && <p className="text-center py-8 text-muted-foreground">로딩 중...</p>}
        {error && <p className="text-center py-8 text-muted-foreground">{error}</p>}

        {data && !loading && (
          <div className="space-y-4">
            {/* Metrics grid */}
            <div className="grid grid-cols-2 gap-3">
              <MetricCard label="수익률" value={data.total_return} colorBySign />
              <MetricCard label="MDD" value={data.mdd} />
              <MetricCard label="변동성 (연환산)" value={data.volatility} />
              <MetricCard label="샤프비율" value={data.sharpe_ratio} suffix="" />
            </div>

            {/* Returns chart */}
            <div>
              <p className="text-sm font-medium mb-2">가상 수익률 추이</p>
              <div className="h-52">
                <ResponsiveContainer width="100%" height="100%">
                  <LineChart data={data.chart_data}>
                    <CartesianGrid strokeDasharray="3 3" />
                    <XAxis
                      dataKey="date"
                      tickFormatter={(v: string) => v.slice(5)}
                      tick={{ fontSize: 11 }}
                    />
                    <YAxis
                      tickFormatter={(v: number) => `${v.toFixed(1)}%`}
                      tick={{ fontSize: 11 }}
                    />
                    <Tooltip
                      formatter={(v: number) => [`${v.toFixed(2)}%`, '수익률']}
                      labelFormatter={(l: string) => l}
                    />
                    <Line
                      type="monotone"
                      dataKey="return_rate"
                      stroke="#6366f1"
                      strokeWidth={2}
                      dot={false}
                    />
                  </LineChart>
                </ResponsiveContainer>
              </div>
            </div>

            {/* Drawdown chart */}
            <div>
              <p className="text-sm font-medium mb-2">Drawdown</p>
              <div className="h-40">
                <ResponsiveContainer width="100%" height="100%">
                  <AreaChart data={data.drawdown_data}>
                    <CartesianGrid strokeDasharray="3 3" />
                    <XAxis
                      dataKey="date"
                      tickFormatter={(v: string) => v.slice(5)}
                      tick={{ fontSize: 11 }}
                    />
                    <YAxis
                      tickFormatter={(v: number) => `${v.toFixed(1)}%`}
                      tick={{ fontSize: 11 }}
                    />
                    <Tooltip
                      formatter={(v: number) => [`${v.toFixed(2)}%`, 'Drawdown']}
                      labelFormatter={(l: string) => l}
                    />
                    <Area
                      type="monotone"
                      dataKey="drawdown"
                      stroke="#ef4444"
                      fill="#ef444420"
                      strokeWidth={1.5}
                    />
                  </AreaChart>
                </ResponsiveContainer>
              </div>
            </div>

            <p className="text-xs text-muted-foreground text-right">
              데이터 시작일: {data.actual_start_date}
            </p>
          </div>
        )}
      </DialogContent>
    </Dialog>
  )
}
