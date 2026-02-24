import { useEffect, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { sharedApi } from '@/lib/api'
import type { SharedPortfolioListItem } from '@/types/api'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { Users } from 'lucide-react'

export default function SharedPortfoliosPage() {
  const navigate = useNavigate()
  const [portfolios, setPortfolios] = useState<SharedPortfolioListItem[]>([])
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    sharedApi.getAll()
      .then(setPortfolios)
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
        {portfolios.map((p) => (
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
                <p>{p.user_name}</p>
                <p>종목 {p.tickers_count}개</p>
                {p.updated_at && (
                  <p className="text-xs">
                    {new Date(p.updated_at).toLocaleDateString('ko-KR')}
                  </p>
                )}
              </div>
            </CardContent>
          </Card>
        ))}
      </div>
    </div>
  )
}
