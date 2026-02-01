import { useState, useEffect } from 'react'
import { Link, useNavigate } from 'react-router-dom'
import { RefreshCw, TrendingUp, TrendingDown, AlertCircle } from 'lucide-react'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'
import { Button } from '@/components/ui/button'
import { Badge } from '@/components/ui/badge'
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from '@/components/ui/table'
import { useAuth } from '@/hooks/useAuth'
import { aiApi, watchlistApi } from '@/lib/api'
import type { Signal, Insight, Watchlist } from '@/types/api'

export default function AIPage() {
  const navigate = useNavigate()
  const { isAuthenticated, isLoading: authLoading } = useAuth()
  const [signals, setSignals] = useState<Signal[]>([])
  const [insights, setInsights] = useState<Insight[]>([])
  const [watchlists, setWatchlists] = useState<Watchlist[]>([])
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    if (!authLoading && !isAuthenticated) {
      navigate('/login')
    }
  }, [authLoading, isAuthenticated, navigate])

  useEffect(() => {
    if (isAuthenticated) {
      fetchData()
    }
  }, [isAuthenticated])

  const fetchData = async () => {
    setLoading(true)
    setError(null)
    try {
      const [signalsData, insightsData, watchlistData] = await Promise.all([
        aiApi.getSignals(),
        aiApi.getInsights(),
        watchlistApi.getAll(),
      ])
      setSignals(signalsData)
      setInsights(insightsData)
      setWatchlists(watchlistData)
    } catch (err) {
      console.error('Failed to fetch AI data:', err)
      setError('데이터를 불러오는데 실패했습니다')
    } finally {
      setLoading(false)
    }
  }

  const buySignals = signals.filter((s) => s.signal_type === 'buy')
  const sellSignals = signals.filter((s) => s.signal_type === 'sell')

  const renderSignalStrength = (confidence: number) => {
    const stars = Math.round(confidence * 3)
    return '★'.repeat(stars) + '☆'.repeat(3 - stars)
  }

  const totalWatchlistItems = watchlists.reduce((acc, w) => acc + w.items.length, 0)

  if (authLoading) {
    return (
      <div className="flex items-center justify-center min-h-[60vh]">
        <div className="text-muted-foreground">로딩 중...</div>
      </div>
    )
  }

  if (!isAuthenticated) {
    return null
  }

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold">AI 종목 추천</h1>
          <p className="text-muted-foreground">
            워치리스트 ETF 포트폴리오 변화 기반 분석
          </p>
        </div>
        <Button onClick={fetchData} disabled={loading} variant="outline">
          <RefreshCw className={`w-4 h-4 mr-2 ${loading ? 'animate-spin' : ''}`} />
          새로고침
        </Button>
      </div>

      {error && (
        <Card className="border-destructive">
          <CardContent className="flex items-center gap-2 py-4 text-destructive">
            <AlertCircle className="w-5 h-5" />
            {error}
          </CardContent>
        </Card>
      )}

      {totalWatchlistItems === 0 && !loading && (
        <Card>
          <CardContent className="py-12 text-center">
            <p className="text-muted-foreground mb-4">
              AI 분석을 위해 먼저 워치리스트에 ETF를 추가해주세요
            </p>
            <Button asChild>
              <Link to="/watchlist">워치리스트로 이동</Link>
            </Button>
          </CardContent>
        </Card>
      )}

      {totalWatchlistItems > 0 && (
        <>
          <div className="text-sm text-muted-foreground">
            분석 대상: 워치리스트 ETF {totalWatchlistItems}개 | 분석 기간: 최근 1개월
          </div>

          <div className="grid md:grid-cols-2 gap-6">
            <Card>
              <CardHeader>
                <CardTitle className="flex items-center gap-2 text-green-600">
                  <TrendingUp className="w-5 h-5" />
                  매수 신호 종목
                </CardTitle>
                <CardDescription>
                  운용사들이 신규 편입하거나 비중을 늘린 종목
                </CardDescription>
              </CardHeader>
              <CardContent>
                {loading ? (
                  <div className="py-8 text-center text-muted-foreground">분석 중...</div>
                ) : buySignals.length > 0 ? (
                  <Table>
                    <TableHeader>
                      <TableRow>
                        <TableHead>ETF</TableHead>
                        <TableHead>시그널</TableHead>
                        <TableHead className="text-right">강도</TableHead>
                      </TableRow>
                    </TableHeader>
                    <TableBody>
                      {buySignals.map((signal) => (
                        <TableRow key={signal.etf_code}>
                          <TableCell>
                            <Link
                              to={`/etf/${signal.etf_code}`}
                              className="font-medium hover:underline"
                            >
                              {signal.etf_name}
                            </Link>
                          </TableCell>
                          <TableCell className="text-sm text-muted-foreground">
                            {signal.reason}
                          </TableCell>
                          <TableCell className="text-right text-yellow-500">
                            {renderSignalStrength(signal.confidence)}
                          </TableCell>
                        </TableRow>
                      ))}
                    </TableBody>
                  </Table>
                ) : (
                  <div className="py-8 text-center text-muted-foreground">
                    매수 신호가 없습니다
                  </div>
                )}
              </CardContent>
            </Card>

            <Card>
              <CardHeader>
                <CardTitle className="flex items-center gap-2 text-red-600">
                  <TrendingDown className="w-5 h-5" />
                  매도 신호 종목
                </CardTitle>
                <CardDescription>
                  운용사들이 제외하거나 비중을 줄인 종목
                </CardDescription>
              </CardHeader>
              <CardContent>
                {loading ? (
                  <div className="py-8 text-center text-muted-foreground">분석 중...</div>
                ) : sellSignals.length > 0 ? (
                  <Table>
                    <TableHeader>
                      <TableRow>
                        <TableHead>ETF</TableHead>
                        <TableHead>시그널</TableHead>
                        <TableHead className="text-right">강도</TableHead>
                      </TableRow>
                    </TableHeader>
                    <TableBody>
                      {sellSignals.map((signal) => (
                        <TableRow key={signal.etf_code}>
                          <TableCell>
                            <Link
                              to={`/etf/${signal.etf_code}`}
                              className="font-medium hover:underline"
                            >
                              {signal.etf_name}
                            </Link>
                          </TableCell>
                          <TableCell className="text-sm text-muted-foreground">
                            {signal.reason}
                          </TableCell>
                          <TableCell className="text-right text-yellow-500">
                            {renderSignalStrength(signal.confidence)}
                          </TableCell>
                        </TableRow>
                      ))}
                    </TableBody>
                  </Table>
                ) : (
                  <div className="py-8 text-center text-muted-foreground">
                    매도 신호가 없습니다
                  </div>
                )}
              </CardContent>
            </Card>
          </div>

          {insights.length > 0 && (
            <Card>
              <CardHeader>
                <CardTitle>AI 인사이트</CardTitle>
              </CardHeader>
              <CardContent className="space-y-4">
                {insights.map((insight, index) => (
                  <div key={index} className="p-4 bg-muted rounded-lg">
                    <h4 className="font-medium mb-2">{insight.title}</h4>
                    <p className="text-sm text-muted-foreground mb-2">{insight.content}</p>
                    <div className="flex gap-2 flex-wrap">
                      {insight.etfs.map((etf) => (
                        <Badge key={etf} variant="secondary">
                          {etf}
                        </Badge>
                      ))}
                    </div>
                  </div>
                ))}
              </CardContent>
            </Card>
          )}
        </>
      )}
    </div>
  )
}
