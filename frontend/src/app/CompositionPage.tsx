import { useEffect, useMemo, useRef, useState } from 'react'
import { useNavigate, useSearchParams } from 'react-router-dom'
import { ChevronDown, FolderOpen, Layers, Save, X } from 'lucide-react'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog'
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuLabel,
  DropdownMenuTrigger,
} from '@/components/ui/dropdown-menu'
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from '@/components/ui/table'
import { ETFInfoDialog } from '@/components/ETFInfo'
import { etfsApi, portfolioApi } from '@/lib/api'
import { useToast } from '@/hooks/use-toast'
import { cn } from '@/lib/utils'
import type { CompositionResponse, Portfolio } from '@/types/api'

interface Pick {
  code: string
  name: string
  weight: string  // 입력 중인 값을 그대로 두려고 문자열로 보관
}

const parseWeight = (v: string) => {
  const n = parseFloat(v)
  return Number.isFinite(n) && n > 0 ? n : 0
}

const formatPct = (v: number, digits = 2) => `${v.toFixed(digits)}%`

// 정수면 소수점 없이, 아니면 한 자리까지
const formatInputPct = (v: number) => `${Number.isInteger(v) ? v : v.toFixed(1)}%`

const defaultPortfolioName = (picks: Pick[]) => {
  const names = picks.slice(0, 2).map((p) => p.name).join(' + ')
  return picks.length > 2 ? `${names} 외 ${picks.length - 2}` : names
}

export default function CompositionPage() {
  const navigate = useNavigate()
  const [searchParams, setSearchParams] = useSearchParams()
  const { toast } = useToast()

  const [picks, setPicks] = useState<Pick[]>([])
  const [expanded, setExpanded] = useState(true)

  // ETF 검색
  const [query, setQuery] = useState('')
  const [searchResults, setSearchResults] = useState<{ code: string; name: string }[]>([])
  const [searching, setSearching] = useState(false)
  const searchSeq = useRef(0)

  // 계산 결과
  const [result, setResult] = useState<CompositionResponse | null>(null)
  const [calculating, setCalculating] = useState(false)
  const [calcError, setCalcError] = useState(false)

  // 포트폴리오 불러오기
  const [portfolios, setPortfolios] = useState<Portfolio[]>([])

  // ETF 상세 모달
  const [detail, setDetail] = useState<Pick | null>(null)

  // 저장
  const [saveOpen, setSaveOpen] = useState(false)
  const [saveName, setSaveName] = useState('')
  const [saving, setSaving] = useState(false)

  const activePicks = useMemo(
    () => picks.filter((p) => parseWeight(p.weight) > 0),
    [picks],
  )
  const inputTotal = useMemo(
    () => picks.reduce((sum, p) => sum + parseWeight(p.weight), 0),
    [picks],
  )
  const normalizedOf = (p: Pick) => (inputTotal > 0 ? parseWeight(p.weight) * 100 / inputTotal : 0)

  useEffect(() => {
    portfolioApi.getAll().then(setPortfolios).catch(() => {})
  }, [])

  const loadPortfolio = async (id: number) => {
    try {
      const detail = await portfolioApi.get(id)
      // 현금은 구성종목이 없으므로 불러오지 않는다
      const targets = detail.target_allocations.filter((t) => t.ticker.toUpperCase() !== 'CASH')
      const etfs = await Promise.allSettled(targets.map((t) => etfsApi.get(t.ticker)))
      setPicks(targets.map((t, i) => {
        const etf = etfs[i]
        return {
          code: t.ticker,
          name: etf.status === 'fulfilled' ? etf.value.name : t.ticker,
          weight: String(Number(t.target_weight)),
        }
      }))
      setExpanded(true)
      toast({ title: `'${detail.name}'의 목표 비중을 불러왔습니다` })
    } catch {
      toast({ title: '포트폴리오를 불러오지 못했습니다', variant: 'destructive' })
    }
  }

  // 포트폴리오 화면의 "구성종목 보기"로 들어온 경우
  useEffect(() => {
    const id = Number(searchParams.get('portfolio'))
    if (!id) return
    setSearchParams({}, { replace: true })
    loadPortfolio(id)
  }, [])

  const handleSearch = async (value: string) => {
    setQuery(value)
    const seq = ++searchSeq.current
    if (value.trim().length < 2) {
      setSearchResults([])
      setSearching(false)
      return
    }
    setSearching(true)
    try {
      const results = await etfsApi.search(value.trim(), 20)
      if (seq !== searchSeq.current) return
      const used = new Set(picks.map((p) => p.code))
      setSearchResults(results.filter((r) => !used.has(r.code)).map((r) => ({ code: r.code, name: r.name })))
    } catch {
      if (seq === searchSeq.current) setSearchResults([])
    } finally {
      if (seq === searchSeq.current) setSearching(false)
    }
  }

  const addPick = (code: string, name: string) => {
    setPicks((prev) => (prev.some((p) => p.code === code) ? prev : [...prev, { code, name, weight: '10' }]))
    setQuery('')
    setSearchResults([])
    searchSeq.current++
    // 추가한 ETF의 비중 칸으로 바로 이동
    requestAnimationFrame(() => {
      const input = document.getElementById(`weight-${code}`) as HTMLInputElement | null
      input?.focus()
      input?.select()
    })
  }

  const updateWeight = (code: string, weight: string) => {
    setPicks((prev) => prev.map((p) => (p.code === code ? { ...p, weight } : p)))
  }

  const removePick = (code: string) => {
    setPicks((prev) => prev.filter((p) => p.code !== code))
  }

  // 비중을 입력하는 동안 요청이 몰리지 않게 잠깐 기다렸다가 계산한다
  const requestKey = JSON.stringify(activePicks.map((p) => [p.code, parseWeight(p.weight)]))
  useEffect(() => {
    if (activePicks.length === 0) {
      setResult(null)
      setCalcError(false)
      setCalculating(false)
      return
    }
    const controller = new AbortController()
    const timer = setTimeout(() => {
      setCalculating(true)
      setCalcError(false)
      etfsApi.getComposition(
        activePicks.map((p) => ({ code: p.code, weight: parseWeight(p.weight) })),
        controller.signal,
      )
        .then(setResult)
        .catch(() => {
          if (!controller.signal.aborted) setCalcError(true)
        })
        .finally(() => {
          if (!controller.signal.aborted) setCalculating(false)
        })
    }, 300)
    return () => {
      clearTimeout(timer)
      controller.abort()
    }
  }, [requestKey])

  const openSave = () => {
    setSaveName(defaultPortfolioName(activePicks))
    setSaveOpen(true)
  }

  const handleSave = async () => {
    if (!saveName.trim() || activePicks.length === 0) return
    setSaving(true)
    try {
      const created = await portfolioApi.create({
        name: saveName.trim(),
        calculation_base: 'CURRENT_TOTAL',
        targets: activePicks.map((p) => ({ ticker: p.code, target_weight: parseWeight(p.weight) })),
      })
      toast({ title: `'${created.name}'을(를) 만들었습니다` })
      navigate('/portfolio', { state: { selectId: created.id } })
    } catch {
      toast({ title: '저장 실패', variant: 'destructive' })
      setSaving(false)
    }
  }

  const maxWeight = result?.stocks[0]?.weight || 1
  const overlapCount = result?.stocks.filter((s) => s.etfs.length > 1).length ?? 0

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-2xl font-bold">구성종목 분석</h1>
        <p className="text-sm text-muted-foreground mt-1">
          ETF와 투자 비중을 넣으면 실제로 담기는 종목 비중을 바로 계산합니다.
        </p>
      </div>

      {/* ETF 구성 */}
      <Card>
        <CardHeader className={cn('flex flex-row flex-wrap items-start gap-3 space-y-0', expanded ? 'pb-3' : 'pb-5')}>
          <button
            type="button"
            className="flex items-center gap-2 rounded-md -ml-1 px-1 py-0.5 hover:bg-muted"
            aria-expanded={expanded}
            aria-controls="etf-picks"
            onClick={() => setExpanded((v) => !v)}
          >
            <ChevronDown className={cn('w-4 h-4 text-muted-foreground transition-transform', !expanded && '-rotate-90')} />
            <CardTitle className="text-base">ETF 구성</CardTitle>
            <span className="text-xs text-muted-foreground">{picks.length}개</span>
          </button>
          {!expanded && picks.length > 0 && (
            <div className="flex flex-1 basis-72 min-w-0 flex-wrap gap-1 pt-0.5">
              {picks.map((p) => (
                <span key={p.code} className="rounded-full border px-2 py-0.5 text-xs text-muted-foreground">
                  {p.name} <b className="font-semibold text-primary">{formatInputPct(parseWeight(p.weight))}</b>
                </span>
              ))}
              <span className="rounded-full border px-2 py-0.5 text-xs text-muted-foreground">
                합계 <b className="font-semibold text-primary">{formatInputPct(inputTotal)}</b>
              </span>
            </div>
          )}
          <DropdownMenu>
            <DropdownMenuTrigger asChild>
              <Button variant="outline" size="sm" className="ml-auto h-8 text-xs" disabled={portfolios.length === 0}>
                <FolderOpen className="w-3.5 h-3.5 mr-1.5" />
                포트폴리오에서 불러오기
              </Button>
            </DropdownMenuTrigger>
            <DropdownMenuContent align="end" className="max-h-72 overflow-y-auto">
              <DropdownMenuLabel className="text-xs text-muted-foreground">목표 비중을 불러옵니다</DropdownMenuLabel>
              {portfolios.map((p) => (
                <DropdownMenuItem key={p.id} onSelect={() => loadPortfolio(p.id)}>
                  {p.name}
                </DropdownMenuItem>
              ))}
            </DropdownMenuContent>
          </DropdownMenu>
        </CardHeader>

        {expanded && (
          <CardContent id="etf-picks" className="space-y-2">
            <div className="flex flex-wrap items-center gap-x-5 gap-y-2">
              <div className="relative flex-1 basis-72 max-w-md">
                <Input
                  placeholder="ETF 이름이나 코드로 추가"
                  value={query}
                  onChange={(e) => handleSearch(e.target.value)}
                  onBlur={() => setTimeout(() => setSearchResults([]), 150)}
                />
                {(searching || searchResults.length > 0) && (
                  <div className="absolute z-50 w-full mt-1 border rounded-md max-h-60 overflow-y-auto bg-background shadow-md">
                    {searching && searchResults.length === 0 && (
                      <p className="text-xs text-muted-foreground px-3 py-2">검색 중...</p>
                    )}
                    {searchResults.map((r) => (
                      <button
                        key={r.code}
                        type="button"
                        className="w-full text-left px-3 py-2 hover:bg-muted text-sm flex justify-between gap-2"
                        onMouseDown={(e) => e.preventDefault()}
                        onClick={() => addPick(r.code, r.name)}
                      >
                        <span>{r.name}</span>
                        <span className="font-mono text-xs text-muted-foreground">{r.code}</span>
                      </button>
                    ))}
                  </div>
                )}
              </div>
              <p className="text-sm text-muted-foreground tabular-nums">
                입력 합계 <b className="text-foreground">{formatInputPct(inputTotal)}</b> → 100% 기준으로 환산
              </p>
            </div>

            {picks.length > 0 && (
              <ul className="grid gap-x-8 [grid-template-columns:repeat(auto-fill,minmax(min(100%,380px),1fr))]">
                {picks.map((p) => (
                  <li key={p.code} className="grid grid-cols-[minmax(0,1fr)_80px_76px_28px] items-center gap-2 py-2.5 border-b">
                    <div className="min-w-0">
                      <button
                        type="button"
                        className="text-left text-sm font-medium hover:underline hover:text-primary break-words"
                        onClick={() => setDetail(p)}
                      >
                        {p.name}
                      </button>
                      <p className="font-mono text-[11px] text-muted-foreground">{p.code}</p>
                    </div>
                    <div className="relative">
                      <Input
                        id={`weight-${p.code}`}
                        type="number"
                        min="0"
                        max="100"
                        step="0.5"
                        className="h-8 pr-6 text-right tabular-nums"
                        value={p.weight}
                        aria-label={`${p.name} 투자 비중`}
                        onChange={(e) => updateWeight(p.code, e.target.value)}
                      />
                      <span className="pointer-events-none absolute right-2 top-1.5 text-xs text-muted-foreground">%</span>
                    </div>
                    <p className="text-right text-sm font-semibold text-primary tabular-nums">
                      <span className="mr-1 text-xs font-normal text-muted-foreground">환산</span>
                      {formatPct(normalizedOf(p), 1)}
                    </p>
                    <Button
                      variant="ghost"
                      size="sm"
                      className="h-7 w-7 p-0 text-muted-foreground"
                      aria-label={`${p.name} 빼기`}
                      onClick={() => removePick(p.code)}
                    >
                      <X className="w-4 h-4" />
                    </Button>
                  </li>
                ))}
              </ul>
            )}
          </CardContent>
        )}
      </Card>

      {/* 구성종목 비중 */}
      <Card>
        <CardHeader className="flex flex-row flex-wrap items-center justify-between gap-3 space-y-0 pb-3">
          <CardTitle className="text-base">
            구성종목 비중 <span className="text-xs font-normal text-muted-foreground">상위 30</span>
          </CardTitle>
          <Button size="sm" onClick={openSave} disabled={activePicks.length === 0}>
            <Save className="w-4 h-4 mr-1.5" />
            포트폴리오로 저장
          </Button>
        </CardHeader>
        <CardContent className="p-0">
          {activePicks.length === 0 ? (
            <div className="py-12 text-center text-muted-foreground">
              <Layers className="w-10 h-10 mx-auto mb-3 opacity-50" />
              <p>ETF를 추가하고 투자 비중을 입력하세요</p>
            </div>
          ) : calcError ? (
            <p className="py-12 text-center text-muted-foreground">구성종목을 계산하지 못했습니다. 잠시 후 다시 시도하세요.</p>
          ) : !result ? (
            <p className="py-12 text-center text-muted-foreground">계산 중...</p>
          ) : (
            <div className={cn('transition-opacity', calculating && 'opacity-60')}>
              <div className="flex flex-wrap gap-x-5 gap-y-1 px-6 pb-3 text-sm text-muted-foreground tabular-nums">
                <span>전체 종목 <b className="font-semibold text-foreground">{result.total_stocks}개</b></span>
                <span>겹치는 종목 <b className="font-semibold text-foreground">{overlapCount}개</b></span>
                {result.as_of && <span>기준일 <b className="font-semibold text-foreground">{result.as_of}</b></span>}
              </div>
              {result.stocks.length === 0 ? (
                <p className="py-10 text-center text-muted-foreground border-t">구성종목 정보가 있는 ETF가 없습니다</p>
              ) : (
                <Table className="min-w-[640px]">
                  <TableHeader>
                    <TableRow>
                      <TableHead className="w-14 text-right">순위</TableHead>
                      <TableHead>종목명</TableHead>
                      <TableHead className="w-44">포트폴리오 비중</TableHead>
                      <TableHead>소속 ETF (기여 비중)</TableHead>
                    </TableRow>
                  </TableHeader>
                  <TableBody>
                    {result.stocks.map((s) => (
                      <TableRow key={s.stock_code}>
                        <TableCell className="text-right text-muted-foreground tabular-nums">{s.rank}</TableCell>
                        <TableCell className="font-medium whitespace-nowrap">
                          {s.stock_name}
                          {s.etfs.length > 1 && (
                            <span className="ml-1.5 rounded bg-amber-100 px-1.5 py-px text-[10px] font-bold text-amber-700 dark:bg-amber-950 dark:text-amber-400">
                              중복 {s.etfs.length}
                            </span>
                          )}
                        </TableCell>
                        <TableCell>
                          <div className="relative flex h-6 items-center justify-end overflow-hidden rounded pr-2 font-semibold tabular-nums">
                            <div className="absolute inset-y-0 left-0 bg-primary/15" style={{ width: `${s.weight / maxWeight * 100}%` }} />
                            <span className="relative">{formatPct(s.weight)}</span>
                          </div>
                        </TableCell>
                        <TableCell>
                          <div className="flex flex-wrap gap-1">
                            {s.etfs.map((e) => (
                              <span key={e.code} className="whitespace-nowrap rounded-full border px-2 py-0.5 text-xs text-muted-foreground">
                                {e.name} <b className="font-medium text-foreground tabular-nums">{formatPct(e.weight)}</b>
                              </span>
                            ))}
                          </div>
                        </TableCell>
                      </TableRow>
                    ))}
                  </TableBody>
                </Table>
              )}
            </div>
          )}
        </CardContent>
      </Card>

      {detail && (
        <ETFInfoDialog
          code={detail.code}
          name={detail.name}
          open={!!detail}
          onOpenChange={(open) => !open && setDetail(null)}
          portfolioWeight={normalizedOf(detail)}
          detailInNewTab
        />
      )}

      <Dialog open={saveOpen} onOpenChange={(open) => !saving && setSaveOpen(open)}>
        <DialogContent className="max-w-md">
          <DialogHeader>
            <DialogTitle>포트폴리오로 저장</DialogTitle>
            <DialogDescription>
              지금 구성으로 새 포트폴리오를 만듭니다. 목표 비중만 들어가고 보유 수량은 비어 있습니다.
            </DialogDescription>
          </DialogHeader>
          <div className="space-y-4">
            <div className="space-y-2">
              <Label htmlFor="composition-portfolio-name">포트폴리오 이름</Label>
              <Input
                id="composition-portfolio-name"
                value={saveName}
                onChange={(e) => setSaveName(e.target.value)}
                onKeyDown={(e) => e.key === 'Enter' && handleSave()}
              />
            </div>
            <div className="space-y-2">
              <p className="text-sm font-medium">목표 비중 (입력값 그대로)</p>
              <div className="rounded-md border text-sm tabular-nums">
                {activePicks.map((p) => (
                  <div key={p.code} className="flex justify-between gap-3 px-3 py-1.5 border-b">
                    <span className="min-w-0 break-words">{p.name}</span>
                    <span>{formatPct(parseWeight(p.weight))}</span>
                  </div>
                ))}
                <div className="flex justify-between bg-muted px-3 py-1.5 font-semibold">
                  <span>합계</span>
                  <span>{formatPct(inputTotal)}</span>
                </div>
              </div>
              {Math.abs(inputTotal - 100) > 1e-9 && (
                <p className="text-xs text-muted-foreground">
                  합계가 {formatPct(inputTotal, 1)}라 포트폴리오 화면에 "목표 비중 합계가 100%가 아님" 경고가 함께 보입니다.
                </p>
              )}
            </div>
          </div>
          <DialogFooter>
            <Button variant="outline" onClick={() => setSaveOpen(false)} disabled={saving}>취소</Button>
            <Button onClick={handleSave} disabled={saving || !saveName.trim()}>
              {saving ? '저장 중...' : '저장하고 열기'}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  )
}
