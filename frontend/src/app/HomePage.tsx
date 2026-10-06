import { useEffect, useRef, useState, useCallback } from 'react'
import { Link, useSearchParams } from 'react-router-dom'
import { Search, ChevronDown, ChevronRight, Star } from 'lucide-react'
import { Input } from '@/components/ui/input'
import { Card, CardContent } from '@/components/ui/card'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { etfsApi, tagsApi, watchlistApi } from '@/lib/api'
import { useAuth } from '@/hooks/useAuth'
import { useToast } from '@/hooks/use-toast'
import { formatKrwAmount } from '@/lib/utils'
import type { Tag, Holding } from '@/types/api'

interface ETFCardItem {
  code: string
  name: string
  net_assets?: number | null
  return_1d?: number | null
  return_1w?: number | null
  return_1m?: number | null
  market_cap_change_1w?: number | null
}

const PAGE_SIZE = 20
type PageFetcher = (offset: number) => Promise<ETFCardItem[]>

const formatAmount = (value: number) => formatKrwAmount(value, '')

const returnColor = (value: number | null | undefined) =>
  value == null || value === 0 ? 'text-muted-foreground' : value > 0 ? 'text-red-500' : 'text-blue-500'

const formatReturn = (value: number | null | undefined) =>
  value == null ? '-' : value > 0 ? `+${value.toFixed(1)}%` : `${value.toFixed(1)}%`

function ReturnBadge({ label, value, className = '' }: { label: string; value: number | null | undefined; className?: string }) {
  return (
    <div className={`text-right w-20 ${className}`}>
      <div className="text-[10px] text-muted-foreground leading-none mb-0.5">{label}</div>
      <div className={`text-base font-medium whitespace-nowrap ${returnColor(value)}`}>{formatReturn(value)}</div>
    </div>
  )
}

function ETFExpandableCard({
  etf,
  expanded,
  onToggle,
  holdings,
  isWatched,
  onWatchToggle,
}: {
  etf: ETFCardItem
  expanded: boolean
  onToggle: () => void
  holdings: Holding[] | undefined
  isWatched: boolean
  onWatchToggle: ((code: string) => void) | null
}) {
  return (
    <Card>
      <CardContent className="p-0">
        <div
          className="flex items-center gap-2 sm:gap-3 p-3 sm:p-4 cursor-pointer hover:bg-muted/50 transition-colors"
          onClick={onToggle}
        >
          {expanded ? (
            <ChevronDown className="w-4 h-4 text-muted-foreground flex-shrink-0" />
          ) : (
            <ChevronRight className="w-4 h-4 text-muted-foreground flex-shrink-0" />
          )}
          <div className="min-w-0 flex-1">
            <Link
              to={`/etf/${etf.code}`}
              className="font-medium hover:underline truncate block"
              onClick={(e) => e.stopPropagation()}
            >
              {etf.name}
            </Link>
            <div className="flex items-center justify-between gap-3 text-sm text-muted-foreground">
              {etf.code}
              {/* 모바일: 이름은 첫 줄 전체를 쓰고 1D·시총은 코드 옆 둘째 줄에 */}
              <div className="flex items-baseline gap-3 whitespace-nowrap sm:hidden">
                <span>
                  <span className="mr-1 text-[10px]">1D</span>
                  <span className={`font-medium ${returnColor(etf.return_1d)}`}>{formatReturn(etf.return_1d)}</span>
                </span>
                <span>{etf.net_assets != null ? formatAmount(etf.net_assets) : '-'}</span>
              </div>
            </div>
          </div>
          {/* 넓을수록 열을 더 보여 준다: sm 1D·시총, md 1W·1M, xl 시총변화 */}
          <div className="hidden sm:flex items-center gap-5 flex-shrink-0">
            <ReturnBadge label="1D" value={etf.return_1d} />
            <ReturnBadge label="1W" value={etf.return_1w} className="hidden md:block" />
            <ReturnBadge label="1M" value={etf.return_1m} className="hidden md:block" />
            <div className="hidden text-right w-32 xl:block">
              <div className="text-[10px] text-muted-foreground leading-none mb-0.5">시총변화(1W)</div>
              {etf.net_assets != null && etf.market_cap_change_1w != null ? (
                <div className={`text-base font-medium whitespace-nowrap ${returnColor(etf.market_cap_change_1w)}`}>
                  {etf.market_cap_change_1w > 0 ? '+' : ''}{formatAmount(Math.round(etf.net_assets * etf.market_cap_change_1w / 100))}({etf.market_cap_change_1w > 0 ? '+' : ''}{etf.market_cap_change_1w.toFixed(1)}%)
                </div>
              ) : (
                <div className="text-base text-muted-foreground">-</div>
              )}
            </div>
            <div className="text-right w-24">
              <div className="text-[10px] text-muted-foreground leading-none mb-0.5">시총</div>
              <div className="text-base text-muted-foreground whitespace-nowrap">{etf.net_assets != null ? formatAmount(etf.net_assets) : '-'}</div>
            </div>
          </div>
          {onWatchToggle && (
            <Button
              variant="ghost"
              size="icon"
              className="shrink-0 h-8 w-8"
              onClick={(e) => {
                e.stopPropagation()
                onWatchToggle(etf.code)
              }}
            >
              <Star
                className={`w-4 h-4 ${isWatched ? 'fill-yellow-400 text-yellow-400' : 'text-muted-foreground'}`}
              />
            </Button>
          )}
        </div>
        {expanded && (
          <div className="border-t px-4 py-3 bg-muted/30">
            {holdings ? (
              holdings.length > 0 ? (
                <div className="space-y-2">
                  {holdings.map((h) => (
                    <div
                      key={h.stock_code}
                      className="flex justify-between items-center text-sm"
                    >
                      <span>{h.stock_name} <span className="text-muted-foreground">({h.stock_code})</span></span>
                      <span className="font-medium">{h.weight.toFixed(2)}%</span>
                    </div>
                  ))}
                </div>
              ) : (
                <div className="text-sm text-muted-foreground">보유종목 정보가 없습니다</div>
              )
            ) : (
              <div className="text-sm text-muted-foreground">불러오는 중...</div>
            )}
          </div>
        )}
      </CardContent>
    </Card>
  )
}

export default function HomePage() {
  const { isAuthenticated } = useAuth()
  const { toast } = useToast()
  const [searchParams, setSearchParams] = useSearchParams()
  const [searchQuery, setSearchQuery] = useState(searchParams.get('q') || '')
  const [loading, setLoading] = useState(false)
  const [watchedCodes, setWatchedCodes] = useState<Set<string>>(new Set())
  const [latestDate, setLatestDate] = useState<string | null>(null)

  // ETF list (shared between search and tag)
  const [etfList, setEtfList] = useState<ETFCardItem[]>([])

  // Tag state
  const [tags, setTags] = useState<Tag[]>([])
  const [selectedTag, setSelectedTag] = useState<string | null>(searchParams.get('tag') || '시총')
  const [tagsExpanded, setTagsExpanded] = useState(false)
  const [tagsOverflow, setTagsOverflow] = useState(false)
  const tagsRef = useRef<HTMLDivElement>(null)

  // Shared expand/holdings state
  const [expandedETF, setExpandedETF] = useState<string | null>(null)
  const [holdings, setHoldings] = useState<Record<string, Holding[]>>({})

  const FAVORITES_TAG = '즐겨찾기'
  const SORT_TAGS: Record<string, string> = {
    '시총': 'market_cap',
    '시총상승률': 'market_cap_change_1w',
    '1D수익률': 'return_1d',
    '1주수익률': 'return_1w',
  }
  const isSortTag = (tagName: string) => tagName in SORT_TAGS

  // 무한 스크롤: 검색·정렬 탭은 PAGE_SIZE씩 이어 받고, 분류 태그·즐겨찾기는 한 번에 전체를 받는다
  const [hasMore, setHasMore] = useState(false)
  const [loadingMore, setLoadingMore] = useState(false)
  const pageFetcherRef = useRef<PageFetcher | null>(null)
  const offsetRef = useRef(0)
  const listRequestRef = useRef(0)
  const loadingMoreRef = useRef(false)
  const sentinelRef = useRef<HTMLDivElement>(null)

  const loadList = useCallback(async (fetcher: PageFetcher, paged: boolean) => {
    // 응답이 늦게 온 이전 요청이 새 목록을 덮어쓰지 않도록 요청 번호로 거른다
    const requestId = ++listRequestRef.current
    pageFetcherRef.current = paged ? fetcher : null
    offsetRef.current = 0
    setHasMore(false)
    setLoading(true)
    try {
      const items = await fetcher(0)
      if (requestId !== listRequestRef.current) return
      setEtfList(items)
      offsetRef.current = items.length
      setHasMore(paged && items.length === PAGE_SIZE)
    } catch {
      if (requestId !== listRequestRef.current) return
      setEtfList([])
    } finally {
      if (requestId === listRequestRef.current) setLoading(false)
    }
  }, [])

  const loadMore = useCallback(async () => {
    const fetcher = pageFetcherRef.current
    if (!fetcher || loadingMoreRef.current) return
    const requestId = listRequestRef.current
    loadingMoreRef.current = true
    setLoadingMore(true)
    try {
      const items = await fetcher(offsetRef.current)
      if (requestId !== listRequestRef.current) return
      offsetRef.current += items.length
      setEtfList((prev) => {
        const seen = new Set(prev.map((e) => e.code))
        return [...prev, ...items.filter((e) => !seen.has(e.code))]
      })
      setHasMore(items.length === PAGE_SIZE)
    } catch {
      if (requestId === listRequestRef.current) setHasMore(false)
    } finally {
      loadingMoreRef.current = false
      setLoadingMore(false)
    }
  }, [])

  // 목록 끝의 sentinel이 보이면 다음 페이지를 불러온다.
  // loadingMore가 바뀔 때마다 다시 관찰해서, 한 페이지를 붙인 뒤에도 sentinel이 화면 안에 있으면 이어서 불러온다.
  useEffect(() => {
    const el = sentinelRef.current
    if (!el || !hasMore || loading || loadingMore) return
    const observer = new IntersectionObserver((entries) => {
      if (entries[0].isIntersecting) loadMore()
    }, { rootMargin: '200px' })
    observer.observe(el)
    return () => observer.disconnect()
  }, [hasMore, loading, loadingMore, loadMore])

  const loadSearch = (query: string) =>
    loadList((offset) => etfsApi.searchUniverse(query, PAGE_SIZE, offset), true)

  const loadTag = (tagName: string) => {
    if (tagName === FAVORITES_TAG) return loadList(() => watchlistApi.getETFs(), false)
    if (isSortTag(tagName)) return loadList((offset) => etfsApi.getTop(PAGE_SIZE, SORT_TAGS[tagName], offset), true)
    return loadList(() => tagsApi.getETFs(tagName), false)
  }

  // Restore state from URL params on mount, or load top ETFs by default
  const restoredRef = useRef(false)
  useEffect(() => {
    if (restoredRef.current) return
    restoredRef.current = true
    const q = searchParams.get('q')
    const tag = searchParams.get('tag')
    if (q) {
      loadSearch(q.trim())
    } else if (tag) {
      loadTag(tag)
    } else {
      // 기본: 시가총액순 (시총 태그 선택 상태)
      setSelectedTag('시총')
      loadTag('시총')
    }
  }, [searchParams])

  useEffect(() => {
    if (!isAuthenticated) return
    watchlistApi.getCodes().then((codes) => setWatchedCodes(new Set(codes))).catch(console.error)
  }, [isAuthenticated])

  useEffect(() => {
    tagsApi.getAll().then(setTags).catch(console.error)
    etfsApi.getLatestDate().then(setLatestDate).catch(console.error)
  }, [])

  useEffect(() => {
    if (tagsRef.current) {
      setTagsOverflow(tagsRef.current.scrollHeight > tagsRef.current.clientHeight)
    }
  }, [tags])

  const updateParams = useCallback((q: string | null, tag: string | null) => {
    const params = new URLSearchParams()
    if (q) params.set('q', q)
    if (tag) params.set('tag', tag)
    setSearchParams(params, { replace: true })
  }, [setSearchParams])

  const handleSearch = async () => {
    const query = searchQuery.trim()
    if (!query) return
    setSearchQuery(query)
    setSelectedTag(null)
    setExpandedETF(null)
    updateParams(query, null)
    await loadSearch(query)
  }

  const handleTagClick = async (tagName: string) => {
    if (selectedTag === tagName) {
      // 태그 해제 → 시가총액 TOP으로 복귀
      setSelectedTag('시총')
      setExpandedETF(null)
      setSearchQuery('')
      updateParams(null, null)
      await loadTag('시총')
      return
    }
    setSelectedTag(tagName)
    setExpandedETF(null)
    setSearchQuery('')
    updateParams(null, tagName)
    await loadTag(tagName)
  }

  const handleETFExpand = async (etfCode: string) => {
    if (expandedETF === etfCode) {
      setExpandedETF(null)
      return
    }
    setExpandedETF(etfCode)
    if (!holdings[etfCode]) {
      try {
        const h = await etfsApi.getHoldings(etfCode)
        setHoldings((prev) => ({ ...prev, [etfCode]: h }))
      } catch (error) {
        console.error('Failed to fetch holdings:', error)
      }
    }
  }

  const handleWatchToggle = async (etfCode: string) => {
    if (!isAuthenticated) {
      toast({ title: '로그인이 필요합니다', variant: 'destructive' })
      return
    }
    const isWatched = watchedCodes.has(etfCode)
    try {
      if (isWatched) {
        await watchlistApi.remove(etfCode)
        setWatchedCodes((prev) => {
          const next = new Set(prev)
          next.delete(etfCode)
          return next
        })
        // 즐겨찾기 태그 보는 중이면 목록에서 제거
        if (selectedTag === FAVORITES_TAG) {
          setEtfList((prev) => prev.filter((e) => e.code !== etfCode))
        }
        toast({ title: '즐겨찾기에서 해제되었습니다' })
      } else {
        await watchlistApi.add(etfCode)
        setWatchedCodes((prev) => new Set(prev).add(etfCode))
        toast({ title: '즐겨찾기에 추가되었습니다' })
      }
    } catch {
      toast({ title: isWatched ? '해제 실패' : '추가 실패', variant: 'destructive' })
    }
  }

  const handleKeyDown = (e: React.KeyboardEvent) => {
    if (e.key === 'Enter') {
      handleSearch()
    }
  }

  return (
    <div className="space-y-4">
      <div className="mx-auto">
        {/* 정렬 버튼 그룹 + 검색 */}
        <div className="flex flex-col gap-3 sm:flex-row sm:items-center">
          <div className="no-scrollbar flex items-center gap-1 overflow-x-auto rounded-lg border p-1 sm:shrink-0">
            {Object.keys(SORT_TAGS).map((name) => (
              <button
                key={name}
                className={`shrink-0 whitespace-nowrap px-3 py-1.5 text-sm rounded-md transition-colors ${
                  selectedTag === name
                    ? 'bg-primary text-primary-foreground font-medium'
                    : 'text-muted-foreground hover:text-foreground hover:bg-muted'
                }`}
                onClick={() => handleTagClick(name)}
              >
                {name}
              </button>
            ))}
            {isAuthenticated && (
              <button
                className={`shrink-0 whitespace-nowrap px-3 py-1.5 text-sm rounded-md transition-colors flex items-center gap-1 ${
                  selectedTag === FAVORITES_TAG
                    ? 'bg-primary text-primary-foreground font-medium'
                    : 'text-muted-foreground hover:text-foreground hover:bg-muted'
                }`}
                onClick={() => handleTagClick(FAVORITES_TAG)}
              >
                <Star className={`w-3 h-3 ${selectedTag === FAVORITES_TAG ? 'fill-current' : ''}`} />
                {FAVORITES_TAG}({watchedCodes.size})
              </button>
            )}
          </div>
          <div className="relative flex-1">
            <Search className="absolute left-3 top-1/2 transform -translate-y-1/2 text-muted-foreground w-4 h-4" />
            <Input
              placeholder="ETF 검색..."
              value={searchQuery}
              onChange={(e) => setSearchQuery(e.target.value)}
              onKeyDown={handleKeyDown}
              className="pl-9 h-9"
            />
          </div>
        </div>
      </div>

      <div className="mx-auto space-y-4">

        {/* 분류 태그 */}
        <div>
          <div className="relative">
            <div
              ref={tagsRef}
              className={`flex flex-wrap gap-2 ${tagsExpanded ? '' : 'max-h-9 overflow-hidden'}`}
            >
              {tags.map((tag) => (
                <Badge
                  key={tag.name}
                  variant={selectedTag === tag.name ? 'default' : 'outline'}
                  className="cursor-pointer text-sm px-3 py-1"
                  onClick={() => handleTagClick(tag.name)}
                >
                  {tag.name} ({tag.etf_count})
                </Badge>
              ))}
            </div>
            {(tagsOverflow || tagsExpanded) && (
              <button
                className="flex items-center gap-1 text-xs text-muted-foreground mt-1 hover:text-foreground"
                onClick={() => setTagsExpanded(!tagsExpanded)}
              >
                {tagsExpanded ? <ChevronDown className="w-3 h-3" /> : <ChevronRight className="w-3 h-3" />}
                {tagsExpanded ? '접기' : '더보기'}
              </button>
            )}
          </div>
        </div>

        {/* ETF 목록 (검색/태그 공용) */}
        {latestDate && (
          <div className="text-sm text-muted-foreground text-right">
            기준일: {latestDate?.slice(2).replace(/-/g, '/')}
          </div>
        )}
        {loading ? (
          <div className="text-center py-8 text-muted-foreground">불러오는 중...</div>
        ) : etfList.length > 0 ? (
          <div className="space-y-2">
            {etfList.map((etf) => (
              <ETFExpandableCard
                key={etf.code}
                etf={etf}
                expanded={expandedETF === etf.code}
                onToggle={() => handleETFExpand(etf.code)}
                holdings={holdings[etf.code]}
                isWatched={watchedCodes.has(etf.code)}
                onWatchToggle={isAuthenticated ? handleWatchToggle : null}
              />
            ))}
            {hasMore && <div ref={sentinelRef} className="h-px" />}
            {loadingMore && (
              <div className="text-center py-4 text-sm text-muted-foreground">불러오는 중...</div>
            )}
          </div>
        ) : null}
      </div>
    </div>
  )
}
