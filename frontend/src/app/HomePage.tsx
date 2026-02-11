import { useEffect, useRef, useState } from 'react'
import { Link } from 'react-router-dom'
import { Search, ChevronDown, ChevronRight } from 'lucide-react'
import { Input } from '@/components/ui/input'
import { Card, CardContent } from '@/components/ui/card'
import { Badge } from '@/components/ui/badge'
import { etfsApi, tagsApi } from '@/lib/api'
import type { Tag, Holding } from '@/types/api'

interface ETFCardItem {
  code: string
  name: string
  net_assets?: number | null
}

function formatAmount(value: number): string {
  if (value >= 1_0000_0000) {
    return `${Math.floor(value / 1_0000_0000).toLocaleString()}억원`
  }
  return `${Math.floor(value / 1_0000).toLocaleString()}만원`
}

function ETFExpandableCard({
  etf,
  expanded,
  onToggle,
  holdings,
}: {
  etf: ETFCardItem
  expanded: boolean
  onToggle: () => void
  holdings: Holding[] | undefined
}) {
  return (
    <Card>
      <CardContent className="p-0">
        <div
          className="flex items-center justify-between p-4 cursor-pointer hover:bg-muted/50 transition-colors"
          onClick={onToggle}
        >
          <div className="flex items-center gap-2">
            {expanded ? (
              <ChevronDown className="w-4 h-4 text-muted-foreground" />
            ) : (
              <ChevronRight className="w-4 h-4 text-muted-foreground" />
            )}
            <div>
              <Link
                to={`/etf/${etf.code}`}
                className="font-medium hover:underline"
                onClick={(e) => e.stopPropagation()}
              >
                {etf.name}
              </Link>
              <div className="text-sm text-muted-foreground">{etf.code}</div>
            </div>
          </div>
          {etf.net_assets != null && (
            <span className="text-sm text-muted-foreground whitespace-nowrap">
              {formatAmount(etf.net_assets)}
            </span>
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
  const [searchQuery, setSearchQuery] = useState('')
  const [loading, setLoading] = useState(false)

  // ETF list (shared between search and tag)
  const [etfList, setEtfList] = useState<ETFCardItem[]>([])

  // Tag state
  const [tags, setTags] = useState<Tag[]>([])
  const [selectedTag, setSelectedTag] = useState<string | null>(null)
  const [tagLoading, setTagLoading] = useState(false)
  const [tagsExpanded, setTagsExpanded] = useState(false)
  const [tagsOverflow, setTagsOverflow] = useState(false)
  const tagsRef = useRef<HTMLDivElement>(null)

  // Shared expand/holdings state
  const [expandedETF, setExpandedETF] = useState<string | null>(null)
  const [holdings, setHoldings] = useState<Record<string, Holding[]>>({})

  useEffect(() => {
    tagsApi.getAll().then(setTags).catch(console.error)
  }, [])

  useEffect(() => {
    if (tagsRef.current) {
      setTagsOverflow(tagsRef.current.scrollHeight > tagsRef.current.clientHeight)
    }
  }, [tags])

  const handleSearch = async () => {
    if (!searchQuery.trim()) return
    setLoading(true)
    setSelectedTag(null)
    setExpandedETF(null)
    try {
      const results = await etfsApi.search(searchQuery)
      setEtfList(results)
    } catch {
      setEtfList([])
    } finally {
      setLoading(false)
    }
  }

  const handleTagClick = async (tagName: string) => {
    if (selectedTag === tagName) {
      setSelectedTag(null)
      setEtfList([])
      return
    }
    setSelectedTag(tagName)
    setExpandedETF(null)
    setSearchQuery('')
    setTagLoading(true)
    try {
      const etfs = await tagsApi.getETFs(tagName)
      setEtfList(etfs)
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

      <div className="max-w-4xl mx-auto space-y-6">
        {/* 태그 분류 */}
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
              />
            ))}
          </div>
        ) : null}
      </div>
    </div>
  )
}
