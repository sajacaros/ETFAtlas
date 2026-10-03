import { useEffect, useRef, useState, type ReactNode } from 'react'
import { Link } from 'react-router-dom'
import { HelpCircle } from 'lucide-react'
import { Card, CardContent } from '@/components/ui/card'
import { Badge } from '@/components/ui/badge'
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog'
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from '@/components/ui/table'
import { etfsApi } from '@/lib/api'
import { cn, formatKrwAmount } from '@/lib/utils'
import type { ETF, Holding } from '@/types/api'

const DIVIDEND_CYCLE_LABELS: Record<number, string> = {
  0: '분배 없음',
  1: '월배당',
  3: '분기배당',
  6: '반기배당',
  12: '연배당',
}

export function dividendCycleLabel(cycle: number | null): string | null {
  if (cycle == null) return null
  return DIVIDEND_CYCLE_LABELS[cycle] ?? `${cycle}개월 주기 배당`
}

function InfoCard({ label, children }: { label: string; children: ReactNode }) {
  return (
    <Card className="py-3">
      <CardContent className="pb-0 pt-0">
        <p className="text-xs text-muted-foreground">{label}</p>
        {children}
      </CardContent>
    </Card>
  )
}

/** ? 아이콘: 마우스를 올리거나 누르면 설명을 보여준다 */
function HelpTip({ text, alignRight = false }: { text: string; alignRight?: boolean }) {
  const [open, setOpen] = useState(false)
  const ref = useRef<HTMLSpanElement>(null)

  useEffect(() => {
    if (!open) return
    const close = (e: PointerEvent) => {
      if (!ref.current?.contains(e.target as Node)) setOpen(false)
    }
    document.addEventListener('pointerdown', close)
    return () => document.removeEventListener('pointerdown', close)
  }, [open])

  return (
    <span ref={ref} className="relative inline-flex align-middle">
      <button
        type="button"
        aria-label="설명 보기"
        className="text-muted-foreground hover:text-foreground"
        onPointerEnter={(e) => e.pointerType === 'mouse' && setOpen(true)}
        onPointerLeave={(e) => e.pointerType === 'mouse' && setOpen(false)}
        onPointerDown={(e) => e.pointerType !== 'mouse' && setOpen((o) => !o)}
        onFocus={() => setOpen(true)}
        onBlur={() => setOpen(false)}
      >
        <HelpCircle className="w-3 h-3" />
      </button>
      {open && (
        <span
          role="tooltip"
          className={`absolute ${alignRight ? 'left-0 md:left-auto md:right-0' : 'left-0'} top-full z-20 mt-1 w-56 rounded-md border bg-popover p-2 text-xs font-normal leading-relaxed text-popover-foreground shadow-md`}
        >
          {text}
        </span>
      )}
    </span>
  )
}

const NET_ASSETS_HELP = 'ETF가 실제로 보유한 주식·현금 등 자산의 가치 (1주당 순자산가치 × 발행 주식 수)'
const MARKET_CAP_HELP = '시장에서 거래되는 ETF 가격으로 매긴 규모 (종가 × 상장 주식 수). 거래 가격이 순자산가치와 조금씩 달라 순자산과 차이가 납니다. 옆 숫자는 1주 전 대비 증감률입니다.'

export interface MarketCapInfo {
  latest: number
  weekAgo: number | null
  changeRate: number | null
}

function SizeLabel({ label, help, alignRight }: { label: string; help: string; alignRight?: boolean }) {
  return (
    <p className="text-xs text-muted-foreground flex items-center gap-1">
      {label}
      <HelpTip text={help} alignRight={alignRight} />
    </p>
  )
}

/** ETF 기본 정보 카드 (운용사·카테고리·순자산/시가총액·보수율·기초지수·상장일). 시가총액은 가격 데이터가 있을 때만 */
export function ETFInfoCards({ etf, tags, marketCap }: { etf: ETF; tags: string[]; marketCap?: MarketCapInfo | null }) {
  return (
    <div className="grid grid-cols-2 md:grid-cols-3 gap-3">
      <InfoCard label="운용사">
        <p className="text-sm font-semibold mt-1">{etf.issuer || '-'}</p>
      </InfoCard>
      <InfoCard label="카테고리">
        <div className="flex flex-wrap gap-1 mt-1">
          {tags.length > 0
            ? tags.map((tag) => (
                <Badge key={tag} variant="secondary" className="text-xs">
                  {tag}
                </Badge>
              ))
            : <p className="text-sm font-semibold">-</p>
          }
        </div>
      </InfoCard>
      <Card className="py-3">
        <CardContent className="pb-0 pt-0 flex flex-wrap gap-x-6 gap-y-2">
          <div>
            <SizeLabel label="순자산" help={NET_ASSETS_HELP} />
            <p className="text-sm font-semibold mt-1">
              {etf.net_assets ? formatKrwAmount(etf.net_assets) : '-'}
            </p>
          </div>
          {marketCap && (
            <div>
              <SizeLabel
                label="시가총액"
                help={marketCap.weekAgo != null
                  ? `${MARKET_CAP_HELP} (1주 전 ${formatKrwAmount(marketCap.weekAgo)})`
                  : MARKET_CAP_HELP}
                alignRight
              />
              <p className="text-sm font-semibold mt-1">
                {formatKrwAmount(marketCap.latest)}
                {marketCap.changeRate != null && (
                  <span className={`text-xs font-normal ml-1 ${marketCap.changeRate > 0 ? 'text-red-500' : marketCap.changeRate < 0 ? 'text-blue-500' : 'text-muted-foreground'}`}>
                    {marketCap.changeRate > 0 ? '+' : ''}{marketCap.changeRate.toFixed(1)}%
                  </span>
                )}
              </p>
            </div>
          )}
        </CardContent>
      </Card>
      <InfoCard label="보수율">
        <p className="text-sm font-semibold mt-1">
          {etf.expense_ratio ? `${etf.expense_ratio}%` : '-'}
        </p>
      </InfoCard>
      <InfoCard label="기초지수">
        <p className="text-sm font-semibold mt-1">{etf.base_index || '-'}</p>
      </InfoCard>
      <InfoCard label="상장일">
        <p className="text-sm font-semibold mt-1">{etf.listed_date || '-'}</p>
      </InfoCard>
    </div>
  )
}

interface ETFInfoDialogProps {
  code: string
  name?: string
  open: boolean
  onOpenChange: (open: boolean) => void
}

/** ETF 정보 카드 + 구성 종목 모달 (가격 정보 제외) */
export function ETFInfoDialog({ code, name, open, onOpenChange }: ETFInfoDialogProps) {
  const [etf, setEtf] = useState<ETF | null>(null)
  const [tags, setTags] = useState<string[]>([])
  const [holdings, setHoldings] = useState<Holding[]>([])
  const [loading, setLoading] = useState(false)

  useEffect(() => {
    if (!open) return
    let cancelled = false
    setLoading(true)
    setEtf(null)
    setTags([])
    setHoldings([])
    Promise.allSettled([etfsApi.get(code), etfsApi.getTags(code), etfsApi.getHoldings(code)])
      .then(([etfResult, tagsResult, holdingsResult]) => {
        if (cancelled) return
        if (etfResult.status === 'fulfilled') setEtf(etfResult.value)
        if (tagsResult.status === 'fulfilled') setTags(tagsResult.value)
        if (holdingsResult.status === 'fulfilled') {
          setHoldings([...holdingsResult.value].sort((a, b) => b.weight - a.weight))
        }
      })
      .finally(() => {
        if (!cancelled) setLoading(false)
      })
    return () => {
      cancelled = true
    }
  }, [code, open])

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="max-w-3xl w-[95vw] max-h-[90vh] overflow-y-auto">
        <DialogHeader>
          <DialogTitle className="text-xl">{etf?.name ?? name ?? code}</DialogTitle>
          <DialogDescription className="flex items-center gap-2">
            <span>{[code, etf && dividendCycleLabel(etf.dividend_cycle)].filter(Boolean).join(' · ')}</span>
            {etf && (
              <Link
                to={`/etf/${code}`}
                className="text-xs text-blue-600 hover:underline"
                onClick={() => onOpenChange(false)}
              >
                상세 보기
              </Link>
            )}
          </DialogDescription>
        </DialogHeader>

        {loading ? (
          <div className="text-center py-8 text-muted-foreground">로딩 중...</div>
        ) : !etf ? (
          <div className="text-center py-8 text-muted-foreground">ETF 정보가 없습니다</div>
        ) : (
          <div className="space-y-4 min-w-0">
            <ETFInfoCards etf={etf} tags={tags} />
            <div>
              <p className="text-sm font-semibold mb-2">구성 종목</p>
              {holdings.length === 0 ? (
                <p className="text-sm text-muted-foreground">구성 종목 정보가 없습니다</p>
              ) : (
                <Card>
                  <Table>
                    <TableHeader>
                      <TableRow>
                        <TableHead>종목명</TableHead>
                        <TableHead>종목코드</TableHead>
                        <TableHead className="text-right">비중</TableHead>
                      </TableRow>
                    </TableHeader>
                    <TableBody>
                      {holdings.map((h) => (
                        <TableRow key={h.stock_code}>
                          <TableCell className="font-medium">{h.stock_name}</TableCell>
                          <TableCell>{h.stock_code}</TableCell>
                          <TableCell className="text-right">{h.weight.toFixed(2)}%</TableCell>
                        </TableRow>
                      ))}
                    </TableBody>
                  </Table>
                </Card>
              )}
            </div>
          </div>
        )}
      </DialogContent>
    </Dialog>
  )
}

interface ETFLinkProps {
  code: string
  name?: string
  className?: string
  children: ReactNode
}

/** 누르면 ETF 정보 모달을 여는 링크 */
export function ETFLink({ code, name, className, children }: ETFLinkProps) {
  const [open, setOpen] = useState(false)
  return (
    <>
      <button
        type="button"
        className={cn('text-left hover:underline', className)}
        onClick={() => setOpen(true)}
      >
        {children}
      </button>
      <ETFInfoDialog code={code} name={name} open={open} onOpenChange={setOpen} />
    </>
  )
}
