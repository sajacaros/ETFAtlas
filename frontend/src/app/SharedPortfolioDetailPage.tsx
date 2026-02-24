import { useEffect, useState } from 'react'
import { useParams, Link } from 'react-router-dom'
import { sharedApi } from '@/lib/api'
import type { SharedPortfolioDetail, SharedReturnsResponse } from '@/types/api'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { Button } from '@/components/ui/button'
import { ArrowLeft } from 'lucide-react'
import {
  ResponsiveContainer, LineChart, Line, XAxis, YAxis, Tooltip, CartesianGrid,
} from 'recharts'

const PERIODS = [
  { key: '1w', label: '1주' },
  { key: '1m', label: '1개월' },
  { key: '3m', label: '3개월' },
] as const

export default function SharedPortfolioDetailPage() {
  const { shareToken } = useParams<{ shareToken: string }>()
  const [detail, setDetail] = useState<SharedPortfolioDetail | null>(null)
  const [returns, setReturns] = useState<SharedReturnsResponse | null>(null)
  const [period, setPeriod] = useState('1m')
  const [loading, setLoading] = useState(true)
  const [returnsError, setReturnsError] = useState<string | null>(null)

  useEffect(() => {
    if (!shareToken) return
    sharedApi.get(shareToken)
      .then(setDetail)
      .catch(console.error)
      .finally(() => setLoading(false))
  }, [shareToken])

  useEffect(() => {
    if (!shareToken) return
    setReturnsError(null)
    sharedApi.getReturns(shareToken, period)
      .then(setReturns)
      .catch(() => setReturnsError('수익률 데이터를 불러올 수 없습니다'))
  }, [shareToken, period])

  if (loading) return <div className="text-center py-12 text-muted-foreground">로딩 중...</div>
  if (!detail) return <div className="text-center py-12 text-muted-foreground">포트폴리오를 찾을 수 없습니다</div>

  const totalWeight = detail.allocations.reduce((sum, a) => sum + a.weight, 0)

  return (
    <div className="space-y-6">
      <div className="flex items-center gap-4">
        <Link to="/shared">
          <Button variant="ghost" size="sm"><ArrowLeft className="w-4 h-4 mr-1" />목록</Button>
        </Link>
        <div>
          <h1 className="text-2xl font-bold">{detail.portfolio_name}</h1>
          <p className="text-sm text-muted-foreground">{detail.user_name}</p>
        </div>
      </div>

      {/* 종목 비중 테이블 */}
      <Card>
        <CardHeader>
          <CardTitle className="text-lg">종목 비중</CardTitle>
        </CardHeader>
        <CardContent>
          <table className="w-full text-sm">
            <thead>
              <tr className="border-b text-muted-foreground">
                <th className="text-left py-2">종목</th>
                <th className="text-left py-2">티커</th>
                <th className="text-right py-2">비중</th>
              </tr>
            </thead>
            <tbody>
              {detail.allocations.map((a) => (
                <tr key={a.ticker} className="border-b">
                  <td className="py-2">{a.name}</td>
                  <td className="py-2 text-muted-foreground">{a.ticker}</td>
                  <td className="py-2 text-right font-medium">{a.weight.toFixed(1)}%</td>
                </tr>
              ))}
              <tr className="font-semibold">
                <td className="py-2" colSpan={2}>합계</td>
                <td className="py-2 text-right">{totalWeight.toFixed(1)}%</td>
              </tr>
            </tbody>
          </table>
        </CardContent>
      </Card>

      {/* 가상 수익률 차트 */}
      <Card>
        <CardHeader>
          <div className="flex items-center justify-between">
            <CardTitle className="text-lg">
              가상 수익률 (1,000만원 기준)
            </CardTitle>
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
          </div>
        </CardHeader>
        <CardContent>
          {returnsError ? (
            <p className="text-center text-sm text-muted-foreground py-8">{returnsError}</p>
          ) : !returns ? (
            <p className="text-center text-sm text-muted-foreground py-8">로딩 중...</p>
          ) : (
            <>
              {returns.actual_start_date !== returns.chart_data[0]?.date && (
                <p className="text-xs text-muted-foreground mb-2">
                  * 데이터 시작일: {returns.actual_start_date}
                </p>
              )}
              <div className="h-64">
                <ResponsiveContainer width="100%" height="100%">
                  <LineChart data={returns.chart_data}>
                    <CartesianGrid strokeDasharray="3 3" />
                    <XAxis
                      dataKey="date"
                      tickFormatter={(v: string) => v.slice(5)}
                      tick={{ fontSize: 12 }}
                    />
                    <YAxis
                      tickFormatter={(v: number) => `${(v / 10000).toFixed(0)}만`}
                      tick={{ fontSize: 12 }}
                    />
                    <Tooltip
                      formatter={(v: number) => [`${v.toLocaleString()}원`, '평가금액']}
                      labelFormatter={(l: string) => l}
                    />
                    <Line
                      type="monotone"
                      dataKey="value"
                      stroke="#2563eb"
                      strokeWidth={2}
                      dot={false}
                    />
                  </LineChart>
                </ResponsiveContainer>
              </div>
              {returns.chart_data.length > 0 && (
                <div className="mt-4 flex gap-4 text-sm">
                  <span>시작: {returns.chart_data[0].value.toLocaleString()}원</span>
                  <span>현재: {returns.chart_data[returns.chart_data.length - 1].value.toLocaleString()}원</span>
                  <span className={
                    returns.chart_data[returns.chart_data.length - 1].value >= returns.chart_data[0].value
                      ? 'text-green-600' : 'text-red-600'
                  }>
                    수익률: {(
                      ((returns.chart_data[returns.chart_data.length - 1].value - returns.chart_data[0].value) /
                        returns.chart_data[0].value) * 100
                    ).toFixed(2)}%
                  </span>
                </div>
              )}
            </>
          )}
        </CardContent>
      </Card>
    </div>
  )
}
