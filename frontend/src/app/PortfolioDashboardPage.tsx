import { useEffect, useMemo, useState } from 'react'
import { useParams, Link } from 'react-router-dom'
import { ArrowLeft, ChevronDown, ChevronUp } from 'lucide-react'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { Button } from '@/components/ui/button'
import { portfolioApi } from '@/lib/api'
import { useAuth } from '@/hooks/useAuth'
import type { DashboardResponse, DashboardSummaryItem, TotalHoldingsResponse } from '@/types/api'
import {
  ComposedChart,
  Line,
  Bar,
  Cell,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  ResponsiveContainer,
} from 'recharts'

function formatNumber(n: number): string {
  return new Intl.NumberFormat('ko-KR').format(Math.round(n))
}

function formatManwon(n: number): string {
  const man = Math.floor(Math.abs(n) / 10000)
  const sign = n < 0 ? '-' : ''
  if (man >= 10000) {
    const eok = Math.floor(man / 10000)
    const rest = man % 10000
    return rest > 0
      ? `${sign}${eok}억${new Intl.NumberFormat('ko-KR').format(rest)}만`
      : `${sign}${eok}억`
  }
  return `${sign}${new Intl.NumberFormat('ko-KR').format(man)}만`
}

function formatRate(rate: number): string {
  const sign = rate >= 0 ? '+' : ''
  return `${sign}${rate.toFixed(2)}%`
}

function SummaryCard({
  title,
  item,
}: {
  title: string
  item: DashboardSummaryItem | null
}) {
  if (!item) {
    return (
      <Card>
        <CardHeader className="px-4 py-2 pb-1">
          <CardTitle className="text-sm font-medium text-muted-foreground">
            {title}
          </CardTitle>
        </CardHeader>
        <CardContent className="px-4 pb-3 pt-0">
          <p className="text-sm text-muted-foreground">데이터 없음</p>
        </CardContent>
      </Card>
    )
  }

  const isPositive = item.rate >= 0
  const colorClass = isPositive ? 'text-red-500' : 'text-blue-500'

  return (
    <Card>
      <CardHeader className="px-4 py-2 pb-1">
        <CardTitle className="text-sm font-medium text-muted-foreground">
          {title}
        </CardTitle>
      </CardHeader>
      <CardContent className="px-4 pb-3 pt-0">
        <p className={`text-lg font-bold ${colorClass}`}>
          {formatRate(item.rate)}
        </p>
        <p className={`text-sm ${colorClass}`}>
          {item.amount >= 0 ? '+' : ''}{formatNumber(item.amount)}원
        </p>
      </CardContent>
    </Card>
  )
}

export default function PortfolioDashboardPage() {
  const { id } = useParams<{ id: string }>()
  const { isAuthenticated } = useAuth()
  const [dashboard, setDashboard] = useState<DashboardResponse | null>(null)
  const [loading, setLoading] = useState(true)
  const [totalHoldings, setTotalHoldings] = useState<TotalHoldingsResponse | null>(null)
  const [period, setPeriod] = useState<'1M' | '3M' | '6M' | '1Y' | 'ALL'>('ALL')
  const [chartOpen, setChartOpen] = useState(true)
  const isTotal = !id

  useEffect(() => {
    if (!isAuthenticated) return

    const fetchDashboard = async () => {
      try {
        const data = isTotal
          ? await portfolioApi.getTotalDashboard()
          : await portfolioApi.getDashboard(Number(id))
        setDashboard(data)
      } catch {
        console.error('Failed to fetch dashboard')
      } finally {
        setLoading(false)
      }
    }
    fetchDashboard()
  }, [isAuthenticated, id, isTotal])

  useEffect(() => {
    if (!isAuthenticated || !isTotal) return

    const fetchHoldings = async () => {
      try {
        const data = await portfolioApi.getTotalHoldings()
        setTotalHoldings(data)
      } catch {
        console.error('Failed to fetch total holdings')
      }
    }
    fetchHoldings()
  }, [isAuthenticated, isTotal])

  const chartDataWithChange = useMemo(() => {
    const all = dashboard?.chart_data ?? []
    if (all.length === 0) return []

    let filtered = all
    if (period !== 'ALL') {
      const now = new Date(all[all.length - 1].date)
      const months = { '1M': 1, '3M': 3, '6M': 6, '1Y': 12 }[period]
      const cutoff = new Date(now)
      cutoff.setMonth(cutoff.getMonth() - months)
      const cutoffStr = cutoff.toISOString().slice(0, 10)
      // include one extra point before cutoff for first daily_rate calc
      const startIdx = Math.max(0, all.findIndex((p) => p.date >= cutoffStr) - 1)
      filtered = all.slice(startIdx)
    }

    return filtered.map((point, i) => {
      const value = Number(point.total_value)
      const prevValue = i > 0 ? Number(filtered[i - 1].total_value) : value
      return {
        ...point,
        total_value: value,
        daily_rate: i === 0 ? 0 : prevValue ? ((value - prevValue) / prevValue) * 100 : 0,
      }
    })
  }, [dashboard?.chart_data, period])

  if (!isAuthenticated) {
    return (
      <div className="text-center py-12">
        <h2 className="text-2xl font-bold mb-4">로그인이 필요합니다</h2>
        <Link to="/login">
          <Button>로그인하기</Button>
        </Link>
      </div>
    )
  }

  if (loading) {
    return <div className="text-center py-12">로딩 중...</div>
  }

  if (!dashboard || dashboard.chart_data.length === 0) {
    return (
      <div className="space-y-6">
        <div className="flex items-center gap-4">
          <Link to="/portfolio">
            <Button variant="ghost" size="sm">
              <ArrowLeft className="w-4 h-4 mr-1" />
              포트폴리오
            </Button>
          </Link>
          <h2 className="text-xl font-bold">
            {isTotal ? '통합 대시보드' : '대시보드'}
          </h2>
        </div>
        <Card>
          <CardContent className="py-12 text-center">
            <p className="text-muted-foreground">
              아직 스냅샷 데이터가 없습니다.
            </p>
            <p className="text-sm text-muted-foreground mt-2">
              일별 배치가 실행되면 데이터가 수집됩니다.
            </p>
          </CardContent>
        </Card>
      </div>
    )
  }

  const { summary } = dashboard

  return (
    <div className="space-y-6">
      {/* Header + Current Value */}
      <div className="flex items-center gap-4">
        <Link to="/portfolio">
          <Button variant="ghost" size="sm">
            <ArrowLeft className="w-4 h-4 mr-1" />
            포트폴리오
          </Button>
        </Link>
        <h2 className="text-xl font-bold shrink-0">
          {isTotal ? '통합 대시보드' : '대시보드'}
        </h2>
        <div className="flex-1 flex items-center justify-between border rounded-lg px-5 py-2 bg-card shadow-sm">
          <p className="text-2xl font-bold font-mono">
            <span className="text-sm font-normal text-muted-foreground mr-1">평가금액 :</span>
            {formatNumber(summary.current_value)}원
          </p>
          {summary.daily && (
            <p
              className={`text-base font-bold ${summary.daily.rate >= 0 ? 'text-red-500' : 'text-blue-500'}`}
            >
              {summary.daily.amount >= 0 ? '+' : ''}
              {formatNumber(summary.daily.amount)}원 ({formatRate(summary.daily.rate)})
            </p>
          )}
        </div>
      </div>

      {!isTotal && (
        <Card>
          <CardContent className="py-4">
            <div className="flex flex-wrap items-center gap-6">
              <div>
                <p className="text-sm text-muted-foreground">투자금액</p>
                <p className="text-base font-mono">
                  {summary.invested_amount != null
                    ? `${formatNumber(summary.invested_amount)}원`
                    : '-'}
                </p>
              </div>
              <div>
                <p className="text-sm text-muted-foreground">투자 수익률</p>
                {summary.investment_return ? (
                  <p
                    className={`text-base font-bold ${summary.investment_return.rate >= 0 ? 'text-red-500' : 'text-blue-500'}`}
                  >
                    {summary.investment_return.amount >= 0 ? '+' : ''}
                    {formatNumber(summary.investment_return.amount)}원 (
                    {formatRate(summary.investment_return.rate)})
                  </p>
                ) : (
                  <p className="text-base font-mono">-</p>
                )}
              </div>
            </div>
          </CardContent>
        </Card>
      )}

      {/* Summary Cards */}
      <div className="grid gap-4 grid-cols-2 lg:grid-cols-4">
        <SummaryCard title="전일대비" item={summary.daily} />
        <SummaryCard title="전달대비" item={summary.monthly} />
        <SummaryCard title="전년대비" item={summary.yearly} />
        <SummaryCard title="올해 수익률 (YTD)" item={summary.ytd} />
      </div>

      {/* Value Chart */}
      <Card>
        <CardHeader className="flex flex-row items-center justify-between px-4 py-3">
          <div className="flex items-center gap-1">
            <CardTitle className="text-base">평가금액 추이</CardTitle>
            {isTotal && (
              <Button
                variant="ghost"
                size="sm"
                className="h-7 w-7 p-0"
                onClick={() => setChartOpen((prev) => !prev)}
              >
                {chartOpen ? <ChevronUp className="w-4 h-4" /> : <ChevronDown className="w-4 h-4" />}
              </Button>
            )}
          </div>
          {chartOpen && (
            <div className="flex gap-1">
              {(['1M', '3M', '6M', '1Y', 'ALL'] as const).map((p) => (
                <Button
                  key={p}
                  variant={period === p ? 'default' : 'ghost'}
                  size="sm"
                  className="h-7 px-2 text-xs"
                  onClick={() => setPeriod(p)}
                >
                  {p === 'ALL' ? '전체' : p}
                </Button>
              ))}
            </div>
          )}
        </CardHeader>
        {chartOpen && (
          <CardContent className="px-4 pb-4 pt-0">
            <ResponsiveContainer width="100%" height={300}>
              <ComposedChart data={chartDataWithChange}>
                <CartesianGrid strokeDasharray="3 3" />
                <XAxis
                  dataKey="date"
                  tick={{ fontSize: 12 }}
                  tickFormatter={(v) => v.slice(5)}
                  interval={Math.max(0, Math.floor(chartDataWithChange.length / 8) - 1)}
                />
                <YAxis
                  yAxisId="rate"
                  tick={{ fontSize: 11 }}
                  tickFormatter={(v) => `${v.toFixed(1)}%`}
                  label={{ value: '일별 수익률', angle: -90, position: 'insideLeft', style: { fontSize: 11, fill: '#888' } }}
                />
                <YAxis
                  yAxisId="value"
                  orientation="right"
                  tick={{ fontSize: 12 }}
                  tickFormatter={(v) => formatManwon(v)}
                  label={{ value: '평가금액', angle: 90, position: 'insideRight', style: { fontSize: 11, fill: '#888' } }}
                  domain={[
                    (dataMin: number) => Math.floor(dataMin * 0.95),
                    (dataMax: number) => Math.ceil(dataMax * 1.05),
                  ]}
                />
                <Tooltip
                  formatter={(value: number, name: string) => {
                    if (name === 'total_value') return [`${formatNumber(value)}원`, '평가금액']
                    const sign = value >= 0 ? '+' : ''
                    return [`${sign}${value.toFixed(2)}%`, '일별 수익률']
                  }}
                  labelFormatter={(label) => label}
                />
                <Bar yAxisId="rate" dataKey="daily_rate" name="일별 수익률" opacity={0.4}>
                  {chartDataWithChange.map((entry, index) => (
                    <Cell
                      key={`cell-${index}`}
                      fill={entry.daily_rate >= 0 ? '#ef4444' : '#3b82f6'}
                    />
                  ))}
                </Bar>
                <Line
                  yAxisId="value"
                  type="monotone"
                  dataKey="total_value"
                  stroke="#6366f1"
                  strokeWidth={2.5}
                  dot={false}
                />
              </ComposedChart>
            </ResponsiveContainer>
          </CardContent>
        )}
      </Card>

      {/* Holdings Weight Table (Total Dashboard only) */}
      {isTotal && totalHoldings && totalHoldings.holdings.length > 0 && (
        <Card>
          <CardHeader>
            <CardTitle className="text-base">종목 비중</CardTitle>
          </CardHeader>
          <CardContent>
            <div className="overflow-x-auto">
              <table className="w-full text-sm">
                <thead>
                  <tr className="border-b text-left text-muted-foreground">
                    <th className="pb-2 font-medium">종목</th>
                    <th className="pb-2 font-medium text-right">수량</th>
                    <th className="pb-2 font-medium text-right">현재가</th>
                    <th className="pb-2 font-medium text-right">평가금액</th>
                    <th className="pb-2 font-medium text-right w-[140px]">비중</th>
                  </tr>
                </thead>
                <tbody>
                  {totalHoldings.holdings.map((h) => (
                    <tr key={h.ticker} className="border-b last:border-0">
                      <td className="py-2">
                        <div className="font-medium">{h.name}</div>
                        <div className="text-xs text-muted-foreground">{h.ticker}</div>
                      </td>
                      <td className="py-2 text-right font-mono">
                        {formatNumber(h.quantity)}
                      </td>
                      <td className="py-2 text-right font-mono">
                        {formatNumber(h.current_price)}원
                      </td>
                      <td className="py-2 text-right font-mono">
                        {formatNumber(h.value)}원
                      </td>
                      <td className="py-2 text-right">
                        <div className="flex items-center justify-end gap-2">
                          <div className="w-16 bg-muted rounded-full h-2">
                            <div
                              className="bg-indigo-500 h-2 rounded-full"
                              style={{ width: `${Math.min(h.weight, 100)}%` }}
                            />
                          </div>
                          <span className="font-mono text-xs w-12 text-right">
                            {h.weight.toFixed(1)}%
                          </span>
                        </div>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </CardContent>
        </Card>
      )}

    </div>
  )
}
