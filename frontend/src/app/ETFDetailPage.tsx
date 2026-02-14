import { useEffect, useMemo, useState } from 'react'
import { useParams } from 'react-router-dom'
import {
  LineChart,
  Line,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  ResponsiveContainer,
} from 'recharts'
import { TrendingUp, TrendingDown, Minus, Star, ChevronDown, ChevronRight, ArrowUp, ArrowDown, ArrowUpDown } from 'lucide-react'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs'
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
import { etfsApi, watchlistApi } from '@/lib/api'
import { Link } from 'react-router-dom'
import { useAuth } from '@/hooks/useAuth'
import { useToast } from '@/hooks/use-toast'
import type { ETF, Holding, HoldingChange, Price, SimilarETF } from '@/types/api'

export default function ETFDetailPage() {
  const { code } = useParams<{ code: string }>()
  const { isAuthenticated } = useAuth()
  const { toast } = useToast()

  const [etf, setEtf] = useState<ETF | null>(null)
  const [holdings, setHoldings] = useState<Holding[]>([])
  const [changes, setChanges] = useState<HoldingChange[]>([])
  const [prices, setPrices] = useState<Price[]>([])
  const [tags, setTags] = useState<string[]>([])
  const [loading, setLoading] = useState(true)
  const [isWatching, setIsWatching] = useState(false)
  const [watchToggling, setWatchToggling] = useState(false)
  const [similarEtfs, setSimilarEtfs] = useState<SimilarETF[]>([])
  const [changePeriod, setChangePeriod] = useState<'1d' | '1w' | '1m'>('1d')
  const [priceChartOpen, setPriceChartOpen] = useState(false)
  const [similarOpen, setSimilarOpen] = useState(false)

  type SortDir = 'asc' | 'desc'
  const [holdingSort, setHoldingSort] = useState<{ key: keyof Holding; dir: SortDir }>({ key: 'weight', dir: 'desc' })
  const [changeSort, setChangeSort] = useState<{ key: keyof HoldingChange; dir: SortDir }>({ key: 'current_weight', dir: 'desc' })

  const toggleSort = <T,>(
    current: { key: T; dir: SortDir },
    setter: (v: { key: T; dir: SortDir }) => void,
    key: T,
  ) => {
    if (current.key === key) {
      setter({ key, dir: current.dir === 'asc' ? 'desc' : 'asc' })
    } else {
      setter({ key, dir: 'desc' })
    }
  }

  const SortIcon = ({ active, dir }: { active: boolean; dir: SortDir }) =>
    active
      ? dir === 'asc' ? <ArrowUp className="w-3 h-3 inline ml-1" /> : <ArrowDown className="w-3 h-3 inline ml-1" />
      : <ArrowUpDown className="w-3 h-3 inline ml-1 opacity-30" />

  const sortedHoldings = useMemo(() => {
    const sorted = [...holdings]
    const { key, dir } = holdingSort
    sorted.sort((a, b) => {
      const av = a[key] ?? ''
      const bv = b[key] ?? ''
      if (typeof av === 'number' && typeof bv === 'number') return dir === 'asc' ? av - bv : bv - av
      return dir === 'asc' ? String(av).localeCompare(String(bv)) : String(bv).localeCompare(String(av))
    })
    return sorted
  }, [holdings, holdingSort])

  const sortedChanges = useMemo(() => {
    const sorted = [...changes]
    const { key, dir } = changeSort
    sorted.sort((a, b) => {
      const av = a[key] ?? ''
      const bv = b[key] ?? ''
      if (typeof av === 'number' && typeof bv === 'number') return dir === 'asc' ? av - bv : bv - av
      return dir === 'asc' ? String(av).localeCompare(String(bv)) : String(bv).localeCompare(String(av))
    })
    return sorted
  }, [changes, changeSort])

  useEffect(() => {
    if (!code) return

    const fetchData = async () => {
      setLoading(true)
      setEtf(null)
      setHoldings([])
      setChanges([])
      setPrices([])
      setTags([])
      setSimilarEtfs([])
      setPriceChartOpen(false)
      setSimilarOpen(false)
      setIsWatching(false)
      try {
        const [etfResult, holdingsResult, changesResult, pricesResult, tagsResult, similarResult] = await Promise.allSettled([
          etfsApi.get(code),
          etfsApi.getHoldings(code),
          etfsApi.getChanges(code),
          etfsApi.getPrices(code),
          etfsApi.getTags(code),
          etfsApi.getSimilar(code),
        ])
        if (etfResult.status === 'fulfilled') setEtf(etfResult.value)
        if (holdingsResult.status === 'fulfilled') setHoldings(holdingsResult.value)
        if (changesResult.status === 'fulfilled') setChanges(changesResult.value)
        if (pricesResult.status === 'fulfilled') setPrices(pricesResult.value)
        if (tagsResult.status === 'fulfilled') setTags(tagsResult.value)
        if (similarResult.status === 'fulfilled') setSimilarEtfs(similarResult.value)
      } catch (error) {
        console.error('Failed to fetch ETF data:', error)
      } finally {
        setLoading(false)
      }
    }

    fetchData()
  }, [code])

  // Check if current ETF is in user's watchlist
  useEffect(() => {
    if (!code || !isAuthenticated) return
    watchlistApi.getCodes().then((codes) => {
      setIsWatching(codes.includes(code))
    }).catch(() => {})
  }, [code, isAuthenticated])

  useEffect(() => {
    if (!code) return
    etfsApi.getChanges(code, changePeriod).then(setChanges).catch(() => {})
  }, [code, changePeriod])

  const handleToggleWatch = async () => {
    if (!isAuthenticated) {
      toast({ title: '로그인이 필요합니다', variant: 'destructive' })
      return
    }
    if (!code || watchToggling) return

    setWatchToggling(true)
    try {
      if (isWatching) {
        await watchlistApi.remove(code)
        setIsWatching(false)
        toast({ title: '즐겨찾기에서 해제되었습니다' })
      } else {
        await watchlistApi.add(code)
        setIsWatching(true)
        toast({ title: '즐겨찾기에 추가되었습니다' })
      }
    } catch {
      toast({ title: '처리 실패', variant: 'destructive' })
    } finally {
      setWatchToggling(false)
    }
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
        return <Minus className="w-4 h-4 text-gray-500" />
    }
  }

  const getChangeBadge = (type: string) => {
    const variants: Record<string, 'default' | 'destructive' | 'secondary'> = {
      added: 'default',
      increased: 'default',
      decreased: 'destructive',
      removed: 'destructive',
      unchanged: 'secondary',
    }
    const labels: Record<string, string> = {
      added: '신규',
      increased: '증가',
      decreased: '감소',
      removed: '제외',
      unchanged: '-',
    }
    return (
      <Badge variant={variants[type] || 'secondary'}>
        {labels[type] || type}
      </Badge>
    )
  }

  if (loading) {
    return <div className="text-center py-12">로딩 중...</div>
  }

  if (!etf) {
    return <div className="text-center py-12">ETF를 찾을 수 없습니다</div>
  }

  const chartData = prices
    .filter((p) => p.close != null)
    .map((p) => ({
      date: p.date,
      close: p.close,
    }))

  return (
    <div className="space-y-6">
      <div className="flex items-start justify-between">
        <div>
          <h1 className="text-3xl font-bold">{etf.name}</h1>
          <p className="text-muted-foreground">{etf.code}</p>
        </div>
        <Button
          variant="ghost"
          size="icon"
          onClick={handleToggleWatch}
          disabled={watchToggling}
          title={isWatching ? '즐겨찾기 해제' : '즐겨찾기 추가'}
        >
          <Star
            className={`w-6 h-6 ${isWatching ? 'fill-yellow-400 text-yellow-400' : 'text-muted-foreground'}`}
          />
        </Button>
      </div>

      <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
        <Card className="py-3">
          <CardContent className="pb-0 pt-0">
            <p className="text-xs text-muted-foreground">운용사</p>
            <p className="text-sm font-semibold mt-1">{etf.issuer || '-'}</p>
          </CardContent>
        </Card>
        <Card className="py-3">
          <CardContent className="pb-0 pt-0">
            <p className="text-xs text-muted-foreground">카테고리</p>
            <div className="flex flex-wrap gap-1 mt-1">
              {tags.length > 0
                ? tags.map((tag) => (
                    <Badge key={tag} variant="secondary" className="text-xs">
                      {tag}
                    </Badge>
                  ))
                : <p className="text-sm font-semibold">-</p>
              }
            </div>
          </CardContent>
        </Card>
        <Card className="py-3">
          <CardContent className="pb-0 pt-0">
            <p className="text-xs text-muted-foreground">순자산</p>
            <p className="text-sm font-semibold mt-1">
              {etf.net_assets ? `${(etf.net_assets / 100000000).toFixed(0)}억원` : '-'}
            </p>
          </CardContent>
        </Card>
        <Card className="py-3">
          <CardContent className="pb-0 pt-0">
            <p className="text-xs text-muted-foreground">보수율</p>
            <p className="text-sm font-semibold mt-1">
              {etf.expense_ratio ? `${etf.expense_ratio}%` : '-'}
            </p>
          </CardContent>
        </Card>
      </div>

      {(() => {
        const validPrices = prices.filter((p) => p.market_cap != null)
        if (validPrices.length === 0) return null
        const latest = validPrices[validPrices.length - 1]
        const latestDate = new Date(latest.date)
        const weekAgoTarget = new Date(latestDate)
        weekAgoTarget.setDate(weekAgoTarget.getDate() - 7)
        const weekAgoPrice = validPrices.reduce((closest, p) => {
          const d = new Date(p.date)
          if (d > latestDate) return closest
          if (!closest) return p
          return Math.abs(d.getTime() - weekAgoTarget.getTime()) < Math.abs(new Date(closest.date).getTime() - weekAgoTarget.getTime()) ? p : closest
        }, null as typeof latest | null)
        const latestCap = latest.market_cap!
        const weekAgoCap = weekAgoPrice && weekAgoPrice.market_cap && weekAgoPrice.date !== latest.date
          ? weekAgoPrice.market_cap : null
        const changeRate = weekAgoCap
          ? ((latestCap - weekAgoCap) / weekAgoCap) * 100
          : null
        const fmtCap = (v: number) => v >= 1_0000_0000
          ? `${Math.floor(v / 1_0000_0000).toLocaleString()}억원`
          : `${Math.floor(v / 1_0000).toLocaleString()}만원`
        return (
          <Card className="py-3">
            <CardContent className="pb-0 pt-0">
              <p className="text-xs text-muted-foreground">시가총액</p>
              <p className="text-sm font-semibold mt-1">
                {fmtCap(latestCap)}
                {changeRate != null && (
                  <span className={`text-xs font-normal ml-1 ${changeRate > 0 ? 'text-red-500' : changeRate < 0 ? 'text-blue-500' : 'text-muted-foreground'}`}>
                    {changeRate > 0 ? '+' : ''}{changeRate.toFixed(1)}%
                  </span>
                )}
              </p>
              {weekAgoCap != null && (
                <p className="text-[11px] text-muted-foreground mt-0.5">1W전 {fmtCap(weekAgoCap)}</p>
              )}
            </CardContent>
          </Card>
        )
      })()}

      <Card>
        <CardHeader
          className={`cursor-pointer select-none ${priceChartOpen ? '' : 'py-3'}`}
          onClick={() => setPriceChartOpen(!priceChartOpen)}
        >
          <CardTitle className={`flex items-center gap-2 ${priceChartOpen ? '' : 'text-sm'}`}>
            {priceChartOpen ? <ChevronDown className="w-4 h-4" /> : <ChevronRight className="w-4 h-4" />}
            가격 추이
          </CardTitle>
        </CardHeader>
        {priceChartOpen && (
          <CardContent>
            <div className="h-[200px]">
              <ResponsiveContainer width="100%" height="100%">
                <LineChart data={chartData}>
                  <CartesianGrid strokeDasharray="3 3" />
                  <XAxis
                    dataKey="date"
                    tick={{ fontSize: 12 }}
                    tickFormatter={(value) => value.slice(5)}
                  />
                  <YAxis tick={{ fontSize: 12 }} domain={['auto', 'auto']} />
                  <Tooltip />
                  <Line
                    type="monotone"
                    dataKey="close"
                    stroke="#2563eb"
                    strokeWidth={2}
                    dot={false}
                  />
                </LineChart>
              </ResponsiveContainer>
            </div>
          </CardContent>
        )}
      </Card>

      {similarEtfs.length > 0 && (
        <Card>
          <CardHeader
            className={`cursor-pointer select-none ${similarOpen ? '' : 'py-3'}`}
            onClick={() => setSimilarOpen(!similarOpen)}
          >
            <CardTitle className={`flex items-center gap-2 ${similarOpen ? '' : 'text-sm'}`}>
              {similarOpen ? <ChevronDown className="w-4 h-4" /> : <ChevronRight className="w-4 h-4" />}
              유사 ETF
              <Badge variant="secondary" className="text-xs">{similarEtfs.length}</Badge>
            </CardTitle>
          </CardHeader>
          {similarOpen && (
            <CardContent>
              <Table>
                <TableHeader>
                  <TableRow>
                    <TableHead>ETF명</TableHead>
                    <TableHead className="text-right">겹침 종목</TableHead>
                    <TableHead className="text-right">비중 유사도</TableHead>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {similarEtfs.map((s) => (
                    <TableRow key={s.etf_code}>
                      <TableCell>
                        <Link to={`/etf/${s.etf_code}`} className="text-blue-600 hover:underline font-medium">
                          {s.name}
                        </Link>
                        <span className="text-xs text-muted-foreground ml-2">{s.etf_code}</span>
                      </TableCell>
                      <TableCell className="text-right">{s.overlap}개</TableCell>
                      <TableCell className="text-right">{s.similarity.toFixed(1)}%</TableCell>
                    </TableRow>
                  ))}
                </TableBody>
              </Table>
            </CardContent>
          )}
        </Card>
      )}

      <Tabs defaultValue="holdings">
        <TabsList>
          <TabsTrigger value="holdings">구성 종목</TabsTrigger>
          <TabsTrigger value="changes">비중 변화</TabsTrigger>
        </TabsList>

        <TabsContent value="holdings" className="mt-4">
          <Card>
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead className="cursor-pointer select-none" onClick={() => toggleSort(holdingSort, setHoldingSort, 'stock_name')}>종목명<SortIcon active={holdingSort.key === 'stock_name'} dir={holdingSort.dir} /></TableHead>
                  <TableHead className="cursor-pointer select-none" onClick={() => toggleSort(holdingSort, setHoldingSort, 'stock_code')}>종목코드<SortIcon active={holdingSort.key === 'stock_code'} dir={holdingSort.dir} /></TableHead>
                  <TableHead className="text-right cursor-pointer select-none" onClick={() => toggleSort(holdingSort, setHoldingSort, 'weight')}>비중<SortIcon active={holdingSort.key === 'weight'} dir={holdingSort.dir} /></TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {sortedHoldings.map((holding) => (
                  <TableRow key={holding.stock_code}>
                    <TableCell className="font-medium">{holding.stock_name}</TableCell>
                    <TableCell>{holding.stock_code}</TableCell>
                    <TableCell className="text-right">
                      {holding.weight.toFixed(2)}%
                    </TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          </Card>
        </TabsContent>

        <TabsContent value="changes" className="mt-4">
          <div className="flex gap-1 mb-3">
            {(['1d', '1w', '1m'] as const).map((p) => (
              <Button
                key={p}
                size="sm"
                variant={changePeriod === p ? 'default' : 'outline'}
                onClick={() => setChangePeriod(p)}
              >
                {p === '1d' ? '전일' : p === '1w' ? '1주' : '1개월'}
              </Button>
            ))}
          </div>
          <Card>
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead className="cursor-pointer select-none" onClick={() => toggleSort(changeSort, setChangeSort, 'stock_name')}>종목명<SortIcon active={changeSort.key === 'stock_name'} dir={changeSort.dir} /></TableHead>
                  <TableHead className="cursor-pointer select-none" onClick={() => toggleSort(changeSort, setChangeSort, 'change_type')}>변화<SortIcon active={changeSort.key === 'change_type'} dir={changeSort.dir} /></TableHead>
                  <TableHead className="text-right cursor-pointer select-none" onClick={() => toggleSort(changeSort, setChangeSort, 'previous_weight')}>이전 비중<SortIcon active={changeSort.key === 'previous_weight'} dir={changeSort.dir} /></TableHead>
                  <TableHead className="text-right cursor-pointer select-none" onClick={() => toggleSort(changeSort, setChangeSort, 'current_weight')}>현재 비중<SortIcon active={changeSort.key === 'current_weight'} dir={changeSort.dir} /></TableHead>
                  <TableHead className="text-right cursor-pointer select-none" onClick={() => toggleSort(changeSort, setChangeSort, 'weight_change')}>변화량<SortIcon active={changeSort.key === 'weight_change'} dir={changeSort.dir} /></TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {sortedChanges.map((change) => (
                  <TableRow key={change.stock_code}>
                    <TableCell>
                      <div className="flex items-center gap-2">
                        {getChangeIcon(change.change_type)}
                        <span className="font-medium">{change.stock_name}</span>
                      </div>
                    </TableCell>
                    <TableCell>{getChangeBadge(change.change_type)}</TableCell>
                    <TableCell className="text-right">
                      {change.previous_weight.toFixed(2)}%
                    </TableCell>
                    <TableCell className="text-right">
                      {change.current_weight.toFixed(2)}%
                    </TableCell>
                    <TableCell
                      className={`text-right ${
                        change.weight_change > 0
                          ? 'text-green-600'
                          : change.weight_change < 0
                          ? 'text-red-600'
                          : ''
                      }`}
                    >
                      {change.weight_change > 0 ? '+' : ''}
                      {change.weight_change.toFixed(2)}%
                    </TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          </Card>
        </TabsContent>
      </Tabs>
    </div>
  )
}
