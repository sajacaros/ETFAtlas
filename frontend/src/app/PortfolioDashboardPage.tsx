import { useEffect, useState } from 'react'
import { useParams, Link } from 'react-router-dom'
import { ArrowLeft } from 'lucide-react'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { Button } from '@/components/ui/button'
import { portfolioApi } from '@/lib/api'
import { useAuth } from '@/hooks/useAuth'
import type { DashboardResponse, DashboardSummaryItem, TotalHoldingsResponse } from '@/types/api'
import {
  LineChart,
  Line,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  ResponsiveContainer,
} from 'recharts'

function formatNumber(n: number): string {
  return new Intl.NumberFormat('ko-KR').format(Math.round(n))
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
        <CardHeader className="pb-2">
          <CardTitle className="text-sm font-medium text-muted-foreground">
            {title}
          </CardTitle>
        </CardHeader>
        <CardContent>
          <p className="text-sm text-muted-foreground">데이터 없음</p>
        </CardContent>
      </Card>
    )
  }

  const isPositive = item.rate >= 0
  const colorClass = isPositive ? 'text-red-500' : 'text-blue-500'

  return (
    <Card>
      <CardHeader className="pb-2">
        <CardTitle className="text-sm font-medium text-muted-foreground">
          {title}
        </CardTitle>
      </CardHeader>
      <CardContent>
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

  const { summary, chart_data } = dashboard

  return (
    <div className="space-y-6">
      {/* Header */}
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

      {/* Summary Cards */}
      <div className="grid gap-4 grid-cols-2 lg:grid-cols-4">
        <SummaryCard title="전일대비" item={summary.daily} />
        <SummaryCard title="전달대비" item={summary.monthly} />
        <SummaryCard title="전년대비" item={summary.yearly} />
        <SummaryCard title="올해 수익률 (YTD)" item={summary.ytd} />
      </div>

      {/* Current Value + Daily Change Banner */}
      <Card>
        <CardContent className="py-4">
          <div className="flex flex-wrap items-center justify-between gap-4">
            <div>
              <p className="text-sm text-muted-foreground">현재 평가금액</p>
              <p className="text-2xl font-bold font-mono">
                {formatNumber(summary.current_value)}원
              </p>
            </div>
            {summary.daily && (
              <div className="text-right">
                <p className="text-sm text-muted-foreground">전일대비</p>
                <p
                  className={`text-lg font-bold ${summary.daily.rate >= 0 ? 'text-red-500' : 'text-blue-500'}`}
                >
                  {summary.daily.amount >= 0 ? '+' : ''}
                  {formatNumber(summary.daily.amount)}원 (
                  {formatRate(summary.daily.rate)})
                </p>
              </div>
            )}
          </div>
          {!isTotal && (
            <div className="flex flex-wrap items-center gap-6 mt-3 pt-3 border-t">
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
          )}
        </CardContent>
      </Card>

      {/* Value Chart */}
      <Card>
        <CardHeader>
          <CardTitle className="text-base">평가금액 추이</CardTitle>
        </CardHeader>
        <CardContent>
          <ResponsiveContainer width="100%" height={300}>
            <LineChart data={chart_data}>
              <CartesianGrid strokeDasharray="3 3" />
              <XAxis
                dataKey="date"
                tick={{ fontSize: 12 }}
                tickFormatter={(v) => v.slice(5)}
              />
              <YAxis
                tick={{ fontSize: 12 }}
                tickFormatter={(v) => formatNumber(v)}
              />
              <Tooltip
                formatter={(value: number) => [
                  `${formatNumber(value)}원`,
                  '평가금액',
                ]}
                labelFormatter={(label) => label}
              />
              <Line
                type="monotone"
                dataKey="total_value"
                stroke="#6366f1"
                strokeWidth={2}
                dot={false}
              />
            </LineChart>
          </ResponsiveContainer>
        </CardContent>
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
