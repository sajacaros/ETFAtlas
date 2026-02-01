import { useState } from 'react'
import { Link } from 'react-router-dom'
import { Search } from 'lucide-react'
import { Input } from '@/components/ui/input'
import { Card, CardContent } from '@/components/ui/card'
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs'
import { Badge } from '@/components/ui/badge'
import { etfsApi, stocksApi } from '@/lib/api'
import type { ETF, Stock, ETFByStock } from '@/types/api'

export default function HomePage() {
  const [searchQuery, setSearchQuery] = useState('')
  const [activeTab, setActiveTab] = useState('etf')
  const [etfResults, setEtfResults] = useState<ETF[]>([])
  const [stockResults, setStockResults] = useState<Stock[]>([])
  const [etfsByStock, setEtfsByStock] = useState<ETFByStock[]>([])
  const [selectedStock, setSelectedStock] = useState<Stock | null>(null)
  const [loading, setLoading] = useState(false)

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

      <Tabs value={activeTab} onValueChange={setActiveTab} className="max-w-4xl mx-auto">
        <TabsList className="grid w-full grid-cols-2">
          <TabsTrigger value="etf">ETF 검색</TabsTrigger>
          <TabsTrigger value="stock">종목 검색</TabsTrigger>
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
      </Tabs>
    </div>
  )
}
