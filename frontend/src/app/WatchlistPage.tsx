import { useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import { Plus, Trash2, X } from 'lucide-react'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
  DialogTrigger,
} from '@/components/ui/dialog'
import { Badge } from '@/components/ui/badge'
import { watchlistApi } from '@/lib/api'
import { useAuth } from '@/hooks/useAuth'
import { useToast } from '@/hooks/use-toast'
import type { Watchlist } from '@/types/api'

export default function WatchlistPage() {
  const { isAuthenticated } = useAuth()
  const { toast } = useToast()

  const [watchlists, setWatchlists] = useState<Watchlist[]>([])
  const [loading, setLoading] = useState(true)
  const [newListName, setNewListName] = useState('')
  const [dialogOpen, setDialogOpen] = useState(false)

  useEffect(() => {
    if (!isAuthenticated) return

    const fetchWatchlists = async () => {
      try {
        const data = await watchlistApi.getAll()
        setWatchlists(data)
      } catch (error) {
        console.error('Failed to fetch watchlists:', error)
      } finally {
        setLoading(false)
      }
    }

    fetchWatchlists()
  }, [isAuthenticated])

  const handleCreateList = async () => {
    if (!newListName.trim()) return

    try {
      const newList = await watchlistApi.create(newListName)
      setWatchlists([...watchlists, newList])
      setNewListName('')
      setDialogOpen(false)
      toast({ title: '워치리스트가 생성되었습니다' })
    } catch (error) {
      toast({ title: '생성 실패', variant: 'destructive' })
    }
  }

  const handleDeleteList = async (id: number) => {
    try {
      await watchlistApi.delete(id)
      setWatchlists(watchlists.filter((list) => list.id !== id))
      toast({ title: '워치리스트가 삭제되었습니다' })
    } catch (error) {
      toast({ title: '삭제 실패', variant: 'destructive' })
    }
  }

  const handleRemoveItem = async (watchlistId: number, itemId: number) => {
    try {
      await watchlistApi.removeETF(watchlistId, itemId)
      setWatchlists(
        watchlists.map((list) =>
          list.id === watchlistId
            ? { ...list, items: list.items.filter((item) => item.id !== itemId) }
            : list
        )
      )
      toast({ title: 'ETF가 제거되었습니다' })
    } catch (error) {
      toast({ title: '제거 실패', variant: 'destructive' })
    }
  }

  if (!isAuthenticated) {
    return (
      <div className="text-center py-12">
        <h2 className="text-2xl font-bold mb-4">로그인이 필요합니다</h2>
        <p className="text-muted-foreground mb-6">
          워치리스트 기능을 사용하려면 로그인해주세요
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
      <div className="flex items-center justify-between">
        <h1 className="text-3xl font-bold">워치리스트</h1>
        <Dialog open={dialogOpen} onOpenChange={setDialogOpen}>
          <DialogTrigger asChild>
            <Button>
              <Plus className="w-4 h-4 mr-2" />
              새 워치리스트
            </Button>
          </DialogTrigger>
          <DialogContent>
            <DialogHeader>
              <DialogTitle>새 워치리스트 생성</DialogTitle>
            </DialogHeader>
            <div className="space-y-4">
              <Input
                placeholder="워치리스트 이름"
                value={newListName}
                onChange={(e) => setNewListName(e.target.value)}
                onKeyDown={(e) => e.key === 'Enter' && handleCreateList()}
              />
              <Button onClick={handleCreateList} className="w-full">
                생성
              </Button>
            </div>
          </DialogContent>
        </Dialog>
      </div>

      {watchlists.length === 0 ? (
        <Card>
          <CardContent className="py-12 text-center">
            <p className="text-muted-foreground mb-4">
              아직 워치리스트가 없습니다
            </p>
            <Button onClick={() => setDialogOpen(true)}>
              <Plus className="w-4 h-4 mr-2" />
              첫 워치리스트 만들기
            </Button>
          </CardContent>
        </Card>
      ) : (
        <div className="grid gap-6">
          {watchlists.map((list) => (
            <Card key={list.id}>
              <CardHeader className="flex flex-row items-center justify-between">
                <CardTitle>{list.name}</CardTitle>
                <Button
                  variant="ghost"
                  size="sm"
                  className="text-destructive hover:text-destructive"
                  onClick={() => handleDeleteList(list.id)}
                >
                  <Trash2 className="w-4 h-4" />
                </Button>
              </CardHeader>
              <CardContent>
                {list.items.length === 0 ? (
                  <p className="text-muted-foreground text-center py-4">
                    ETF를 추가해주세요
                  </p>
                ) : (
                  <div className="flex flex-wrap gap-2">
                    {list.items.map((item) => (
                      <Link key={item.id} to={`/etf/${item.etf_code}`}>
                        <Badge
                          variant="secondary"
                          className="pl-3 pr-1 py-2 flex items-center gap-2 hover:bg-secondary/80"
                        >
                          <span>{item.etf_name}</span>
                          <button
                            className="hover:bg-secondary rounded p-0.5"
                            onClick={(e) => {
                              e.preventDefault()
                              e.stopPropagation()
                              handleRemoveItem(list.id, item.id)
                            }}
                          >
                            <X className="w-3 h-3" />
                          </button>
                        </Badge>
                      </Link>
                    ))}
                  </div>
                )}
              </CardContent>
            </Card>
          ))}
        </div>
      )}
    </div>
  )
}
