import { useState, useCallback, useEffect } from 'react'
import { ETFLink } from '@/components/ETFInfo'
import { useToast } from '@/hooks/use-toast'
import { adminApi } from '@/lib/api'
import type { AdminETFTag } from '@/types/api'
import { Button } from '@/components/ui/button'
import { Badge } from '@/components/ui/badge'
import { Input } from '@/components/ui/input'
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from '@/components/ui/table'
import { X, Loader2, RotateCcw } from 'lucide-react'

// ============ ETF Tags Tab ============

const ETF_TAG_FILTERS = [
  { label: '전체', value: 'all' },
  { label: '태그 없음', value: 'untagged' },
  { label: '수동 지정', value: 'manual' },
] as const

type ETFTagFilter = (typeof ETF_TAG_FILTERS)[number]['value']

export default function ETFTagsTab() {
  const { toast } = useToast()
  const [items, setItems] = useState<AdminETFTag[]>([])
  const [tagOptions, setTagOptions] = useState<string[]>([])
  const [loading, setLoading] = useState(false)
  const [filter, setFilter] = useState<ETFTagFilter>('all')
  const [query, setQuery] = useState('')
  const [savingCode, setSavingCode] = useState<string | null>(null)

  const fetchItems = useCallback(async () => {
    setLoading(true)
    try {
      const res = await adminApi.listETFTags()
      setItems(res.items)
      setTagOptions(res.tags)
    } catch {
      toast({ title: 'ETF 태그 목록 조회 실패', variant: 'destructive' })
    } finally {
      setLoading(false)
    }
  }, [toast])

  useEffect(() => {
    fetchItems()
  }, [fetchItems])

  const save = useCallback(async (code: string, tags: string[] | null) => {
    setSavingCode(code)
    try {
      const updated = await adminApi.updateETFTags(code, tags)
      setItems((prev) => prev.map((item) => (item.code === code ? updated : item)))
      if (tags === null) {
        toast({ title: '수동 지정을 해제했습니다', description: '다음 태깅(토요일 03:00) 때 자동으로 다시 정해집니다.' })
      }
    } catch {
      toast({ title: '태그 저장 실패', variant: 'destructive' })
    } finally {
      setSavingCode(null)
    }
  }, [toast])

  const q = query.trim().toLowerCase()
  const visible = items.filter((item) => {
    if (filter === 'untagged' && item.tags.length > 0) return false
    if (filter === 'manual' && !item.manual) return false
    return !q || item.name.toLowerCase().includes(q) || item.code.toLowerCase().includes(q)
  })

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center gap-2">
        {ETF_TAG_FILTERS.map((f) => (
          <Button
            key={f.value}
            variant={filter === f.value ? 'default' : 'outline'}
            size="sm"
            onClick={() => setFilter(f.value)}
          >
            {f.label}
          </Button>
        ))}
        <Input
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          placeholder="ETF 이름 또는 코드"
          className="w-56 h-8"
        />
        <span className="text-sm text-muted-foreground ml-2">
          {visible.length} / {items.length}개
        </span>
      </div>
      <p className="text-sm text-muted-foreground">
        태그를 바꾸면 수동 지정이 되어 매주 자동 태깅에서 제외됩니다. 해제하면 다음 태깅 때 자동으로 다시 정해집니다.
      </p>

      <Table>
        <TableHeader>
          <TableRow>
            <TableHead className="w-[90px]">코드</TableHead>
            <TableHead>ETF</TableHead>
            <TableHead>태그</TableHead>
            <TableHead className="w-[100px]">구분</TableHead>
          </TableRow>
        </TableHeader>
        <TableBody>
          {loading ? (
            <TableRow>
              <TableCell colSpan={4} className="text-center py-8 text-muted-foreground">
                로딩 중...
              </TableCell>
            </TableRow>
          ) : visible.length === 0 ? (
            <TableRow>
              <TableCell colSpan={4} className="text-center py-8 text-muted-foreground">
                데이터가 없습니다
              </TableCell>
            </TableRow>
          ) : (
            visible.map((item) => {
              const saving = savingCode === item.code
              const remaining = tagOptions.filter((t) => !item.tags.includes(t))
              return (
                <TableRow key={item.code}>
                  <TableCell className="font-mono text-sm">{item.code}</TableCell>
                  <TableCell>
                    <ETFLink code={item.code} name={item.name}>{item.name}</ETFLink>
                  </TableCell>
                  <TableCell>
                    <div className="flex flex-wrap items-center gap-1">
                      {item.tags.map((tag) => (
                        <Badge key={tag} variant="secondary" className="gap-1 pr-1">
                          {tag}
                          <button
                            type="button"
                            aria-label={`${tag} 태그 제거`}
                            disabled={saving}
                            onClick={() => save(item.code, item.tags.filter((t) => t !== tag))}
                            className="rounded-full hover:bg-muted-foreground/20 disabled:opacity-50"
                          >
                            <X className="w-3 h-3" />
                          </button>
                        </Badge>
                      ))}
                      <select
                        aria-label={`${item.name} 태그 추가`}
                        value=""
                        disabled={saving || remaining.length === 0}
                        onChange={(e) => e.target.value && save(item.code, [...item.tags, e.target.value])}
                        className="h-7 rounded-md border border-input bg-background px-2 text-xs disabled:opacity-50"
                      >
                        <option value="">+ 태그</option>
                        {remaining.map((t) => (
                          <option key={t} value={t}>{t}</option>
                        ))}
                      </select>
                      {saving && <Loader2 className="w-3 h-3 animate-spin text-muted-foreground" />}
                    </div>
                  </TableCell>
                  <TableCell>
                    {item.manual ? (
                      <div className="flex items-center gap-1">
                        <Badge>수동</Badge>
                        <Button
                          variant="ghost"
                          size="sm"
                          className="h-7 w-7 p-0"
                          title="수동 지정 해제"
                          disabled={saving}
                          onClick={() => save(item.code, null)}
                        >
                          <RotateCcw className="w-3.5 h-3.5" />
                        </Button>
                      </div>
                    ) : (
                      <Badge variant="outline">자동</Badge>
                    )}
                  </TableCell>
                </TableRow>
              )
            })
          )}
        </TableBody>
      </Table>
    </div>
  )
}
