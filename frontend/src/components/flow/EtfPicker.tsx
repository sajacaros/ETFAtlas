import { useEffect, useRef, useState } from 'react'
import { Loader2 } from 'lucide-react'
import { etfsApi } from '@/lib/api'
import { Input } from '@/components/ui/input'
import { formatValue } from '@/components/answer/format'

type Hit = { code: string; name: string; net_assets: number | null }

interface Props {
  id: string
  value: string  // 고르면 6자리 코드, 고르지 않고 쓴 글자면 그 글자 (서버가 이름으로 찾는다)
  name: string  // 고른 ETF 이름 (화면 표시용)
  onPick: (code: string, name: string) => void
  onType: (text: string) => void
}

/** 구성종목을 수집하는 ETF 중에서 이름 일부나 코드로 찾아 고른다. 낱말 순서·띄어쓰기는 상관없다 */
export function EtfPicker({ id, value, name, onPick, onType }: Props) {
  const [query, setQuery] = useState(name || value)
  const [hits, setHits] = useState<Hit[]>([])
  const [open, setOpen] = useState(false)
  const [loading, setLoading] = useState(false)
  const [active, setActive] = useState(0)
  const seq = useRef(0)

  // 다른 노드를 고르면 그 노드의 값으로 바꾼다
  useEffect(() => setQuery(name || value), [id, name, value])

  useEffect(() => {
    if (!open) return
    const q = query.trim()
    const current = ++seq.current
    if (!q) {
      setHits([])
      return
    }
    setLoading(true)
    const timer = setTimeout(() => {
      etfsApi.searchUniverse(q, 8)
        .then((rows) => current === seq.current && (setHits(rows), setActive(0)))
        .catch(() => current === seq.current && setHits([]))
        .finally(() => current === seq.current && setLoading(false))
    }, 200)
    return () => clearTimeout(timer)
  }, [query, open])

  const pick = (h: Hit) => {
    onPick(h.code, h.name)
    setQuery(h.name)
    setOpen(false)
  }

  return (
    <div className="relative">
      <Input
        id={id}
        value={query}
        autoComplete="off"
        placeholder="예: 반도체 kodex, 069500"
        onChange={(e) => {
          setQuery(e.target.value)
          onType(e.target.value)
          setOpen(true)
        }}
        onFocus={() => setOpen(true)}
        onBlur={() => setTimeout(() => setOpen(false), 150)}  // 목록 클릭이 먼저 처리되게
        onKeyDown={(e) => {
          if (!open || !hits.length) return
          if (e.key === 'ArrowDown') { e.preventDefault(); setActive((a) => Math.min(a + 1, hits.length - 1)) }
          else if (e.key === 'ArrowUp') { e.preventDefault(); setActive((a) => Math.max(a - 1, 0)) }
          else if (e.key === 'Enter') { e.preventDefault(); pick(hits[active]) }
          else if (e.key === 'Escape') setOpen(false)
        }}
      />
      {name && value && !open && <p className="mt-1 text-xs text-muted-foreground">선택됨: {name} ({value})</p>}
      {open && query.trim() && (
        <ul className="absolute z-20 mt-1 max-h-72 w-full overflow-y-auto rounded-md border bg-popover p-1 text-sm shadow-md">
          {loading && !hits.length && (
            <li className="flex items-center gap-2 px-2 py-1.5 text-muted-foreground"><Loader2 className="h-3.5 w-3.5 animate-spin" /> 찾는 중</li>
          )}
          {!loading && !hits.length && <li className="px-2 py-1.5 text-muted-foreground">맞는 ETF가 없습니다</li>}
          {hits.map((h, i) => (
            <li key={h.code}>
              <button
                type="button"
                onMouseDown={(e) => e.preventDefault()}
                onClick={() => pick(h)}
                onMouseEnter={() => setActive(i)}
                className={`flex w-full items-baseline justify-between gap-2 rounded px-2 py-1.5 text-left ${i === active ? 'bg-muted' : ''}`}
              >
                <span className="truncate">{h.name}</span>
                <span className="shrink-0 text-xs text-muted-foreground">
                  {h.code}{h.net_assets ? ` · ${formatValue(h.net_assets, 'krw')}` : ''}
                </span>
              </button>
            </li>
          ))}
        </ul>
      )}
    </div>
  )
}
