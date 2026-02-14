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

function formatAmount(value: number): string {
  const abs = Math.abs(value)
  const sign = value < 0 ? '-' : ''
  if (abs >= 1_0000_0000) {
    return `${sign}${Math.floor(abs / 1_0000_0000).toLocaleString()}억원`
  }
  return `${sign}${Math.floor(abs / 1_0000).toLocaleString()}만원`
}

function ReturnBadge({ label, value }: { label: string; value: number | null | undefined }) {
  const hasValue = value != null
  const color = hasValue
    ? value > 0 ? 'text-red-500' : value < 0 ? 'text-blue-500' : 'text-muted-foreground'
    : 'text-muted-foreground'
  const formatted = hasValue
    ? value > 0 ? `+${value.toFixed(1)}%` : `${value.toFixed(1)}%`
    : '-'
  return (
    <div className="text-right w-16">
      <div className="text-[10px] text-muted-foreground leading-none mb-0.5">{label}</div>
      <div className={`text-sm font-medium ${color}`}>{formatted}</div>
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
          className="flex items-center justify-between p-4 cursor-pointer hover:bg-muted/50 transition-colors"
          onClick={onToggle}
        >
          <div className="flex items-center gap-2 min-w-0">
            {expanded ? (
              <ChevronDown className="w-4 h-4 text-muted-foreground flex-shrink-0" />
            ) : (
              <ChevronRight className="w-4 h-4 text-muted-foreground flex-shrink-0" />
            )}
            <div className="min-w-0">
              <Link
                to={`/etf/${etf.code}`}
                className="font-medium hover:underline truncate block"
                onClick={(e) => e.stopPropagation()}
              >
                {etf.name}
              </Link>
              <div className="text-sm text-muted-foreground">{etf.code}</div>
            </div>
          </div>
          <div className="flex items-center gap-5 flex-shrink-0">
            <ReturnBadge label="1D" value={etf.return_1d} />
            <ReturnBadge label="1W" value={etf.return_1w} />
            <ReturnBadge label="1M" value={etf.return_1m} />
            <div className="text-right w-20">
              {etf.net_assets != null && etf.market_cap_change_1w != null ? (
                <>
                  <div className="text-[10px] text-muted-foreground leading-none mb-0.5">시총1W</div>
                  <div className={`text-sm font-medium ${etf.market_cap_change_1w > 0 ? 'text-red-500' : etf.market_cap_change_1w < 0 ? 'text-blue-500' : 'text-muted-foreground'}`}>
                    {etf.market_cap_change_1w > 0 ? '+' : ''}{formatAmount(Math.round(etf.net_assets * etf.market_cap_change_1w / 100))}
                  </div>
                </>
              ) : (
                <>
                  <div className="text-[10px] text-muted-foreground leading-none mb-0.5">시총1W</div>
                  <div className="text-sm text-muted-foreground">-</div>
                </>
              )}
            </div>
            <div className="text-right w-20">
              <div className="text-[10px] text-muted-foreground leading-none mb-0.5">시총</div>
              <div className="text-sm text-muted-foreground">{etf.net_assets != null ? formatAmount(etf.net_assets) : '-'}</div>
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

  // ETF list (shared between search and tag)
  const [etfList, setEtfList] = useState<ETFCardItem[]>([])

  // Tag state
  const [tags, setTags] = useState<Tag[]>([])
  const [selectedTag, setSelectedTag] = useState<string | null>(searchParams.get('tag') || '시총 TOP')
  const [tagLoading, setTagLoading] = useState(false)
  const [tagsExpanded, setTagsExpanded] = useState(false)
  const [tagsOverflow, setTagsOverflow] = useState(false)
  const tagsRef = useRef<HTMLDivElement>(null)

  // Shared expand/holdings state
  const [expandedETF, setExpandedETF] = useState<string | null>(null)
  const [holdings, setHoldings] = useState<Record<string, Holding[]>>({})

  const FAVORITES_TAG = '즐겨찾기'
  const SORT_TAGS: Record<string, string> = {
    '시총 TOP': 'market_cap',
    '시총상승 TOP': 'market_cap_change_1w',
    '1주 수익률 TOP': 'return_1w',
  }
  const isSortTag = (tagName: string) => tagName in SORT_TAGS

  // Restore state from URL params on mount, or load top ETFs by default
  const restoredRef = useRef(false)
  useEffect(() => {
    if (restoredRef.current) return
    restoredRef.current = true
    const q = searchParams.get('q')
    const tag = searchParams.get('tag')
    if (q) {
      setLoading(true)
      etfsApi.searchUniverse(q).then(setEtfList).catch(() => setEtfList([])).finally(() => setLoading(false))
    } else if (tag) {
      setTagLoading(true)
      if (tag === FAVORITES_TAG) {
        watchlistApi.getETFs()
          .then(setEtfList)
          .catch(() => setEtfList([]))
          .finally(() => setTagLoading(false))
      } else if (isSortTag(tag)) {
        etfsApi.getTop(20, SORT_TAGS[tag]).then(setEtfList).catch(() => setEtfList([])).finally(() => setTagLoading(false))
      } else {
        tagsApi.getETFs(tag).then(setEtfList).catch(() => setEtfList([])).finally(() => setTagLoading(false))
      }
    } else {
      // 기본: 시가총액 TOP 20 (시총 TOP 태그 선택 상태)
      setSelectedTag('시총 TOP')
      setLoading(true)
      etfsApi.getTop(20).then(setEtfList).catch(() => setEtfList([])).finally(() => setLoading(false))
    }
  }, [searchParams])

  useEffect(() => {
    if (!isAuthenticated) return
    watchlistApi.getCodes().then((codes) => setWatchedCodes(new Set(codes))).catch(console.error)
  }, [isAuthenticated])

  useEffect(() => {
    tagsApi.getAll().then(setTags).catch(console.error)
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
    if (!searchQuery.trim()) return
    setLoading(true)
    setSelectedTag(null)
    setExpandedETF(null)
    updateParams(searchQuery.trim(), null)
    try {
      const results = await etfsApi.searchUniverse(searchQuery)
      setEtfList(results)
    } catch {
      setEtfList([])
    } finally {
      setLoading(false)
    }
  }

  const handleTagClick = async (tagName: string) => {
    if (selectedTag === tagName) {
      // 태그 해제 → 시가총액 TOP으로 복귀
      setSelectedTag('시총 TOP')
      setExpandedETF(null)
      setSearchQuery('')
      updateParams(null, null)
      setLoading(true)
      try {
        const etfs = await etfsApi.getTop(20)
        setEtfList(etfs)
      } catch {
        setEtfList([])
      } finally {
        setLoading(false)
      }
      return
    }
    setSelectedTag(tagName)
    setExpandedETF(null)
    setSearchQuery('')
    updateParams(null, tagName)
    setTagLoading(true)
    try {
      if (tagName === FAVORITES_TAG) {
        const etfs = await watchlistApi.getETFs()
        setEtfList(etfs)
      } else if (isSortTag(tagName)) {
        const etfs = await etfsApi.getTop(20, SORT_TAGS[tagName])
        setEtfList(etfs)
      } else {
        const etfs = await tagsApi.getETFs(tagName)
        setEtfList(etfs)
      }
    } catch {
      setEtfList([])
    } finally {
      setTagLoading(false)
    }
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

  const isLoading = loading || tagLoading

  return (
    <div className="space-y-6">
      <div className="max-w-2xl mx-auto">
        <div className="relative">
          <Search className="absolute left-3 top-1/2 transform -translate-y-1/2 text-muted-foreground w-5 h-5" />
          <Input
            placeholder="ETF 이름 또는 코드를 검색하세요..."
            value={searchQuery}
            onChange={(e) => setSearchQuery(e.target.value)}
            onKeyDown={handleKeyDown}
            className="pl-10 h-12 text-lg"
          />
        </div>
      </div>

      <div className="max-w-4xl mx-auto space-y-4">
        {/* 정렬 버튼 그룹 */}
        <div className="flex items-center gap-1 rounded-lg border p-1 w-fit">
          {Object.keys(SORT_TAGS).map((name) => (
            <button
              key={name}
              className={`px-3 py-1.5 text-sm rounded-md transition-colors ${
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
              className={`px-3 py-1.5 text-sm rounded-md transition-colors flex items-center gap-1 ${
                selectedTag === FAVORITES_TAG
                  ? 'bg-primary text-primary-foreground font-medium'
                  : 'text-muted-foreground hover:text-foreground hover:bg-muted'
              }`}
              onClick={() => handleTagClick(FAVORITES_TAG)}
            >
              <Star className={`w-3 h-3 ${selectedTag === FAVORITES_TAG ? 'fill-current' : ''}`} />
              {FAVORITES_TAG} ({watchedCodes.size})
            </button>
          )}
        </div>

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
        {isLoading ? (
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
          </div>
        ) : null}
      </div>
    </div>
  )
}
