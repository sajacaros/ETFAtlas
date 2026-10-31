import { useState } from 'react'
import { ArrowLeft, RefreshCw, Pencil, Check, Share2, Copy } from 'lucide-react'
import { Card, CardContent } from '@/components/ui/card'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog'
import { portfolioApi } from '@/lib/api'
import { copyText } from '@/lib/clipboard'
import { formatWon } from '@/lib/format'
import { holdingsMarkdown } from '@/lib/holdingsMarkdown'
import { useToast } from '@/hooks/use-toast'
import type { usePortfolioDraft } from '@/hooks/usePortfolioDraft'
import type { CalculationResult, Portfolio, PortfolioDetail } from '@/types/api'
import { AccountTypeBadges, AccountTypePicker } from '@/components/AccountType'
import PortfolioTable from '@/components/PortfolioTable'
import AddTickerDialog from '@/components/AddTickerDialog'
import { PortfolioSummaryBar } from './PortfolioStats'

// Enter로 입력을 끝내면 포커스를 뺀다 (값은 편집 완료 때 한꺼번에 저장)
const blurOnEnter = (e: React.KeyboardEvent<HTMLInputElement>) => {
  if (e.key === 'Enter') (e.target as HTMLInputElement).blur()
}

/** 포트폴리오 상세 — 보기/편집 화면. 편집 중 바꾼 값은 draft에 모았다가 onSave로 한 번에 저장한다 */
export default function PortfolioDetailView({
  detail,
  portfolio,
  calcResult,
  calcLoading,
  draft,
  saving,
  onBack,
  onRefresh,
  onSave,
}: {
  detail: PortfolioDetail
  portfolio: Portfolio | undefined  // 목록의 같은 포트폴리오 (평가금액 요약)
  calcResult: CalculationResult | null
  calcLoading: boolean
  draft: ReturnType<typeof usePortfolioDraft>
  saving: boolean
  onBack: () => void
  onRefresh: () => void
  onSave: () => void
}) {
  const { toast } = useToast()
  const { isEditing } = draft
  const [shareOpen, setShareOpen] = useState(false)
  const [sharing, setSharing] = useState(false)

  const handleShare = async () => {
    setSharing(true)
    try {
      const res = await portfolioApi.share(detail.id)
      setShareOpen(false)
      toast(res.created
        ? { title: '공유했습니다', description: '공유 포트폴리오에서 볼 수 있습니다' }
        : { title: '이미 같은 구성으로 공유되어 있습니다', description: '새로 공유하지 않았습니다' })
    } catch {
      toast({ title: '공유하지 못했습니다', variant: 'destructive' })
    } finally {
      setSharing(false)
    }
  }

  const handleCopy = async () => {
    if (!calcResult) return
    const markdown = holdingsMarkdown(
      calcResult.rows.map((r) => ({ name: r.name, ticker: r.ticker, weight: r.target_weight })),
    )
    try {
      await copyText(markdown)
      toast({ title: '구성을 마크다운으로 복사했습니다' })
    } catch {
      toast({ title: '복사하지 못했습니다', variant: 'destructive' })
    }
  }

  const handleAddTicker = (ticker: string, targetWeight: number, quantity: number, avgPrice?: number, name?: string) => {
    draft.addTicker({ ticker, name: name || ticker, targetWeight, quantity, avgPrice })
    toast({ title: `${name || ticker} 추가 예정` })
  }

  return (
    <div className="space-y-6">
      <div className="flex items-center gap-4">
        <Button
          variant="ghost"
          size="sm"
          onClick={onBack}
        >
          <ArrowLeft className="w-4 h-4 mr-1" />
          목록
        </Button>
        {isEditing ? (
          <Input
            className="text-xl font-bold border-none shadow-none h-auto py-1 px-2 max-w-xs"
            value={draft.name}
            onChange={(e) => draft.setName(e.target.value)}
            onKeyDown={blurOnEnter}
          />
        ) : (
          <h2 className="text-xl font-bold py-1 px-2">{detail.name}</h2>
        )}
        {isEditing ? (
          <AccountTypePicker value={draft.accountTypes} onChange={draft.setAccountTypes} compact />
        ) : (
          <AccountTypeBadges types={detail.account_types} />
        )}
        <div className="flex items-center gap-2 ml-auto">
          {calcLoading && <span className="text-sm text-muted-foreground">계산 중...</span>}
          {isEditing && <AddTickerDialog onAdd={handleAddTicker} />}
          {!isEditing && (
            <>
              <Button variant="outline" size="sm" onClick={() => setShareOpen(true)}>
                <Share2 className="w-4 h-4 mr-1" />
                공유
              </Button>
              <Dialog open={shareOpen} onOpenChange={(open) => { if (!sharing) setShareOpen(open) }}>
                <DialogContent className="max-w-sm">
                  <DialogHeader>
                    <DialogTitle>포트폴리오 공유</DialogTitle>
                    <DialogDescription>
                      '{detail.name}'의 지금 목표 비중을 공유하시겠습니까? 공유한 뒤 포트폴리오를 고쳐도 공유된 내용은 바뀌지 않습니다.
                    </DialogDescription>
                  </DialogHeader>
                  <DialogFooter className="gap-2 sm:gap-0">
                    <Button variant="outline" onClick={() => setShareOpen(false)} disabled={sharing}>
                      취소
                    </Button>
                    <Button onClick={handleShare} disabled={sharing}>
                      {sharing ? '공유 중...' : '공유'}
                    </Button>
                  </DialogFooter>
                </DialogContent>
              </Dialog>
              <Button
                variant="outline"
                size="sm"
                disabled={!calcResult?.rows.length}
                onClick={handleCopy}
              >
                <Copy className="w-4 h-4 mr-1" />
                복사
              </Button>
            </>
          )}
          <Button
            variant="outline"
            size="sm"
            disabled={calcLoading}
            onClick={onRefresh}
          >
            <RefreshCw className={`w-4 h-4 ${calcLoading ? 'animate-spin' : ''}`} />
          </Button>
          <Button
            variant={isEditing ? 'default' : 'outline'}
            size="sm"
            disabled={saving}
            onClick={() => {
              if (isEditing) {
                onSave()
              } else {
                draft.begin(detail)
              }
            }}
          >
            {isEditing ? (
              <>
                <Check className="w-4 h-4 mr-1" />
                {saving ? '저장 중...' : '편집 완료'}
              </>
            ) : (
              <>
                <Pencil className="w-4 h-4 mr-1" />
                편집
              </>
            )}
          </Button>
        </div>
      </div>

      {/* Summary bar */}
      {portfolio && (
        <PortfolioSummaryBar portfolio={portfolio}>
          {isEditing ? (
            <Input
              type="text"
              inputMode="numeric"
              className="w-32 h-7 text-sm"
              value={draft.cash}
              onChange={(e) => {
                const raw = e.target.value.replace(/,/g, '')
                if (raw === '' || /^\d+$/.test(raw)) {
                  draft.setCash(raw === '' ? '' : formatWon(parseInt(raw, 10)))
                }
              }}
              onKeyDown={blurOnEnter}
              placeholder="예: 500,000"
            />
          ) : (
            <span className="text-sm font-mono">{draft.cash || '0'}원</span>
          )}
        </PortfolioSummaryBar>
      )}


      {/* Table */}
      {calcLoading && !calcResult && (
        <Card>
          <CardContent className="py-16 text-center">
            <RefreshCw className="w-6 h-6 animate-spin mx-auto mb-3 text-muted-foreground" />
            <p className="text-muted-foreground">종목 데이터를 계산하고 있습니다...</p>
          </CardContent>
        </Card>
      )}
      {calcResult && (
        <PortfolioTable
          rows={draft.displayedRows}
          totalWeight={calcResult.total_weight}
          weightWarning={calcResult.weight_warning}
          totalHoldingAmount={calcResult.total_holding_amount}
          totalAdjustmentAmount={calcResult.total_adjustment_amount}
          totalProfitLossAmount={calcResult.total_profit_loss_amount}
          targetAllocations={draft.displayedTargetAllocations}
          holdings={draft.displayedHoldings}
          isEditing={isEditing}
          onUpdateWeight={(ticker, _targetId, weight) => draft.setWeight(ticker, weight)}
          onUpdateQuantity={(ticker, quantity) => draft.setQuantity(ticker, quantity)}
          onUpdateAvgPrice={(ticker, avgPrice) => draft.setAvgPrice(ticker, avgPrice)}
          onDeleteTicker={(ticker) => draft.deleteTicker(ticker)}
        />
      )}
    </div>
  )
}
