import { useState, useCallback, useEffect, useMemo } from 'react'
import { useToast } from '@/hooks/use-toast'
import { useLatestRequest } from '@/hooks/useAsync'
import { adminApi } from '@/lib/api'
import { formatDateTime, formatServerDate } from '@/lib/date'
import type { AdminChatLog } from '@/types/api'
import { Button } from '@/components/ui/button'
import { Badge } from '@/components/ui/badge'
import { Label } from '@/components/ui/label'
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from '@/components/ui/table'
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
  DialogDescription,
} from '@/components/ui/dialog'
import { Check, X, Upload, Undo2, Loader2 } from 'lucide-react'
import { STATUS_FILTERS, statusBadgeVariant } from './common'
import ExampleFormDialog, { type ExampleForm } from './ExampleFormDialog'

// ============ Chat Logs Tab ============

const CHAT_LOG_PAGE_SIZE = 50

export default function ChatLogsTab() {
  const { toast } = useToast()
  const [items, setItems] = useState<AdminChatLog[]>([])
  const [total, setTotal] = useState(0)
  const [statusFilter, setStatusFilter] = useState('')
  const [loading, setLoading] = useState(false)
  const [loadingMore, setLoadingMore] = useState(false)
  const [embedDialogOpen, setEmbedDialogOpen] = useState(false)
  const [embedTarget, setEmbedTarget] = useState<AdminChatLog | null>(null)
  const [detailDialog, setDetailDialog] = useState<AdminChatLog | null>(null)

  // 필터를 바꾼 뒤 늦게 온 이전 필터의 응답은 버린다
  const beginRequest = useLatestRequest()

  // 처음부터 다시 받는다 (필터 변경·리뷰 후)
  const fetchItems = useCallback(async () => {
    const isLatest = beginRequest()
    setLoading(true)
    try {
      const res = await adminApi.listChatLogs(statusFilter || undefined, 0, CHAT_LOG_PAGE_SIZE)
      if (!isLatest()) return
      setItems(res.items)
      setTotal(res.total)
    } catch {
      if (isLatest()) toast({ title: '채팅 로그 목록 조회 실패', variant: 'destructive' })
    } finally {
      if (isLatest()) setLoading(false)
    }
  }, [statusFilter, toast, beginRequest])

  const loadMore = async () => {
    const isLatest = beginRequest()
    setLoadingMore(true)
    try {
      const res = await adminApi.listChatLogs(statusFilter || undefined, items.length, CHAT_LOG_PAGE_SIZE)
      if (!isLatest()) return
      setItems([...items, ...res.items])
      setTotal(res.total)
    } catch {
      if (isLatest()) toast({ title: '채팅 로그 목록 조회 실패', variant: 'destructive' })
    } finally {
      setLoadingMore(false)
    }
  }

  useEffect(() => {
    fetchItems()
  }, [fetchItems])

  const handleReview = useCallback(async (id: number, action: string) => {
    try {
      await adminApi.reviewChatLog(id, action)
      toast({ title: action === 'approve' ? '승인되었습니다' : '거절되었습니다' })
      fetchItems()
    } catch {
      toast({ title: '리뷰 처리 실패', variant: 'destructive' })
    }
  }, [fetchItems, toast])

  const handleWithdraw = useCallback(async (id: number) => {
    try {
      await adminApi.withdrawChatLog(id)
      toast({ title: '철회되었습니다' })
      fetchItems()
    } catch {
      toast({ title: '철회 실패', variant: 'destructive' })
    }
  }, [fetchItems, toast])

  const handleEmbed = useCallback(async (form: ExampleForm) => {
    if (!embedTarget) return
    try {
      await adminApi.embedChatLog(embedTarget.id, { question: form.question, code: form.body, description: form.description })
      toast({ title: '임베드되었습니다' })
      setEmbedDialogOpen(false)
      setEmbedTarget(null)
      fetchItems()
    } catch {
      toast({ title: '임베드 실패', variant: 'destructive' })
    }
  }, [embedTarget, fetchItems, toast])

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center gap-2">
        {STATUS_FILTERS.chatLogs.map((f) => (
          <Button
            key={f.value}
            variant={statusFilter === f.value ? 'default' : 'outline'}
            size="sm"
            onClick={() => setStatusFilter(f.value)}
          >
            {f.label}
          </Button>
        ))}
        <span className="text-sm text-muted-foreground ml-2 whitespace-nowrap">총 {total}건</span>
      </div>

      <Table>
        <TableHeader>
          <TableRow>
            <TableHead className="w-[60px]">ID</TableHead>
            <TableHead>Question</TableHead>
            <TableHead className="max-w-[200px]">Answer</TableHead>
            <TableHead className="w-[100px]">상태</TableHead>
            <TableHead className="w-[140px]">생성일</TableHead>
            <TableHead className="w-[160px]">작업</TableHead>
          </TableRow>
        </TableHeader>
        <TableBody>
          {loading ? (
            <TableRow>
              <TableCell colSpan={6} className="text-center py-8 text-muted-foreground">
                로딩 중...
              </TableCell>
            </TableRow>
          ) : items.length === 0 ? (
            <TableRow>
              <TableCell colSpan={6} className="text-center py-8 text-muted-foreground">
                데이터가 없습니다
              </TableCell>
            </TableRow>
          ) : (
            items.map((item) => (
              <TableRow key={item.id}>
                <TableCell>{item.id}</TableCell>
                <TableCell
                  className="max-w-[300px] truncate cursor-pointer hover:text-primary"
                  onClick={() => setDetailDialog(item)}
                >
                  {item.question}
                  {item.refined_question && (
                    <div className="text-xs text-muted-foreground truncate">→ {item.refined_question}</div>
                  )}
                </TableCell>
                <TableCell className="max-w-[200px] truncate text-muted-foreground">
                  {item.answer.slice(0, 80)}
                  {item.answer.length > 80 && '...'}
                </TableCell>
                <TableCell>
                  <Badge variant={statusBadgeVariant(item.status)}>{item.status}</Badge>
                </TableCell>
                <TableCell className="text-sm text-muted-foreground">
                  {formatServerDate(item.created_at)}
                </TableCell>
                <TableCell>
                  <div className="flex gap-1">
                    {(item.status === 'liked' || item.status === 'rejected') && (
                      <Button
                        variant="ghost"
                        size="icon"
                        className="h-8 w-8 text-green-600"
                        title="승인"
                        onClick={() => handleReview(item.id, 'approve')}
                      >
                        <Check className="w-4 h-4" />
                      </Button>
                    )}
                    {(item.status === 'liked' || item.status === 'approved') && (
                      <Button
                        variant="ghost"
                        size="icon"
                        className="h-8 w-8 text-destructive"
                        title="거절"
                        onClick={() => handleReview(item.id, 'reject')}
                      >
                        <X className="w-4 h-4" />
                      </Button>
                    )}
                    {item.status === 'approved' && (
                      <Button
                        variant="ghost"
                        size="icon"
                        className="h-8 w-8 text-blue-600"
                        title="임베드"
                        onClick={() => { setEmbedTarget(item); setEmbedDialogOpen(true) }}
                      >
                        <Upload className="w-4 h-4" />
                      </Button>
                    )}
                    {item.status === 'embedded' && (
                      <Button
                        variant="ghost"
                        size="icon"
                        className="h-8 w-8 text-orange-600"
                        title="철회"
                        onClick={() => handleWithdraw(item.id)}
                      >
                        <Undo2 className="w-4 h-4" />
                      </Button>
                    )}
                  </div>
                </TableCell>
              </TableRow>
            ))
          )}
        </TableBody>
      </Table>

      {!loading && items.length < total && (
        <Button variant="outline" size="sm" onClick={loadMore} disabled={loadingMore}>
          {loadingMore && <Loader2 className="h-4 w-4 mr-1 animate-spin" />}더 보기
        </Button>
      )}

      <EmbedDialog
        open={embedDialogOpen}
        onOpenChange={(open) => { setEmbedDialogOpen(open); if (!open) setEmbedTarget(null) }}
        chatLog={embedTarget}
        onEmbed={handleEmbed}
      />

      <ChatLogDetailDialog
        chatLog={detailDialog}
        onOpenChange={(open) => { if (!open) setDetailDialog(null) }}
      />
    </div>
  )
}

function EmbedDialog({
  open,
  onOpenChange,
  chatLog,
  onEmbed,
}: {
  open: boolean
  onOpenChange: (open: boolean) => void
  chatLog: AdminChatLog | null
  onEmbed: (form: ExampleForm) => Promise<void>
}) {
  // 맥락에 기대는 원문보다 재작성된 독립 질문이 예시로 쓸모 있다
  const initial = useMemo(() => chatLog && {
    question: chatLog.refined_question || chatLog.question,
    body: chatLog.generated_code || '',
    description: '',
  }, [chatLog])

  return (
    <ExampleFormDialog
      open={open}
      onOpenChange={onOpenChange}
      initial={initial}
      title="코드 예제로 임베드"
      description="승인된 채팅 로그를 코드 예제로 변환합니다."
      idPrefix="embed-"
      bodyLabel="Code"
      submitLabel="임베드"
      submittingLabel="임베드 중..."
      onSubmit={onEmbed}
    />
  )
}

function ChatLogDetailDialog({
  chatLog,
  onOpenChange,
}: {
  chatLog: AdminChatLog | null
  onOpenChange: (open: boolean) => void
}) {
  return (
    <Dialog open={!!chatLog} onOpenChange={onOpenChange}>
      <DialogContent className="max-w-2xl max-h-[80vh] overflow-y-auto">
        <DialogHeader>
          <DialogTitle>채팅 로그 상세</DialogTitle>
          <DialogDescription>ID: {chatLog?.id}</DialogDescription>
        </DialogHeader>
        {chatLog && (
          <div className="space-y-4">
            <div>
              <Label className="text-muted-foreground">Question</Label>
              <p className="mt-1 whitespace-pre-wrap">{chatLog.question}</p>
            </div>
            <div>
              <Label className="text-muted-foreground">Answer</Label>
              <p className="mt-1 whitespace-pre-wrap text-sm">{chatLog.answer}</p>
            </div>
            {chatLog.generated_code && (
              <div>
                <Label className="text-muted-foreground">Generated Code</Label>
                <pre className="mt-1 p-3 bg-muted rounded text-sm overflow-x-auto font-mono">
                  {chatLog.generated_code}
                </pre>
              </div>
            )}
            <div className="flex gap-4 text-sm text-muted-foreground">
              <span>상태: <Badge variant={statusBadgeVariant(chatLog.status)}>{chatLog.status}</Badge></span>
              <span>결과: {chatLog.result}</span>
              <span>생성일: {formatDateTime(chatLog.created_at)}</span>
            </div>
          </div>
        )}
      </DialogContent>
    </Dialog>
  )
}
