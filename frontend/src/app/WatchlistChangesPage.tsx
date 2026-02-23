import { useEffect, useMemo, useState } from 'react'
import { Link } from 'react-router-dom'
import { TrendingUp, TrendingDown, ArrowLeft, AlertCircle, Calendar, ArrowUpDown, ArrowUp, ArrowDown } from 'lucide-react'
import { Input } from '@/components/ui/input'
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
import { useNotification } from '@/hooks/useNotification'
import type { WatchlistChange } from '@/types/api'

type SortKey = 'etf_name' | 'stock_name' | 'change_type' | 'previous_weight' | 'current_weight' | 'weight_change'
type SortDir = 'asc' | 'desc'

export default function WatchlistChangesPage() {
  const { isAuthenticated } = useAuth()
  const { markChecked } = useNotification()
  const [changes, setChanges] = useState<WatchlistChange[]>([])
  const [currentDate, setCurrentDate] = useState<string | null>(null)
  const [previousDate, setPreviousDate] = useState<string | null>(null)
  const [period, setPeriod] = useState<'1d' | '1w' | '1m'>('1d')
  const [baseDate, setBaseDate] = useState('')
  const [filter, setFilter] = useState<'all' | 'increased' | 'decreased'>('all')
  const [loading, setLoading] = useState(true)
  const [sortKey, setSortKey] = useState<SortKey>('weight_change')
  const [sortDir, setSortDir] = useState<SortDir>('desc')

  // 페이지 진입 시 알림 확인 처리
  useEffect(() => {
    if (isAuthenticated) {
      markChecked()
    }
  }, [isAuthenticated, markChecked])

  useEffect(() => {
    if (!isAuthenticated) {
      setLoading(false)
      return
    }
    setLoading(true)
    watchlistApi
      .getChanges(period, baseDate || undefined)
      .then((res) => {
        setChanges(res.changes)
        setCurrentDate(res.current_date)
        setPreviousDate(res.previous_date)
      })
      .catch(() => {
        setChanges([])
        setCurrentDate(null)
        setPreviousDate(null)
      })
      .finally(() => setLoading(false))
  }, [isAuthenticated, period, baseDate])

  const filteredChanges = changes.filter((c) => {
    if (filter === 'increased') return c.change_type === 'increased' || c.change_type === 'added'
    if (filter === 'decreased') return c.change_type === 'decreased' || c.change_type === 'removed'
    return true
  })

  const handleSort = (key: SortKey) => {
    if (sortKey === key) {
      setSortDir((d) => (d === 'asc' ? 'desc' : 'asc'))
    } else {
      setSortKey(key)
      setSortDir(key === 'weight_change' ? 'desc' : 'asc')
    }
  }

  const sortedChanges = useMemo(() => {
    const sorted = [...filteredChanges]
    const dir = sortDir === 'asc' ? 1 : -1
    sorted.sort((a, b) => {
      switch (sortKey) {
        case 'etf_name':
          return dir * a.etf_name.localeCompare(b.etf_name)
        case 'stock_name':
          return dir * a.stock_name.localeCompare(b.stock_name)
        case 'change_type': {
          const order: Record<string, number> = { added: 0, increased: 1, decreased: 2, removed: 3 }
          return dir * ((order[a.change_type] ?? 4) - (order[b.change_type] ?? 4))
        }
        case 'previous_weight':
          return dir * (a.previous_weight - b.previous_weight)
        case 'current_weight':
          return dir * (a.current_weight - b.current_weight)
        case 'weight_change':
          return dir * (Math.abs(a.weight_change) - Math.abs(b.weight_change))
        default:
          return 0
      }
    })
    return sorted
  }, [filteredChanges, sortKey, sortDir])

  const SortIcon = ({ col }: { col: SortKey }) => {
    if (sortKey !== col) return <ArrowUpDown className="w-3 h-3 ml-1 opacity-30" />
    return sortDir === 'asc'
      ? <ArrowUp className="w-3 h-3 ml-1" />
      : <ArrowDown className="w-3 h-3 ml-1" />
  }

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

      <div className="flex items-center gap-4 flex-wrap">
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
        <div className="flex gap-1">
          {([
            { key: 'all', label: '모두보기' },
            { key: 'increased', label: '비중 증가' },
            { key: 'decreased', label: '비중 감소' },
          ] as const).map(({ key, label }) => (
            <Button
              key={key}
              size="sm"
              variant={filter === key ? 'default' : 'outline'}
              onClick={() => setFilter(key)}
            >
              {label}
            </Button>
          ))}
        </div>
        <div className="flex items-center gap-1">
          <Calendar className="w-4 h-4 text-muted-foreground" />
          <Input
            type="date"
            value={baseDate}
            onChange={(e) => setBaseDate(e.target.value)}
            className="w-36 h-8 text-sm"
          />
          {baseDate && (
            <Button size="sm" variant="ghost" onClick={() => setBaseDate('')}>
              오늘
            </Button>
          )}
        </div>
      </div>

      {currentDate && previousDate && (
        <p className="text-sm text-muted-foreground">
          기준일: {previousDate?.slice(2).replace(/-/g, '/')} → {currentDate?.slice(2).replace(/-/g, '/')}
        </p>
      )}

      {loading ? (
        <div className="text-center py-12 text-muted-foreground">로딩 중...</div>
      ) : sortedChanges.length === 0 ? (
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
                <TableHead className="cursor-pointer select-none" onClick={() => handleSort('etf_name')}>
                  <span className="inline-flex items-center">ETF<SortIcon col="etf_name" /></span>
                </TableHead>
                <TableHead className="cursor-pointer select-none" onClick={() => handleSort('stock_name')}>
                  <span className="inline-flex items-center">종목<SortIcon col="stock_name" /></span>
                </TableHead>
                <TableHead className="cursor-pointer select-none" onClick={() => handleSort('change_type')}>
                  <span className="inline-flex items-center">변화<SortIcon col="change_type" /></span>
                </TableHead>
                <TableHead className="cursor-pointer select-none text-right" onClick={() => handleSort('previous_weight')}>
                  <span className="inline-flex items-center justify-end w-full">이전<SortIcon col="previous_weight" /></span>
                </TableHead>
                <TableHead className="cursor-pointer select-none text-right" onClick={() => handleSort('current_weight')}>
                  <span className="inline-flex items-center justify-end w-full">현재<SortIcon col="current_weight" /></span>
                </TableHead>
                <TableHead className="cursor-pointer select-none text-right" onClick={() => handleSort('weight_change')}>
                  <span className="inline-flex items-center justify-end w-full">변화량<SortIcon col="weight_change" /></span>
                </TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {sortedChanges.map((c, i) => (
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
