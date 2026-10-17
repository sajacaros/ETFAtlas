import { useEffect, useMemo, useState } from 'react'
import { useNavigate, useSearchParams } from 'react-router-dom'
import { sharedApi } from '@/lib/api'
import { formatDateTime } from '@/lib/utils'
import { ACCOUNT_TYPES } from '@/lib/accountType'
import { AccountTypeBadges } from '@/components/AccountType'
import type { AccountType, SharedPortfolioListItem, SharedReturnsSummary } from '@/types/api'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { Input } from '@/components/ui/input'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Search, Users, X } from 'lucide-react'

const SORTS = [
  { key: 'latest', label: '최신순' },
  { key: 'oldest', label: '오래된순' },
  { key: 'returns_1w', label: '1주 수익률순' },
  { key: 'returns_1m', label: '1달 수익률순' },
  { key: 'returns_3m', label: '3달 수익률순' },
] as const
type SortKey = (typeof SORTS)[number]['key']

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
  // 상세에서 돌아와도 검색·필터가 남도록 URL에 둔다
  const [searchParams, setSearchParams] = useSearchParams()
  const query = searchParams.get('q') ?? ''
  const owner = searchParams.get('owner') ?? ''  // '' 전체, 'me' 나, 그 외 공유자 id
  const accountType = searchParams.get('type') ?? ''  // '' 전체
  const sortParam = searchParams.get('sort')
  const sort: SortKey = SORTS.some((s) => s.key === sortParam) ? (sortParam as SortKey) : 'latest'

  const setParam = (key: string, value: string) => {
    setSearchParams((prev) => {
      const next = new URLSearchParams(prev)
      if (value) next.set(key, value)
      else next.delete(key)
      return next
    }, { replace: true })
  }

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

  // 공유자 목록: 나를 빼고 공유한 개수가 많은 순
  const owners = useMemo(() => {
    const map = new Map<number, { id: number; name: string; count: number }>()
    portfolios.filter((p) => !p.is_owner).forEach((p) => {
      const o = map.get(p.owner_id) ?? { id: p.owner_id, name: p.owner_name, count: 0 }
      o.count += 1
      map.set(p.owner_id, o)
    })
    return [...map.values()].sort((a, b) => b.count - a.count || a.name.localeCompare(b.name, 'ko'))
  }, [portfolios])
  const myCount = portfolios.filter((p) => p.is_owner).length

  const visible = useMemo(() => {
    const q = query.trim().toLowerCase()
    const filtered = portfolios.filter((p) => {
      if (owner === 'me' ? !p.is_owner : owner && String(p.owner_id) !== owner) return false
      if (accountType && !p.account_types.includes(accountType as AccountType)) return false
      if (!q) return true
      return p.portfolio_name.toLowerCase().includes(q)
    })
    if (sort === 'latest') return filtered  // 서버가 최신순으로 준다
    if (sort === 'oldest') return [...filtered].reverse()
    // 수익률이 없는 것은 뒤로 보낸다
    const value = (p: SharedPortfolioListItem) => returnsMap[p.share_token]?.[sort] ?? -Infinity
    return [...filtered].sort((a, b) => value(b) - value(a))
  }, [portfolios, query, owner, accountType, sort, returnsMap])

  const filtering = query !== '' || owner !== '' || accountType !== ''

  return (
    <div className="space-y-6">
      <h1 className="text-2xl font-bold">공유 포트폴리오</h1>
      {loading ? (
        <div className="text-center py-12 text-muted-foreground">로딩 중...</div>
      ) : portfolios.length === 0 ? (
        <Card>
          <CardContent className="py-12 text-center text-muted-foreground">
            <Users className="w-12 h-12 mx-auto mb-4 opacity-50" />
            <p>공유된 포트폴리오가 없습니다</p>
          </CardContent>
        </Card>
      ) : (
      <>
      <div className="flex flex-wrap items-center gap-2">
        <div className="relative flex-1 min-w-[200px] max-w-sm">
          <Search className="absolute left-2.5 top-1/2 -translate-y-1/2 w-4 h-4 text-muted-foreground" />
          <Input
            className="pl-8"
            placeholder="제목 검색"
            value={query}
            onChange={(e) => setParam('q', e.target.value)}
          />
        </div>
        <select
          aria-label="공유자"
          className="h-9 rounded-md border border-input bg-background px-2 text-sm"
          value={owner}
          onChange={(e) => setParam('owner', e.target.value)}
        >
          <option value="">전체 공유자</option>
          {myCount > 0 && <option value="me">내가 공유한 것 ({myCount})</option>}
          {owners.map((o) => (
            <option key={o.id} value={String(o.id)}>{o.name} ({o.count})</option>
          ))}
        </select>
        <select
          aria-label="계좌 유형"
          className="h-9 rounded-md border border-input bg-background px-2 text-sm"
          value={accountType}
          onChange={(e) => setParam('type', e.target.value)}
        >
          <option value="">전체 계좌</option>
          {ACCOUNT_TYPES.map((t) => (
            <option key={t.value} value={t.value}>{t.label}</option>
          ))}
        </select>
        <select
          aria-label="정렬"
          className="h-9 rounded-md border border-input bg-background px-2 text-sm"
          value={sort}
          onChange={(e) => setParam('sort', e.target.value === 'latest' ? '' : e.target.value)}
        >
          {SORTS.map((s) => (
            <option key={s.key} value={s.key}>{s.label}</option>
          ))}
        </select>
        {filtering && (
          <Button variant="ghost" size="sm" onClick={() => setSearchParams(sort === 'latest' ? {} : { sort }, { replace: true })}>
            <X className="w-4 h-4 mr-1" />
            초기화
          </Button>
        )}
        <span className="text-sm text-muted-foreground ml-auto">
          {filtering ? `${visible.length} / ${portfolios.length}개` : `${portfolios.length}개`}
        </span>
      </div>
      {visible.length === 0 ? (
        <Card>
          <CardContent className="py-12 text-center text-muted-foreground">
            조건에 맞는 공유 포트폴리오가 없습니다
          </CardContent>
        </Card>
      ) : (
      <div className="grid gap-4 md:grid-cols-2 lg:grid-cols-3">
        {visible.map((p) => {
          const r = returnsMap[p.share_token]
          return (
            <Card
              key={p.share_token}
              className="cursor-pointer hover:shadow-md transition-shadow flex flex-col"
              onClick={() => navigate(`/shared/${p.share_token}`)}
            >
              <CardHeader className="pb-2">
                <div className="flex items-start gap-2">
                  <CardTitle className="text-lg flex-1 break-words">{p.portfolio_name}</CardTitle>
                  {p.is_owner && <Badge variant="secondary" className="shrink-0">내 공유</Badge>}
                </div>
                <AccountTypeBadges types={p.account_types} />
                <p className="text-xs text-muted-foreground">
                  <button
                    type="button"
                    className="font-medium text-foreground hover:underline"
                    title={`${p.owner_name}님이 공유한 것만 보기`}
                    onClick={(e) => {
                      e.stopPropagation()
                      setParam('owner', p.is_owner ? 'me' : String(p.owner_id))
                    }}
                  >
                    {p.owner_name}
                  </button>
                  {p.shared_at && <> · {formatDateTime(p.shared_at)}</>}
                </p>
              </CardHeader>
              <CardContent className="flex-1 flex flex-col">
                <p className="text-sm text-muted-foreground flex-1">종목 {p.tickers_count}개</p>
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
      )}
      </>
      )}
    </div>
  )
}
