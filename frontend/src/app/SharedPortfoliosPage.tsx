import { useEffect, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { sharedApi } from '@/lib/api'
import type { SharedPortfolioListItem, SharedReturnsSummary } from '@/types/api'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { Users } from 'lucide-react'

function ReturnBadge({ value }: { value: number | null }) {
  if (value === null) return <span className="text-muted-foreground">-</span>
  const color = value >= 0 ? 'text-green-600' : 'text-red-600'
  const sign = value >= 0 ? '+' : ''
  return <span className={color}>{sign}{value.toFixed(1)}%</span>
}

export default function SharedPortfoliosPage() {
  const navigate = useNavigate()
  const [portfolios, setPortfolios] = useState<SharedPortfolioListItem[]>([])
  const [loading, setLoading] = useState(true)
  const [returnsMap, setReturnsMap] = useState<Record<string, SharedReturnsSummary>>({})

  useEffect(() => {
    sharedApi.getAll()
      .then((list) => {
        setPortfolios(list)
        list.forEach((p) => {
          sharedApi.getReturnsSummary(p.share_token)
            .then((summary) => {
              setReturnsMap((prev) => ({ ...prev, [p.share_token]: summary }))
            })
            .catch(() => {})
        })
      })
      .catch(console.error)
      .finally(() => setLoading(false))
  }, [])

  if (loading) return <div className="text-center py-12 text-muted-foreground">로딩 중...</div>

  if (portfolios.length === 0) {
    return (
      <div className="text-center py-12 text-muted-foreground">
        <Users className="w-12 h-12 mx-auto mb-4 opacity-50" />
        <p>공유된 포트폴리오가 없습니다</p>
      </div>
    )
  }

  return (
    <div className="space-y-6">
      <h1 className="text-2xl font-bold">공유 포트폴리오</h1>
      <div className="grid gap-4 md:grid-cols-2 lg:grid-cols-3">
        {portfolios.map((p) => {
          const r = returnsMap[p.share_token]
          return (
            <Card
              key={p.share_token}
              className="cursor-pointer hover:shadow-md transition-shadow"
              onClick={() => navigate(`/shared/${p.share_token}`)}
            >
              <CardHeader className="pb-2">
                <CardTitle className="text-lg">{p.portfolio_name}</CardTitle>
              </CardHeader>
              <CardContent>
                <div className="text-sm text-muted-foreground space-y-1">
                  <p>종목 {p.tickers_count}개</p>
                  {p.updated_at && (
                    <p className="text-xs">
                      {new Date(p.updated_at).toLocaleDateString('ko-KR')}
                    </p>
                  )}
                </div>
                <div className="mt-3 pt-3 border-t">
                  <div className="grid grid-cols-3 gap-2 text-center text-xs">
                    <div>
                      <p className="text-muted-foreground mb-0.5">1주</p>
                      <p className="font-medium"><ReturnBadge value={r?.returns_1w ?? null} /></p>
                    </div>
                    <div>
                      <p className="text-muted-foreground mb-0.5">1달</p>
                      <p className="font-medium"><ReturnBadge value={r?.returns_1m ?? null} /></p>
                    </div>
                    <div>
                      <p className="text-muted-foreground mb-0.5">3달</p>
                      <p className="font-medium"><ReturnBadge value={r?.returns_3m ?? null} /></p>
                    </div>
                  </div>
                </div>
              </CardContent>
            </Card>
          )
        })}
      </div>
    </div>
  )
}
