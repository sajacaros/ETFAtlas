import { useState, useCallback, useEffect, useMemo } from 'react'
import { useToast } from '@/hooks/use-toast'
import { useLatestRequest } from '@/hooks/useAsync'
import { adminApi, getErrorDetail } from '@/lib/api'
import { formatServerDate } from '@/lib/date'
import type { AdminCodeExample, AdminLayoutExample, AdminExampleSearch } from '@/types/api'
import { Button } from '@/components/ui/button'
import { Badge } from '@/components/ui/badge'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from '@/components/ui/table'
import { Switch } from '@/components/ui/switch'
import { Plus, Pencil, Archive, Search, Loader2 } from 'lucide-react'
import { STATUS_FILTERS, statusBadgeVariant } from './common'
import ExampleFormDialog, { type ExampleForm } from './ExampleFormDialog'

// ============ Code / Layout Examples Tab ============

type SearchResult = AdminExampleSearch['results'][number]

const EXAMPLE_PAGE_SIZE = 50

// 코드 예제와 레이아웃 예제는 본문(code / plan)만 다르다
interface ExampleItem {
  id: number
  question: string
  question_generalized: string | null
  body: string
  description: string | null
  status: string
  created_at: string | null
}

interface ExampleKind {
  noun: string
  bodyLabel: string
  bodyPlaceholder: string
  list: (status: string | undefined, skip: number) => Promise<{ items: ExampleItem[]; total: number }>
  create: (form: ExampleForm) => Promise<unknown>
  update: (id: number, form: ExampleForm) => Promise<unknown>
  archive: (id: number) => Promise<unknown>
  search: (q: string, topK: number, generalize: boolean) => Promise<AdminExampleSearch>
}

export const CODE_EXAMPLES: ExampleKind = {
  noun: '코드 예제',
  bodyLabel: 'Code',
  bodyPlaceholder: '코드를 입력하세요',
  list: async (status, skip) => {
    const res = await adminApi.listCodeExamples(status, skip, EXAMPLE_PAGE_SIZE)
    return { items: res.items.map((i: AdminCodeExample) => ({ ...i, body: i.code })), total: res.total }
  },
  create: (f) => adminApi.createCodeExample({ question: f.question, code: f.body, description: f.description }),
  update: (id, f) => adminApi.updateCodeExample(id, { question: f.question, code: f.body, description: f.description }),
  archive: (id) => adminApi.archiveCodeExample(id),
  search: (q, k, g) => adminApi.searchSimilarExamples(q, k, g),
}

export const LAYOUT_EXAMPLES: ExampleKind = {
  noun: '레이아웃 예제',
  bodyLabel: 'Plan (JSON — 대상 이름은 <종목>, <종목1> 같은 자리표시자로)',
  bodyPlaceholder: '{"rows": [{"slots": [{"skill": "stock_holders", "title": "...", "display": "bar", "args": {"stocks": ["<종목>"]}}]}]}',
  list: async (status, skip) => {
    const res = await adminApi.listLayoutExamples(status, skip, EXAMPLE_PAGE_SIZE)
    return { items: res.items.map((i: AdminLayoutExample) => ({ ...i, body: i.plan })), total: res.total }
  },
  create: (f) => adminApi.createLayoutExample({ question: f.question, plan: f.body, description: f.description }),
  update: (id, f) => adminApi.updateLayoutExample(id, { question: f.question, plan: f.body, description: f.description }),
  archive: (id) => adminApi.archiveLayoutExample(id),
  search: (q, k, g) => adminApi.searchSimilarLayoutExamples(q, k, g),
}

export default function ExamplesTab({ kind }: { kind: ExampleKind }) {
  const { toast } = useToast()
  const [items, setItems] = useState<ExampleItem[]>([])
  const [total, setTotal] = useState(0)
  const [statusFilter, setStatusFilter] = useState('')
  const [loading, setLoading] = useState(false)
  const [loadingMore, setLoadingMore] = useState(false)
  const [dialogOpen, setDialogOpen] = useState(false)
  const [editItem, setEditItem] = useState<ExampleItem | null>(null)
  const [searchQuery, setSearchQuery] = useState('')
  const [searchResults, setSearchResults] = useState<SearchResult[] | null>(null)
  const [searching, setSearching] = useState(false)
  const [generalize, setGeneralize] = useState(false)
  const [queryGeneralized, setQueryGeneralized] = useState<string | null>(null)

  // 필터를 바꾼 뒤 늦게 온 이전 필터의 응답은 버린다
  const beginRequest = useLatestRequest()

  // 처음부터 다시 받는다 (필터 변경·저장 후)
  const fetchItems = useCallback(async () => {
    const isLatest = beginRequest()
    setLoading(true)
    try {
      const res = await kind.list(statusFilter || undefined, 0)
      if (!isLatest()) return
      setItems(res.items)
      setTotal(res.total)
    } catch {
      if (isLatest()) toast({ title: `${kind.noun} 목록 조회 실패`, variant: 'destructive' })
    } finally {
      if (isLatest()) setLoading(false)
    }
  }, [kind, statusFilter, toast, beginRequest])

  const loadMore = async () => {
    const isLatest = beginRequest()
    setLoadingMore(true)
    try {
      const res = await kind.list(statusFilter || undefined, items.length)
      if (!isLatest()) return
      setItems([...items, ...res.items])
      setTotal(res.total)
    } catch {
      if (isLatest()) toast({ title: `${kind.noun} 목록 조회 실패`, variant: 'destructive' })
    } finally {
      setLoadingMore(false)
    }
  }

  useEffect(() => {
    fetchItems()
  }, [fetchItems])

  const handleArchive = useCallback(async (id: number) => {
    try {
      await kind.archive(id)
      toast({ title: '아카이브 처리되었습니다' })
      fetchItems()
    } catch {
      toast({ title: '아카이브 실패', variant: 'destructive' })
    }
  }, [kind, fetchItems, toast])

  const handleSave = useCallback(async (form: ExampleForm) => {
    try {
      if (editItem) {
        await kind.update(editItem.id, form)
        toast({ title: '수정되었습니다' })
      } else {
        await kind.create(form)
        toast({ title: '추가되었습니다' })
      }
      setDialogOpen(false)
      setEditItem(null)
      fetchItems()
    } catch (e) {
      // 레이아웃 계획 검증 오류(400)는 문구가 문자열로 온다
      const detail = getErrorDetail(e)
      toast({ title: '저장 실패', description: typeof detail === 'string' ? detail : undefined, variant: 'destructive' })
    }
  }, [kind, editItem, fetchItems, toast])

  const handleSearch = useCallback(async () => {
    if (!searchQuery.trim()) {
      setSearchResults(null)
      setQueryGeneralized(null)
      return
    }
    setSearching(true)
    try {
      const res = await kind.search(searchQuery.trim(), 5, generalize)
      setSearchResults(res.results)
      setQueryGeneralized(res.query_generalized)
    } catch {
      toast({ title: '유사도 검색 실패', variant: 'destructive' })
    } finally {
      setSearching(false)
    }
  }, [kind, searchQuery, generalize, toast])

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <div className="flex flex-wrap items-center gap-2">
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
          <span className="text-sm text-muted-foreground ml-2 whitespace-nowrap">총 {total}건</span>
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
                    {formatServerDate(item.created_at)}
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

      {!loading && items.length < total && (
        <Button variant="outline" size="sm" onClick={loadMore} disabled={loadingMore}>
          {loadingMore && <Loader2 className="h-4 w-4 mr-1 animate-spin" />}더 보기
        </Button>
      )}

      <ExampleDialog
        kind={kind}
        open={dialogOpen}
        onOpenChange={(open) => { setDialogOpen(open); if (!open) setEditItem(null) }}
        editItem={editItem}
        onSave={handleSave}
      />
    </div>
  )
}

function ExampleDialog({
  kind,
  open,
  onOpenChange,
  editItem,
  onSave,
}: {
  kind: ExampleKind
  open: boolean
  onOpenChange: (open: boolean) => void
  editItem: ExampleItem | null
  onSave: (form: ExampleForm) => Promise<void>
}) {
  const initial = useMemo(() => ({
    question: editItem?.question || '',
    body: editItem?.body || '',
    description: editItem?.description || '',
  }), [editItem])

  const canSubmit = (f: ExampleForm) => {
    if (!f.question.trim() || !f.body.trim()) return false
    return editItem
      ? f.question !== editItem.question ||
        f.body !== editItem.body ||
        f.description !== (editItem.description ?? '')
      : true // 추가 모드에서는 항상 활성화
  }

  return (
    <ExampleFormDialog
      open={open}
      onOpenChange={onOpenChange}
      initial={initial}
      title={editItem ? `${kind.noun} 수정` : `${kind.noun} 추가`}
      description={editItem ? `${kind.noun}를 수정합니다.` : `새 ${kind.noun}를 추가합니다.`}
      bodyLabel={kind.bodyLabel}
      placeholders={{ question: '질문을 입력하세요', body: kind.bodyPlaceholder, description: '설명 (선택)' }}
      canSubmit={canSubmit}
      submitLabel="저장"
      submittingLabel="저장 중..."
      onSubmit={onSave}
    />
  )
}
