import { useEffect, useState, useRef } from 'react'
import { Link } from 'react-router-dom'
import { Star, Search } from 'lucide-react'
import { Card, CardContent } from '@/components/ui/card'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Badge } from '@/components/ui/badge'
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from '@/components/ui/table'
import { etfsApi, watchlistApi } from '@/lib/api'
import { useAuth } from '@/hooks/useAuth'
import { useToast } from '@/hooks/use-toast'
import type { WatchlistItem } from '@/types/api'

export default function WatchlistPage() {
  const { isAuthenticated } = useAuth()
  const { toast } = useToast()

  const [items, setItems] = useState<WatchlistItem[]>([])
  const [watchedCodes, setWatchedCodes] = useState<Set<string>>(new Set())
  const [loading, setLoading] = useState(true)

  // Search state
  const [searchQuery, setSearchQuery] = useState('')
  const [searchResults, setSearchResults] = useState<{ code: string; name: string }[]>([])
  const [searching, setSearching] = useState(false)
  const searchTimeout = useRef<ReturnType<typeof setTimeout>>()

  useEffect(() => {
    if (!isAuthenticated) return

    const fetchData = async () => {
      try {
        const [itemsData, codesData] = await Promise.all([
          watchlistApi.getAll(),
          watchlistApi.getCodes(),
        ])
        setItems(itemsData)
        setWatchedCodes(new Set(codesData))
      } catch (error) {
        console.error('Failed to fetch watchlist:', error)
      } finally {
        setLoading(false)
      }
    }

    fetchData()
  }, [isAuthenticated])

  // Debounced search
  useEffect(() => {
    if (!searchQuery.trim()) {
      setSearchResults([])
      return
    }

    clearTimeout(searchTimeout.current)
    searchTimeout.current = setTimeout(async () => {
      setSearching(true)
      try {
        const results = await etfsApi.searchUniverse(searchQuery, 10)
        setSearchResults(results)
      } catch {
        setSearchResults([])
      } finally {
        setSearching(false)
      }
    }, 300)

    return () => clearTimeout(searchTimeout.current)
  }, [searchQuery])

  const handleAdd = async (etfCode: string) => {
    try {
      const added = await watchlistApi.add(etfCode)
      setItems((prev) => [added, ...prev])
      setWatchedCodes((prev) => new Set(prev).add(etfCode))
      toast({ title: '즐겨찾기에 추가되었습니다' })
    } catch {
      toast({ title: '추가 실패', variant: 'destructive' })
    }
  }

  const handleRemove = async (etfCode: string) => {
    try {
      await watchlistApi.remove(etfCode)
      setItems((prev) => prev.filter((item) => item.etf_code !== etfCode))
      setWatchedCodes((prev) => {
        const next = new Set(prev)
        next.delete(etfCode)
        return next
      })
      toast({ title: '즐겨찾기에서 해제되었습니다' })
    } catch {
      toast({ title: '해제 실패', variant: 'destructive' })
    }
  }

  if (!isAuthenticated) {
    return (
      <div className="text-center py-12">
        <h2 className="text-2xl font-bold mb-4">로그인이 필요합니다</h2>
        <p className="text-muted-foreground mb-6">
          즐겨찾기 기능을 사용하려면 로그인해주세요
        </p>
        <Link to="/login">
          <Button>로그인하기</Button>
        </Link>
      </div>
    )
  }

  if (loading) {
    return <div className="text-center py-12">로딩 중...</div>
  }

  return (
    <div className="space-y-6">
      <h1 className="text-3xl font-bold">즐겨찾기</h1>

      {/* Search */}
      <div className="relative">
        <div className="relative">
          <Search className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-muted-foreground" />
          <Input
            placeholder="ETF 이름 또는 코드로 검색하여 추가..."
            value={searchQuery}
            onChange={(e) => setSearchQuery(e.target.value)}
            className="pl-10"
          />
        </div>
        {searchQuery.trim() && (
          <Card className="absolute z-10 w-full mt-1 max-h-64 overflow-auto">
            <CardContent className="p-2">
              {searching ? (
                <p className="text-sm text-muted-foreground text-center py-2">검색 중...</p>
              ) : searchResults.length === 0 ? (
                <p className="text-sm text-muted-foreground text-center py-2">검색 결과 없음</p>
              ) : (
                searchResults.map((result) => {
                  const isWatched = watchedCodes.has(result.code)
                  return (
                    <div
                      key={result.code}
                      className="flex items-center justify-between px-3 py-2 rounded hover:bg-muted"
                    >
                      <Link to={`/etf/${result.code}`} className="flex-1 min-w-0">
                        <span className="font-medium text-sm">{result.name}</span>
                        <span className="text-xs text-muted-foreground ml-2">{result.code}</span>
                      </Link>
                      <Button
                        variant="ghost"
                        size="icon"
                        className="shrink-0 h-8 w-8"
                        onClick={() => isWatched ? handleRemove(result.code) : handleAdd(result.code)}
                      >
                        <Star
                          className={`w-4 h-4 ${isWatched ? 'fill-yellow-400 text-yellow-400' : 'text-muted-foreground'}`}
                        />
                      </Button>
                    </div>
                  )
                })
              )}
            </CardContent>
          </Card>
        )}
      </div>

      {/* Watchlist Table */}
      {items.length === 0 ? (
        <Card>
          <CardContent className="py-12 text-center">
            <p className="text-muted-foreground">
              즐겨찾기한 ETF가 없습니다. 위 검색란에서 ETF를 찾아 추가해보세요.
            </p>
          </CardContent>
        </Card>
      ) : (
        <Card>
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>ETF명</TableHead>
                <TableHead>코드</TableHead>
                <TableHead>카테고리</TableHead>
                <TableHead className="w-12"></TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {items.map((item) => (
                <TableRow key={item.etf_code}>
                  <TableCell>
                    <Link to={`/etf/${item.etf_code}`} className="text-blue-600 hover:underline font-medium">
                      {item.etf_name}
                    </Link>
                  </TableCell>
                  <TableCell className="text-muted-foreground">{item.etf_code}</TableCell>
                  <TableCell>
                    {item.category ? (
                      <Badge variant="secondary" className="text-xs">{item.category}</Badge>
                    ) : (
                      '-'
                    )}
                  </TableCell>
                  <TableCell>
                    <Button
                      variant="ghost"
                      size="icon"
                      className="h-8 w-8"
                      onClick={() => handleRemove(item.etf_code)}
                      title="즐겨찾기 해제"
                    >
                      <Star className="w-4 h-4 fill-yellow-400 text-yellow-400" />
                    </Button>
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
