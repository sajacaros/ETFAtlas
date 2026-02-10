import { useState, useEffect } from 'react'
import { Link } from 'react-router-dom'
import { Search, ChevronDown, ChevronRight } from 'lucide-react'
import { Input } from '@/components/ui/input'
import { Card, CardContent } from '@/components/ui/card'
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs'
import { Badge } from '@/components/ui/badge'
import { etfsApi, stocksApi, tagsApi } from '@/lib/api'
import type { ETF, Stock, ETFByStock, Tag, TagETF, TagHolding } from '@/types/api'

export default function HomePage() {
  const [searchQuery, setSearchQuery] = useState('')
  const [activeTab, setActiveTab] = useState('etf')
  const [etfResults, setEtfResults] = useState<ETF[]>([])
  const [stockResults, setStockResults] = useState<Stock[]>([])
  const [etfsByStock, setEtfsByStock] = useState<ETFByStock[]>([])
  const [selectedStock, setSelectedStock] = useState<Stock | null>(null)
  const [loading, setLoading] = useState(false)

  // Tag tab state
  const [tags, setTags] = useState<Tag[]>([])
  const [selectedTag, setSelectedTag] = useState<string | null>(null)
  const [tagETFs, setTagETFs] = useState<TagETF[]>([])
  const [expandedETF, setExpandedETF] = useState<string | null>(null)
  const [holdings, setHoldings] = useState<Record<string, TagHolding[]>>({})
  const [tagLoading, setTagLoading] = useState(false)

  useEffect(() => {
    if (activeTab === 'tag' && tags.length === 0) {
      tagsApi.getAll().then(setTags).catch(console.error)
    }
  }, [activeTab, tags.length])

  const handleSearch = async () => {
    if (!searchQuery.trim()) return
    setLoading(true)
    try {
      if (activeTab === 'etf') {
        const results = await etfsApi.search(searchQuery)
        setEtfResults(results)
      } else {
        const results = await stocksApi.search(searchQuery)
        setStockResults(results)
        setSelectedStock(null)
        setEtfsByStock([])
      }
    } catch (error) {
      console.error('Search failed:', error)
    } finally {
      setLoading(false)
    }
  }

  const handleStockClick = async (stock: Stock) => {
    setSelectedStock(stock)
    setLoading(true)
    try {
      const etfs = await stocksApi.getETFsByStock(stock.code)
      setEtfsByStock(etfs)
    } catch (error) {
      console.error('Failed to fetch ETFs:', error)
    } finally {
      setLoading(false)
    }
  }

  const handleTagClick = async (tagName: string) => {
    if (selectedTag === tagName) return
    setSelectedTag(tagName)
    setExpandedETF(null)
    setTagLoading(true)
    try {
      const etfs = await tagsApi.getETFs(tagName)
      setTagETFs(etfs)
    } catch (error) {
      console.error('Failed to fetch tag ETFs:', error)
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
    if (!holdings[etfCode] && selectedTag) {
      try {
        const h = await tagsApi.getHoldings(selectedTag, etfCode)
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

  return (
    <div className="space-y-6">
      <div className="text-center space-y-4">
        <h1 className="text-4xl font-bold">ETF Atlas</h1>
        <p className="text-muted-foreground text-lg">
          ETF와 종목을 검색하고 분석하세요
        </p>
      </div>

      {activeTab !== 'tag' && (
        <div className="max-w-2xl mx-auto">
          <div className="relative">
            <Search className="absolute left-3 top-1/2 transform -translate-y-1/2 text-muted-foreground w-5 h-5" />
            <Input
              placeholder="ETF 또는 종목명을 검색하세요..."
              value={searchQuery}
              onChange={(e) => setSearchQuery(e.target.value)}
              onKeyDown={handleKeyDown}
              className="pl-10 h-12 text-lg"
            />
          </div>
        </div>
      )}

      <Tabs value={activeTab} onValueChange={setActiveTab} className="max-w-4xl mx-auto">
        <TabsList className="grid w-full grid-cols-3">
          <TabsTrigger value="etf">ETF 검색</TabsTrigger>
          <TabsTrigger value="stock">종목 검색</TabsTrigger>
          <TabsTrigger value="tag">태그 분류</TabsTrigger>
        </TabsList>

        <TabsContent value="etf" className="mt-6">
          {loading ? (
            <div className="text-center py-12 text-muted-foreground">검색 중...</div>
          ) : etfResults.length > 0 ? (
            <div className="grid gap-4">
              {etfResults.map((etf) => (
                <Link key={etf.code} to={`/etf/${etf.code}`}>
                  <Card className="hover:border-primary transition-colors cursor-pointer">
                    <CardContent className="p-4">
                      <div className="flex items-center justify-between">
                        <div>
                          <div className="font-medium">{etf.name}</div>
                          <div className="text-sm text-muted-foreground">{etf.code}</div>
                        </div>
                        <div className="text-right">
                          {etf.category && (
                            <Badge variant="secondary">{etf.category}</Badge>
                          )}
                          {etf.issuer && (
                            <div className="text-sm text-muted-foreground mt-1">
                              {etf.issuer}
                            </div>
                          )}
                        </div>
                      </div>
                    </CardContent>
                  </Card>
                </Link>
              ))}
            </div>
          ) : (
            <div className="text-center py-12 text-muted-foreground">
              검색어를 입력하고 Enter를 눌러 검색하세요
            </div>
          )}
        </TabsContent>

        <TabsContent value="stock" className="mt-6">
          {loading ? (
            <div className="text-center py-12 text-muted-foreground">검색 중...</div>
          ) : (
            <div className="grid md:grid-cols-2 gap-6">
              <div>
                <h3 className="font-medium mb-4">종목 검색 결과</h3>
                {stockResults.length > 0 ? (
                  <div className="space-y-2">
                    {stockResults.map((stock) => (
                      <Card
                        key={stock.code}
                        className={`cursor-pointer hover:border-primary transition-colors ${
                          selectedStock?.code === stock.code ? 'border-primary' : ''
                        }`}
                        onClick={() => handleStockClick(stock)}
                      >
                        <CardContent className="p-3">
                          <div className="font-medium">{stock.name}</div>
                          <div className="text-sm text-muted-foreground">
                            {stock.code} {stock.sector && `· ${stock.sector}`}
                          </div>
                        </CardContent>
                      </Card>
                    ))}
                  </div>
                ) : (
                  <div className="text-center py-8 text-muted-foreground">
                    종목을 검색하세요
                  </div>
                )}
              </div>

              <div>
                <h3 className="font-medium mb-4">
                  {selectedStock
                    ? `${selectedStock.name}을(를) 담고 있는 ETF`
                    : '종목을 선택하세요'}
                </h3>
                {etfsByStock.length > 0 ? (
                  <div className="space-y-2">
                    {etfsByStock.map((etf) => (
                      <Link key={etf.etf_code} to={`/etf/${etf.etf_code}`}>
                        <Card className="hover:border-primary transition-colors cursor-pointer">
                          <CardContent className="p-3">
                            <div className="flex justify-between items-center">
                              <div>
                                <div className="font-medium">{etf.etf_name}</div>
                                <div className="text-sm text-muted-foreground">
                                  {etf.etf_code}
                                </div>
                              </div>
                              <Badge variant="outline">
                                {etf.weight.toFixed(2)}%
                              </Badge>
                            </div>
                          </CardContent>
                        </Card>
                      </Link>
                    ))}
                  </div>
                ) : selectedStock ? (
                  <div className="text-center py-8 text-muted-foreground">
                    ETF가 없습니다
                  </div>
                ) : null}
              </div>
            </div>
          )}
        </TabsContent>

        <TabsContent value="tag" className="mt-6">
          {/* Tag badge chips */}
          <div className="flex flex-wrap gap-2 mb-6">
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
            {tags.length === 0 && (
              <div className="text-center py-8 text-muted-foreground w-full">
                태그를 불러오는 중...
              </div>
            )}
          </div>

          {/* ETF list for selected tag */}
          {selectedTag && (
            <div>
              {tagLoading ? (
                <div className="text-center py-8 text-muted-foreground">불러오는 중...</div>
              ) : tagETFs.length > 0 ? (
                <div className="space-y-2">
                  {tagETFs.map((etf) => (
                    <Card key={etf.code}>
                      <CardContent className="p-0">
                        <div
                          className="flex items-center justify-between p-4 cursor-pointer hover:bg-muted/50 transition-colors"
                          onClick={() => handleETFExpand(etf.code)}
                        >
                          <div className="flex items-center gap-2">
                            {expandedETF === etf.code ? (
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
                              {etf.net_assets >= 1_0000_0000
                                ? `${(etf.net_assets / 1_0000_0000).toFixed(0)}억원`
                                : `${(etf.net_assets / 1_0000).toFixed(0)}만원`}
                            </span>
                          )}
                        </div>
                        {/* Holdings accordion */}
                        {expandedETF === etf.code && (
                          <div className="border-t px-4 py-3 bg-muted/30">
                            {holdings[etf.code] ? (
                              holdings[etf.code].length > 0 ? (
                                <div className="space-y-2">
                                  {holdings[etf.code].map((h) => (
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
                  ))}
                </div>
              ) : (
                <div className="text-center py-8 text-muted-foreground">
                  해당 태그에 속한 ETF가 없습니다
                </div>
              )}
            </div>
          )}
        </TabsContent>
      </Tabs>
    </div>
  )
}
