import { useState, useCallback, useEffect } from 'react'
import { useAuth } from '@/hooks/useAuth'
import { useToast } from '@/hooks/use-toast'
import { adminApi } from '@/lib/api'
import type { AdminCodeExample, AdminChatLog } from '@/types/api'
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs'
import { Button } from '@/components/ui/button'
import { Badge } from '@/components/ui/badge'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { Textarea } from '@/components/ui/textarea'
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
  DialogFooter,
  DialogDescription,
} from '@/components/ui/dialog'
import { Switch } from '@/components/ui/switch'
import { ShieldAlert, Plus, Pencil, Archive, Check, X, Upload, Undo2, Search, Loader2 } from 'lucide-react'

const STATUS_FILTERS = {
  codeExamples: [
    { label: '전체', value: '' },
    { label: 'Active', value: 'active' },
    { label: 'Embedded', value: 'embedded' },
  ],
  chatLogs: [
    { label: '전체', value: '' },
    { label: 'Liked', value: 'liked' },
    { label: 'Approved', value: 'approved' },
    { label: 'Rejected', value: 'rejected' },
    { label: 'Embedded', value: 'embedded' },
  ],
}

function statusBadgeVariant(status: string): 'default' | 'secondary' | 'destructive' | 'outline' {
  switch (status) {
    case 'active':
    case 'approved':
    case 'embedded':
      return 'default'
    case 'liked':
      return 'secondary'
    case 'rejected':
      return 'destructive'
    default:
      return 'outline'
  }
}

export default function AdminPage() {
  const { user } = useAuth()

  if (!user?.is_admin) {
    return (
      <div className="flex flex-col items-center justify-center py-20 text-muted-foreground">
        <ShieldAlert className="w-16 h-16 mb-4" />
        <h2 className="text-xl font-semibold mb-2">접근 권한이 없습니다</h2>
        <p>관리자 권한이 필요합니다.</p>
      </div>
    )
  }

  return (
    <div className="space-y-6">
      <h1 className="text-2xl font-bold">관리자</h1>
      <Tabs defaultValue="code-examples">
        <TabsList>
          <TabsTrigger value="code-examples">코드 예제</TabsTrigger>
          <TabsTrigger value="chat-logs">채팅 로그</TabsTrigger>
        </TabsList>
        <TabsContent value="code-examples">
          <CodeExamplesTab />
        </TabsContent>
        <TabsContent value="chat-logs">
          <ChatLogsTab />
        </TabsContent>
      </Tabs>
    </div>
  )
}

// ============ Code Examples Tab ============

interface SearchResult {
  id: number
  question: string
  question_generalized: string | null
  description: string | null
  distance: number
}

function CodeExamplesTab() {
  const { toast } = useToast()
  const [items, setItems] = useState<AdminCodeExample[]>([])
  const [total, setTotal] = useState(0)
  const [statusFilter, setStatusFilter] = useState('')
  const [loading, setLoading] = useState(false)
  const [dialogOpen, setDialogOpen] = useState(false)
  const [editItem, setEditItem] = useState<AdminCodeExample | null>(null)
  const [searchQuery, setSearchQuery] = useState('')
  const [searchResults, setSearchResults] = useState<SearchResult[] | null>(null)
  const [searching, setSearching] = useState(false)
  const [generalize, setGeneralize] = useState(false)
  const [queryGeneralized, setQueryGeneralized] = useState<string | null>(null)

  const fetchItems = useCallback(async () => {
    setLoading(true)
    try {
      const res = await adminApi.listCodeExamples(statusFilter || undefined)
      setItems(res.items)
      setTotal(res.total)
    } catch {
      toast({ title: '코드 예제 목록 조회 실패', variant: 'destructive' })
    } finally {
      setLoading(false)
    }
  }, [statusFilter, toast])

  useEffect(() => {
    fetchItems()
  }, [fetchItems])

  const handleArchive = useCallback(async (id: number) => {
    try {
      await adminApi.archiveCodeExample(id)
      toast({ title: '아카이브 처리되었습니다' })
      fetchItems()
    } catch {
      toast({ title: '아카이브 실패', variant: 'destructive' })
    }
  }, [fetchItems, toast])

  const handleSave = useCallback(async (form: { question: string; code: string; description: string }) => {
    try {
      if (editItem) {
        await adminApi.updateCodeExample(editItem.id, form)
        toast({ title: '수정되었습니다' })
      } else {
        await adminApi.createCodeExample(form)
        toast({ title: '추가되었습니다' })
      }
      setDialogOpen(false)
      setEditItem(null)
      fetchItems()
    } catch {
      toast({ title: '저장 실패', variant: 'destructive' })
    }
  }, [editItem, fetchItems, toast])

  const handleSearch = useCallback(async () => {
    if (!searchQuery.trim()) {
      setSearchResults(null)
      setQueryGeneralized(null)
      return
    }
    setSearching(true)
    try {
      const res = await adminApi.searchSimilarExamples(searchQuery.trim(), 5, generalize)
      setSearchResults(res.results)
      setQueryGeneralized(res.query_generalized)
    } catch {
      toast({ title: '유사도 검색 실패', variant: 'destructive' })
    } finally {
      setSearching(false)
    }
  }, [searchQuery, generalize, toast])

  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-2">
          {STATUS_FILTERS.codeExamples.map((f) => (
            <Button
              key={f.value}
              variant={statusFilter === f.value ? 'default' : 'outline'}
              size="sm"
              onClick={() => { setStatusFilter(f.value); setSearchResults(null); setSearchQuery('') }}
            >
              {f.label}
            </Button>
          ))}
          <span className="text-sm text-muted-foreground ml-2">총 {total}건</span>
        </div>
        <Button
          size="sm"
          onClick={() => { setEditItem(null); setDialogOpen(true) }}
        >
          <Plus className="w-4 h-4 mr-1" />
          추가
        </Button>
      </div>

      {statusFilter === 'embedded' && (
        <div className="space-y-2">
          <div className="flex gap-2 items-center">
            <div className="relative flex-1">
              <Search className="absolute left-2.5 top-2.5 h-4 w-4 text-muted-foreground" />
              <Input
                value={searchQuery}
                onChange={(e) => setSearchQuery(e.target.value)}
                onKeyDown={(e) => e.key === 'Enter' && handleSearch()}
                placeholder="질문을 입력하여 유사도 검색 테스트..."
                className="pl-9"
              />
            </div>
            <div className="flex items-center gap-1.5 shrink-0">
              <Switch checked={generalize} onCheckedChange={setGeneralize} />
              <Label className="text-sm cursor-pointer" onClick={() => setGeneralize(!generalize)}>일반화</Label>
            </div>
            <Button size="sm" onClick={handleSearch} disabled={searching || !searchQuery.trim()}>
              {searching ? <Loader2 className="w-4 h-4 animate-spin" /> : '검색'}
            </Button>
            {searchResults && (
              <Button size="sm" variant="ghost" onClick={() => { setSearchResults(null); setSearchQuery(''); setQueryGeneralized(null) }}>
                초기화
              </Button>
            )}
          </div>
          {queryGeneralized && (
            <div className="text-sm text-muted-foreground px-1">
              일반화 결과: <span className="text-foreground">{queryGeneralized}</span>
            </div>
          )}
        </div>
      )}

      {searchResults && (
        <div className="rounded-md border bg-muted/50 p-3 space-y-2">
          <div className="text-sm font-medium">유사도 검색 결과 ({searchResults.length}건)</div>
          {searchResults.length === 0 ? (
            <p className="text-sm text-muted-foreground">매칭된 예제가 없습니다.</p>
          ) : (
            searchResults.map((r) => (
              <div key={r.id} className="flex items-center gap-3 text-sm">
                <Badge variant="outline" className="shrink-0 w-16 justify-center">
                  {Math.round((1 - r.distance) * 100)}%
                </Badge>
                <span className="text-muted-foreground shrink-0">#{r.id}</span>
                <span className="truncate">{r.question}</span>
                {r.question_generalized && r.question_generalized !== r.question && (
                  <span className="text-muted-foreground truncate shrink-0 max-w-[200px]">
                    → {r.question_generalized}
                  </span>
                )}
              </div>
            ))
          )}
        </div>
      )}

      <Table>
        <TableHeader>
          <TableRow>
            <TableHead className="w-[60px]">ID</TableHead>
            <TableHead>Question</TableHead>
            <TableHead>일반화</TableHead>
            <TableHead className="w-[100px]">상태</TableHead>
            <TableHead className="w-[140px]">생성일</TableHead>
            <TableHead className="w-[100px]">작업</TableHead>
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
            items.map((item) => {
              const match = searchResults?.find((r) => r.id === item.id)
              return (
                <TableRow key={item.id} className={match ? 'bg-primary/10' : undefined}>
                  <TableCell>
                    <div className="flex items-center gap-1">
                      {item.id}
                      {match && (
                        <Badge variant="secondary" className="text-[10px] px-1 py-0">
                          {Math.round((1 - match.distance) * 100)}%
                        </Badge>
                      )}
                    </div>
                  </TableCell>
                  <TableCell className="max-w-[300px] truncate">{item.question}</TableCell>
                  <TableCell className="max-w-[300px] truncate text-muted-foreground">
                    {item.question_generalized && item.question_generalized !== item.question
                      ? item.question_generalized
                      : <span className="text-muted-foreground/50">동일</span>}
                  </TableCell>
                  <TableCell>
                    <Badge variant={statusBadgeVariant(item.status)}>{item.status}</Badge>
                  </TableCell>
                  <TableCell className="text-sm text-muted-foreground">
                    {item.created_at ? new Date(item.created_at).toLocaleDateString() : '-'}
                  </TableCell>
                  <TableCell>
                    <div className="flex gap-1">
                      <Button
                        variant="ghost"
                        size="icon"
                        className="h-8 w-8"
                        onClick={() => { setEditItem(item); setDialogOpen(true) }}
                      >
                        <Pencil className="w-4 h-4" />
                      </Button>
                      {item.status === 'embedded' && (
                        <Button
                          variant="ghost"
                          size="icon"
                          className="h-8 w-8 text-destructive"
                          onClick={() => handleArchive(item.id)}
                        >
                          <Archive className="w-4 h-4" />
                        </Button>
                      )}
                    </div>
                  </TableCell>
                </TableRow>
              )
            })
          )}
        </TableBody>
      </Table>

      <CodeExampleDialog
        open={dialogOpen}
        onOpenChange={(open) => { setDialogOpen(open); if (!open) setEditItem(null) }}
        editItem={editItem}
        onSave={handleSave}
      />
    </div>
  )
}

function CodeExampleDialog({
  open,
  onOpenChange,
  editItem,
  onSave,
}: {
  open: boolean
  onOpenChange: (open: boolean) => void
  editItem: AdminCodeExample | null
  onSave: (form: { question: string; code: string; description: string }) => void
}) {
  const [question, setQuestion] = useState('')
  const [code, setCode] = useState('')
  const [description, setDescription] = useState('')
  const [saving, setSaving] = useState(false)

  useEffect(() => {
    if (open) {
      setQuestion(editItem?.question || '')
      setCode(editItem?.code || '')
      setDescription(editItem?.description || '')
    }
  }, [open, editItem])

  const hasChanges = editItem
    ? question !== editItem.question ||
      code !== editItem.code ||
      description !== (editItem.description ?? '')
    : true // 추가 모드에서는 항상 활성화

  const handleSubmit = async () => {
    if (!question.trim() || !code.trim()) return
    setSaving(true)
    await onSave({ question, code, description })
    setSaving(false)
  }

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="max-w-2xl max-h-[80vh] overflow-y-auto">
        <DialogHeader>
          <DialogTitle>{editItem ? '코드 예제 수정' : '코드 예제 추가'}</DialogTitle>
          <DialogDescription>
            {editItem ? '코드 예제를 수정합니다.' : '새 코드 예제를 추가합니다.'}
          </DialogDescription>
        </DialogHeader>
        <div className="space-y-4">
          <div>
            <Label htmlFor="question">Question</Label>
            <Input
              id="question"
              value={question}
              onChange={(e) => setQuestion(e.target.value)}
              placeholder="질문을 입력하세요"
            />
          </div>
          <div>
            <Label htmlFor="code">Code</Label>
            <Textarea
              id="code"
              value={code}
              onChange={(e) => setCode(e.target.value)}
              placeholder="코드를 입력하세요"
              rows={8}
              className="font-mono text-sm"
            />
          </div>
          <div>
            <Label htmlFor="description">Description</Label>
            <Textarea
              id="description"
              value={description}
              onChange={(e) => setDescription(e.target.value)}
              placeholder="설명 (선택)"
              rows={3}
            />
          </div>
        </div>
        <DialogFooter>
          <Button variant="outline" onClick={() => onOpenChange(false)}>취소</Button>
          <Button onClick={handleSubmit} disabled={saving || !question.trim() || !code.trim() || !hasChanges}>
            {saving ? '저장 중...' : '저장'}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}

// ============ Chat Logs Tab ============

function ChatLogsTab() {
  const { toast } = useToast()
  const [items, setItems] = useState<AdminChatLog[]>([])
  const [total, setTotal] = useState(0)
  const [statusFilter, setStatusFilter] = useState('')
  const [loading, setLoading] = useState(false)
  const [embedDialogOpen, setEmbedDialogOpen] = useState(false)
  const [embedTarget, setEmbedTarget] = useState<AdminChatLog | null>(null)
  const [detailDialog, setDetailDialog] = useState<AdminChatLog | null>(null)

  const fetchItems = useCallback(async () => {
    setLoading(true)
    try {
      const res = await adminApi.listChatLogs(statusFilter || undefined)
      setItems(res.items)
      setTotal(res.total)
    } catch {
      toast({ title: '채팅 로그 목록 조회 실패', variant: 'destructive' })
    } finally {
      setLoading(false)
    }
  }, [statusFilter, toast])

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

  const handleEmbed = useCallback(async (form: { question?: string; code?: string; description?: string }) => {
    if (!embedTarget) return
    try {
      await adminApi.embedChatLog(embedTarget.id, form)
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
      <div className="flex items-center gap-2">
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
        <span className="text-sm text-muted-foreground ml-2">총 {total}건</span>
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
                </TableCell>
                <TableCell className="max-w-[200px] truncate text-muted-foreground">
                  {item.answer.slice(0, 80)}
                  {item.answer.length > 80 && '...'}
                </TableCell>
                <TableCell>
                  <Badge variant={statusBadgeVariant(item.status)}>{item.status}</Badge>
                </TableCell>
                <TableCell className="text-sm text-muted-foreground">
                  {new Date(item.created_at).toLocaleDateString()}
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
  onEmbed: (form: { question?: string; code?: string; description?: string }) => void
}) {
  const [question, setQuestion] = useState('')
  const [code, setCode] = useState('')
  const [description, setDescription] = useState('')
  const [saving, setSaving] = useState(false)

  useEffect(() => {
    if (open && chatLog) {
      setQuestion(chatLog.question)
      setCode(chatLog.generated_code || '')
      setDescription('')
    }
  }, [open, chatLog])

  const handleSubmit = async () => {
    setSaving(true)
    await onEmbed({ question, code, description })
    setSaving(false)
  }

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="max-w-2xl max-h-[80vh] overflow-y-auto">
        <DialogHeader>
          <DialogTitle>코드 예제로 임베드</DialogTitle>
          <DialogDescription>승인된 채팅 로그를 코드 예제로 변환합니다.</DialogDescription>
        </DialogHeader>
        <div className="space-y-4">
          <div>
            <Label htmlFor="embed-question">Question</Label>
            <Input
              id="embed-question"
              value={question}
              onChange={(e) => setQuestion(e.target.value)}
            />
          </div>
          <div>
            <Label htmlFor="embed-code">Code</Label>
            <Textarea
              id="embed-code"
              value={code}
              onChange={(e) => setCode(e.target.value)}
              rows={8}
              className="font-mono text-sm"
            />
          </div>
          <div>
            <Label htmlFor="embed-description">Description</Label>
            <Textarea
              id="embed-description"
              value={description}
              onChange={(e) => setDescription(e.target.value)}
              rows={3}
            />
          </div>
        </div>
        <DialogFooter>
          <Button variant="outline" onClick={() => onOpenChange(false)}>취소</Button>
          <Button onClick={handleSubmit} disabled={saving}>
            {saving ? '임베드 중...' : '임베드'}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
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
              <span>생성일: {new Date(chatLog.created_at).toLocaleString()}</span>
            </div>
          </div>
        )}
      </DialogContent>
    </Dialog>
  )
}
