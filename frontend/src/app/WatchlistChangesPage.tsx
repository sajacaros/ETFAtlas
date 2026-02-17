import { useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import { TrendingUp, TrendingDown, ArrowLeft, AlertCircle } from 'lucide-react'
import { Card } from '@/components/ui/card'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from '@/components/ui/table'
import { watchlistApi } from '@/lib/api'
import { useAuth } from '@/hooks/useAuth'
import type { WatchlistChange } from '@/types/api'

export default function WatchlistChangesPage() {
  const { isAuthenticated } = useAuth()
  const [changes, setChanges] = useState<WatchlistChange[]>([])
  const [period, setPeriod] = useState<'1d' | '1w' | '1m'>('1d')
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    if (!isAuthenticated) {
      setLoading(false)
      return
    }
    setLoading(true)
    watchlistApi
      .getChanges(period)
      .then(setChanges)
      .catch(() => setChanges([]))
      .finally(() => setLoading(false))
  }, [isAuthenticated, period])

  const getChangeIcon = (type: string) => {
    switch (type) {
      case 'increased':
      case 'added':
        return <TrendingUp className="w-4 h-4 text-green-500" />
      case 'decreased':
      case 'removed':
        return <TrendingDown className="w-4 h-4 text-red-500" />
      default:
        return null
    }
  }

  const getChangeBadge = (type: string) => {
    const variants: Record<string, 'default' | 'destructive' | 'secondary'> = {
      added: 'default',
      increased: 'default',
      decreased: 'destructive',
      removed: 'destructive',
    }
    const labels: Record<string, string> = {
      added: '신규 편입',
      increased: '비중 증가',
      decreased: '비중 감소',
      removed: '편출',
    }
    return (
      <Badge variant={variants[type] || 'secondary'}>
        {labels[type] || type}
      </Badge>
    )
  }

  if (!isAuthenticated) {
    return (
      <div className="text-center py-12 text-muted-foreground">
        로그인이 필요합니다
      </div>
    )
  }

  return (
    <div className="space-y-4">
      <div className="flex items-center gap-3">
        <Link to="/">
          <Button variant="ghost" size="icon">
            <ArrowLeft className="w-5 h-5" />
          </Button>
        </Link>
        <h1 className="text-2xl font-bold">즐겨찾기 비중 변화</h1>
      </div>

      <div className="flex gap-1">
        {(['1d', '1w', '1m'] as const).map((p) => (
          <Button
            key={p}
            size="sm"
            variant={period === p ? 'default' : 'outline'}
            onClick={() => setPeriod(p)}
          >
            {p === '1d' ? '전일' : p === '1w' ? '1주' : '1개월'}
          </Button>
        ))}
      </div>

      {loading ? (
        <div className="text-center py-12 text-muted-foreground">로딩 중...</div>
      ) : changes.length === 0 ? (
        <Card className="p-8">
          <div className="flex flex-col items-center gap-3 text-muted-foreground">
            <AlertCircle className="w-10 h-10" />
            <p className="text-lg font-medium">비중 변화가 감지되지 않았습니다</p>
            <p className="text-sm">
              즐겨찾기 ETF들의 보유종목 비중이 변하면 여기에 표시됩니다
            </p>
          </div>
        </Card>
      ) : (
        <Card>
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>ETF</TableHead>
                <TableHead>종목</TableHead>
                <TableHead>변화</TableHead>
                <TableHead className="text-right">이전</TableHead>
                <TableHead className="text-right">현재</TableHead>
                <TableHead className="text-right">변화량</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {changes.map((c, i) => (
                <TableRow key={`${c.etf_code}-${c.stock_code}-${i}`}>
                  <TableCell>
                    <Link
                      to={`/etf/${c.etf_code}`}
                      className="text-sm font-medium hover:underline text-primary"
                    >
                      {c.etf_name}
                    </Link>
                  </TableCell>
                  <TableCell>
                    <div className="flex items-center gap-2">
                      {getChangeIcon(c.change_type)}
                      <span className="font-medium">{c.stock_name}</span>
                    </div>
                  </TableCell>
                  <TableCell>{getChangeBadge(c.change_type)}</TableCell>
                  <TableCell className="text-right">
                    {c.previous_weight.toFixed(2)}%
                  </TableCell>
                  <TableCell className="text-right">
                    {c.current_weight.toFixed(2)}%
                  </TableCell>
                  <TableCell
                    className={`text-right font-medium ${
                      c.weight_change > 0
                        ? 'text-green-600'
                        : c.weight_change < 0
                          ? 'text-red-600'
                          : ''
                    }`}
                  >
                    {c.weight_change > 0 ? '+' : ''}
                    {c.weight_change.toFixed(2)}%p
                  </TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        </Card>
      )}
    </div>
  )
}
