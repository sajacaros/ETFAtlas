import { useEffect, useState, useCallback } from 'react'
import { Link } from 'react-router-dom'
import { useNavigate } from 'react-router-dom'
import { Plus, Trash2, ArrowLeft, AlertTriangle, RefreshCw, Pencil, Check, BarChart3, Eye, EyeOff, GripVertical } from 'lucide-react'
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
  DialogTrigger,
} from '@/components/ui/dialog'
import { portfolioApi } from '@/lib/api'
import { useAuth } from '@/hooks/useAuth'
import { useToast } from '@/hooks/use-toast'
import type { Portfolio, PortfolioDetail, CalculationResult, CalculationBase, DashboardSummary } from '@/types/api'
import PortfolioTable from '@/components/PortfolioTable'
import AddTickerDialog from '@/components/AddTickerDialog'
import { useAmountVisibility, formatMaskedNumber } from '@/hooks/useAmountVisibility'
import {
  DndContext,
  closestCenter,
  PointerSensor,
  useSensor,
  useSensors,
  DragEndEvent,
} from '@dnd-kit/core'
import {
  SortableContext,
  rectSortingStrategy,
  useSortable,
  arrayMove,
} from '@dnd-kit/sortable'
import { CSS } from '@dnd-kit/utilities'

function formatNumber(n: number): string {
  return new Intl.NumberFormat('ko-KR').format(Math.round(n))
}

function SortablePortfolioCard({
  portfolio: p,
  onSelect,
  onDelete,
  onBackfill,
  backfillLoading,
  onDashboard,
  amountVisible,
  formatMaskedNumber: fmn,
}: {
  portfolio: Portfolio
  onSelect: (id: number) => void
  onDelete: (id: number) => void
  onBackfill: (id: number) => void
  backfillLoading: number | null
  onDashboard: (id: number) => void
  amountVisible: boolean
  formatMaskedNumber: (v: number, visible: boolean) => string
}) {
  const {
    attributes,
    listeners,
    setNodeRef,
    transform,
    transition,
    isDragging,
  } = useSortable({ id: p.id })

  const style = {
    transform: CSS.Transform.toString(transform),
    transition,
    opacity: isDragging ? 0.5 : 1,
  }

  return (
    <Card
      ref={setNodeRef}
      style={style}
      className="cursor-pointer hover:shadow-md transition-shadow"
      onClick={() => onSelect(p.id)}
    >
      <CardHeader className="flex flex-row items-center justify-between pb-2">
        <div className="flex items-center gap-1">
          <button
            className="cursor-grab active:cursor-grabbing touch-none p-1 -ml-1 text-muted-foreground hover:text-foreground"
            {...attributes}
            {...listeners}
            onClick={(e) => e.stopPropagation()}
          >
            <GripVertical className="w-4 h-4" />
          </button>
          <CardTitle className="text-lg">{p.name}</CardTitle>
        </div>
        <Button
          variant="ghost"
          size="sm"
          className="text-destructive hover:text-destructive"
          onClick={(e) => {
            e.stopPropagation()
            onDelete(p.id)
          }}
        >
          <Trash2 className="w-4 h-4" />
        </Button>
      </CardHeader>
      <CardContent>
        <div>
          {p.current_value != null && p.current_value_date ? (
            <>
              <p className="text-lg font-bold font-mono">
                <span className="text-sm font-normal text-muted-foreground">
                  {p.current_value_date.slice(2).replace(/-/g, '/')}:
                </span>{' '}
                {fmn(p.current_value, amountVisible)}{amountVisible && '원'}
              </p>
              <p className={`text-sm font-mono ${(p.daily_change_rate ?? 0) >= 0 ? 'text-red-500' : 'text-blue-500'}`}>
                {amountVisible ? (
                  <>
                    <span className="font-normal text-muted-foreground">전일대비</span>{' '}
                    {(p.daily_change_amount ?? 0) >= 0 ? '+' : ''}{formatNumber(p.daily_change_amount ?? 0)}원
                    ({(p.daily_change_rate ?? 0) >= 0 ? '+' : ''}{(p.daily_change_rate ?? 0).toFixed(2)}%)
                  </>
                ) : (
                  '••••••'
                )}
              </p>
              {p.investment_return_rate != null && (
                <p className={`text-xs font-mono mt-1 ${p.investment_return_rate >= 0 ? 'text-red-500' : 'text-blue-500'}`}>
                  {amountVisible ? (
                    <>
                      투자금액 {formatNumber(p.invested_amount ?? 0)}원 / 수익률 {p.investment_return_rate >= 0 ? '+' : ''}{p.investment_return_rate.toFixed(2)}%
                    </>
                  ) : (
                    '투자수익률 ••••••'
                  )}
                </p>
              )}
            </>
          ) : (
            <div>
              <p className="text-sm text-muted-foreground">평가금액 없음</p>
              <Button
                variant="outline"
                size="sm"
                className="mt-2"
                disabled={backfillLoading === p.id}
                onClick={(e) => {
                  e.stopPropagation()
                  onBackfill(p.id)
                }}
              >
                <RefreshCw className={`w-3 h-3 mr-1 ${backfillLoading === p.id ? 'animate-spin' : ''}`} />
                {backfillLoading === p.id ? '생성 중...' : '스냅샷 생성'}
              </Button>
            </div>
          )}
        </div>
        <Button
          variant="outline"
          size="sm"
          className="mt-3"
          onClick={(e) => {
            e.stopPropagation()
            onDashboard(p.id)
          }}
        >
          <BarChart3 className="w-4 h-4 mr-1" />
          대시보드
        </Button>
      </CardContent>
    </Card>
  )
}

export default function PortfolioPage() {
  const { isAuthenticated } = useAuth()
  const { toast } = useToast()
  const navigate = useNavigate()
  const { visible: amountVisible, toggle: toggleAmount } = useAmountVisibility()

  const [portfolios, setPortfolios] = useState<Portfolio[]>([])
  const [loading, setLoading] = useState(true)
  const [selectedId, setSelectedId] = useState<number | null>(null)
  const [detail, setDetail] = useState<PortfolioDetail | null>(null)
  const [calcResult, setCalcResult] = useState<CalculationResult | null>(null)
  const [calcLoading, setCalcLoading] = useState(false)

  // Backfill
  const [backfillLoading, setBackfillLoading] = useState<number | null>(null)

  // Create dialog
  const [createOpen, setCreateOpen] = useState(false)
  const [newName, setNewName] = useState('')
  const [newBase, setNewBase] = useState<CalculationBase>('CURRENT_TOTAL')
  const [newAmount, setNewAmount] = useState('')

  // Delete confirmation
  const [deleteTargetId, setDeleteTargetId] = useState<number | null>(null)

  // Total summary
  const [totalSummary, setTotalSummary] = useState<DashboardSummary | null>(null)

  // Edit mode
  const [isEditing, setIsEditing] = useState(false)

  // Settings editing
  const [editName, setEditName] = useState('')
  const [editAmount, setEditAmount] = useState('')
  const [editCash, setEditCash] = useState('')

  const sensors = useSensors(
    useSensor(PointerSensor, { activationConstraint: { distance: 8 } })
  )

  const handleDragEnd = async (event: DragEndEvent) => {
    const { active, over } = event
    if (!over || active.id === over.id) return

    const oldIndex = portfolios.findIndex((p) => p.id === active.id)
    const newIndex = portfolios.findIndex((p) => p.id === over.id)
    const reordered = arrayMove(portfolios, oldIndex, newIndex)
    setPortfolios(reordered)

    const orders = reordered.map((p, i) => ({ id: p.id, display_order: i }))
    try {
      await portfolioApi.reorder(orders)
    } catch {
      const data = await portfolioApi.getAll()
      setPortfolios(data)
      toast({ title: '순서 변경 실패', variant: 'destructive' })
    }
  }

  useEffect(() => {
    if (!isAuthenticated) return
    const fetchPortfolios = async () => {
      try {
        const data = await portfolioApi.getAll()
        setPortfolios(data)
      } catch {
        console.error('Failed to fetch portfolios')
      } finally {
        setLoading(false)
      }
    }
    const fetchTotalSummary = async () => {
      try {
        const { summary } = await portfolioApi.getTotalDashboard()
        setTotalSummary(summary)
      } catch {
        // 스냅샷이 없는 경우 무시
      }
    }
    fetchPortfolios()
    fetchTotalSummary()
  }, [isAuthenticated])

  const loadDetail = useCallback(async (id: number) => {
    try {
      const d = await portfolioApi.get(id)
      setDetail(d)
      setEditName(d.name)
      setEditAmount(d.target_total_amount ? String(d.target_total_amount) : '')
      const cashHolding = d.holdings.find((h) => h.ticker === 'CASH')
      const cashQty = cashHolding ? Math.round(Number(cashHolding.quantity)) : 0
      setEditCash(cashQty > 0 ? formatNumber(cashQty) : '')
    } catch {
      toast({ title: '포트폴리오 로드 실패', variant: 'destructive' })
    }
  }, [toast])

  const loadCalc = useCallback(async (id: number) => {
    setCalcLoading(true)
    try {
      const r = await portfolioApi.calculate(id)
      setCalcResult(r)
    } catch {
      console.error('Failed to calculate')
    } finally {
      setCalcLoading(false)
    }
  }, [])

  const clearSelection = useCallback(() => {
    setSelectedId(null)
    setDetail(null)
    setCalcResult(null)
    setIsEditing(false)
  }, [])

  useEffect(() => {
    const handlePopState = () => {
      clearSelection()
    }
    window.addEventListener('popstate', handlePopState)
    return () => window.removeEventListener('popstate', handlePopState)
  }, [clearSelection])

  const selectPortfolio = useCallback(async (id: number) => {
    setSelectedId(id)
    window.history.pushState({ portfolioId: id }, '')
    await loadDetail(id)
    loadCalc(id)
  }, [loadDetail, loadCalc])

  const handleCreate = async () => {
    if (!newName.trim()) return
    try {
      const p = await portfolioApi.create({
        name: newName,
        calculation_base: newBase,
        target_total_amount: newAmount ? parseFloat(newAmount) : null,
      })
      setPortfolios([...portfolios, p])
      setNewName('')
      setNewBase('CURRENT_TOTAL')
      setNewAmount('')
      setCreateOpen(false)
      toast({ title: '포트폴리오가 생성되었습니다' })
    } catch {
      toast({ title: '생성 실패', variant: 'destructive' })
    }
  }

  const handleDelete = (id: number) => {
    setDeleteTargetId(id)
  }

  const confirmDelete = async () => {
    if (deleteTargetId === null) return
    const id = deleteTargetId
    setDeleteTargetId(null)
    try {
      await portfolioApi.delete(id)
      setPortfolios(portfolios.filter((p) => p.id !== id))
      if (selectedId === id) {
        setSelectedId(null)
        setDetail(null)
        setCalcResult(null)
      }
      toast({ title: '포트폴리오가 삭제되었습니다' })
    } catch {
      toast({ title: '삭제 실패', variant: 'destructive' })
    }
  }

  const handleBackfill = async (id: number) => {
    setBackfillLoading(id)
    try {
      const result = await portfolioApi.backfillSnapshots(id)
      const data = await portfolioApi.getAll()
      setPortfolios(data)
      toast({ title: `스냅샷 ${result.created}개가 생성되었습니다` })
    } catch (err: unknown) {
      const message = (err as { response?: { data?: { detail?: string } } })?.response?.data?.detail || '스냅샷 생성 실패'
      toast({ title: message, variant: 'destructive' })
    } finally {
      setBackfillLoading(null)
    }
  }

  const handleUpdateSettings = async (field: string, value: string) => {
    if (!selectedId || !detail) return
    try {
      const params: Record<string, string | number | null> = {}
      if (field === 'name') params.name = value
      if (field === 'target_total_amount') params.target_total_amount = value ? parseFloat(value) : null

      const updated = await portfolioApi.update(selectedId, params)
      setDetail({ ...detail, ...updated })
      setPortfolios(portfolios.map((p) => (p.id === selectedId ? { ...p, ...updated } : p)))

      if (field === 'target_total_amount' && !isEditing) {
        loadCalc(selectedId)
      }
    } catch {
      toast({ title: '업데이트 실패', variant: 'destructive' })
    }
  }

  const handleChangeBase = async (base: CalculationBase) => {
    if (!selectedId || !detail) return
    try {
      const updated = await portfolioApi.update(selectedId, { calculation_base: base })
      setDetail({ ...detail, ...updated })
      setPortfolios(portfolios.map((p) => (p.id === selectedId ? { ...p, ...updated } : p)))
      loadCalc(selectedId)
    } catch {
      toast({ title: '업데이트 실패', variant: 'destructive' })
    }
  }

  const handleUpdateCash = async (value: string) => {
    if (!selectedId) return
    const amount = parseInt(value.replace(/,/g, '') || '0', 10)
    try {
      await portfolioApi.addHolding(selectedId, { ticker: 'CASH', quantity: amount })
      await loadDetail(selectedId)
      loadCalc(selectedId)
    } catch {
      toast({ title: '예수금 업데이트 실패', variant: 'destructive' })
    }
  }

  const handleAddTicker = async (ticker: string, targetWeight: number, quantity: number, avgPrice?: number) => {
    if (!selectedId) return
    try {
      await portfolioApi.addTarget(selectedId, { ticker, target_weight: targetWeight })
      if (quantity > 0 || avgPrice) {
        await portfolioApi.addHolding(selectedId, { ticker, quantity, ...(avgPrice ? { avg_price: avgPrice } : {}) })
      }
      await loadDetail(selectedId)
      loadCalc(selectedId)
      toast({ title: '종목이 추가되었습니다' })
    } catch {
      toast({ title: '종목 추가 실패', variant: 'destructive' })
    }
  }

  const handleUpdateWeight = async (targetId: number, weight: number) => {
    if (!selectedId) return
    try {
      await portfolioApi.updateTarget(selectedId, targetId, { target_weight: weight })
      await loadDetail(selectedId)
      loadCalc(selectedId)
    } catch {
      toast({ title: '비중 업데이트 실패', variant: 'destructive' })
    }
  }

  const handleUpdateQuantity = async (ticker: string, quantity: number, holdingId?: number) => {
    if (!selectedId) return
    try {
      if (holdingId) {
        await portfolioApi.updateHolding(selectedId, holdingId, { quantity })
      } else {
        await portfolioApi.addHolding(selectedId, { ticker, quantity })
      }
      await loadDetail(selectedId)
      loadCalc(selectedId)
    } catch {
      toast({ title: '수량 업데이트 실패', variant: 'destructive' })
    }
  }

  const handleUpdateAvgPrice = async (ticker: string, avgPrice: number, holdingId?: number) => {
    if (!selectedId) return
    try {
      if (holdingId) {
        await portfolioApi.updateHolding(selectedId, holdingId, { avg_price: avgPrice })
      } else {
        await portfolioApi.addHolding(selectedId, { ticker, quantity: 0, avg_price: avgPrice })
      }
      await loadDetail(selectedId)
      loadCalc(selectedId)
    } catch {
      toast({ title: '평단가 업데이트 실패', variant: 'destructive' })
    }
  }

  const handleDeleteTicker = async (_ticker: string, targetId?: number, holdingId?: number) => {
    if (!selectedId) return
    try {
      if (targetId) await portfolioApi.deleteTarget(selectedId, targetId)
      if (holdingId) await portfolioApi.deleteHolding(selectedId, holdingId)
      await loadDetail(selectedId)
      loadCalc(selectedId)
      toast({ title: '종목이 삭제되었습니다' })
    } catch {
      toast({ title: '삭제 실패', variant: 'destructive' })
    }
  }

  if (!isAuthenticated) {
    return (
      <div className="text-center py-12">
        <h2 className="text-2xl font-bold mb-4">로그인이 필요합니다</h2>
        <p className="text-muted-foreground mb-6">
          포트폴리오 기능을 사용하려면 로그인해주세요
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

  // Detail view
  if (selectedId && detail) {
    return (
      <div className="space-y-6">
        <div className="flex items-center gap-4">
          <Button
            variant="ghost"
            size="sm"
            onClick={() => window.history.back()}
          >
            <ArrowLeft className="w-4 h-4 mr-1" />
            목록
          </Button>
          {isEditing ? (
            <Input
              className="text-xl font-bold border-none shadow-none h-auto py-1 px-2 max-w-xs"
              value={editName}
              onChange={(e) => setEditName(e.target.value)}
              onBlur={() => handleUpdateSettings('name', editName)}
              onKeyDown={(e) => {
                if (e.key === 'Enter') {
                  handleUpdateSettings('name', editName)
                  ;(e.target as HTMLInputElement).blur()
                }
              }}
            />
          ) : (
            <h2 className="text-xl font-bold py-1 px-2">{detail.name}</h2>
          )}
          <div className="flex items-center gap-2 ml-auto">
            {calcLoading && <span className="text-sm text-muted-foreground">계산 중...</span>}
            {isEditing && <AddTickerDialog onAdd={handleAddTicker} />}
            <Button
              variant="outline"
              size="sm"
              disabled={calcLoading}
              onClick={() => selectedId && Promise.all([loadDetail(selectedId), loadCalc(selectedId)])}
            >
              <RefreshCw className={`w-4 h-4 ${calcLoading ? 'animate-spin' : ''}`} />
            </Button>
            <Button
              variant={isEditing ? 'default' : 'outline'}
              size="sm"
              onClick={() => {
                if (isEditing && selectedId) {
                  Promise.all([loadDetail(selectedId), loadCalc(selectedId)])
                }
                setIsEditing(!isEditing)
              }}
            >
              {isEditing ? (
                <>
                  <Check className="w-4 h-4 mr-1" />
                  편집 완료
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

        {/* Settings bar */}
        <Card>
          <CardContent className="py-4">
            <div className="flex flex-wrap items-center gap-6">
              <div className="flex items-center gap-2">
                <Label className="text-sm whitespace-nowrap">계산 기준:</Label>
                {isEditing ? (
                  <div className="flex gap-1">
                    <Button
                      size="sm"
                      variant={detail.calculation_base === 'CURRENT_TOTAL' ? 'default' : 'outline'}
                      onClick={() => handleChangeBase('CURRENT_TOTAL')}
                    >
                      보유 총액
                    </Button>
                    <Button
                      size="sm"
                      variant={detail.calculation_base === 'TARGET_AMOUNT' ? 'default' : 'outline'}
                      onClick={() => handleChangeBase('TARGET_AMOUNT')}
                    >
                      목표 금액
                    </Button>
                  </div>
                ) : (
                  <span className="text-sm font-medium">
                    {detail.calculation_base === 'CURRENT_TOTAL' ? '보유 총액' : '목표 금액'}
                  </span>
                )}
              </div>

              {detail.calculation_base === 'CURRENT_TOTAL' && (
                <div className="flex items-center gap-2">
                  <Label className="text-sm whitespace-nowrap">예수금:</Label>
                  {isEditing ? (
                    <Input
                      type="text"
                      inputMode="numeric"
                      className="w-40 h-8"
                      value={editCash}
                      onChange={(e) => {
                        const raw = e.target.value.replace(/,/g, '')
                        if (raw === '' || /^\d+$/.test(raw)) {
                          setEditCash(raw === '' ? '' : formatNumber(parseInt(raw, 10)))
                        }
                      }}
                      onBlur={() => handleUpdateCash(editCash)}
                      onKeyDown={(e) => {
                        if (e.key === 'Enter') {
                          handleUpdateCash(editCash)
                          ;(e.target as HTMLInputElement).blur()
                        }
                      }}
                      placeholder="예: 500,000"
                    />
                  ) : (
                    <span className="font-mono text-sm">{editCash || '0'}원</span>
                  )}
                </div>
              )}

              {detail.calculation_base === 'TARGET_AMOUNT' && (
                <div className="flex items-center gap-2">
                  <Label className="text-sm whitespace-nowrap">목표 금액:</Label>
                  {isEditing ? (
                    <Input
                      type="number"
                      className="w-40 h-8"
                      value={editAmount}
                      onChange={(e) => setEditAmount(e.target.value)}
                      onBlur={() => handleUpdateSettings('target_total_amount', editAmount)}
                      onKeyDown={(e) => {
                        if (e.key === 'Enter') {
                          handleUpdateSettings('target_total_amount', editAmount)
                          ;(e.target as HTMLInputElement).blur()
                        }
                      }}
                      placeholder="예: 10000000"
                    />
                  ) : (
                    <span className="font-mono text-sm">
                      {editAmount ? formatNumber(parseFloat(editAmount)) : '0'}원
                    </span>
                  )}
                </div>
              )}

              {calcResult && (
                <div className="flex items-center gap-2 ml-auto">
                  <span className="text-sm text-muted-foreground">기준금액:</span>
                  <span className="font-mono font-semibold">
                    {formatNumber(calcResult.base_amount)}원
                  </span>
                </div>
              )}
            </div>
          </CardContent>
        </Card>

        {/* Weight warning */}
        {calcResult?.weight_warning && (
          <div className="flex items-center gap-2 px-4 py-3 bg-yellow-50 border border-yellow-200 rounded-md text-yellow-800 text-sm">
            <AlertTriangle className="w-4 h-4 flex-shrink-0" />
            {calcResult.weight_warning}
          </div>
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
            rows={calcResult.rows}
            totalWeight={calcResult.total_weight}
            totalHoldingAmount={calcResult.total_holding_amount}
            totalAdjustmentAmount={calcResult.total_adjustment_amount}
            totalProfitLossAmount={calcResult.total_profit_loss_amount}
            targetAllocations={detail.target_allocations}
            holdings={detail.holdings}
            isEditing={isEditing}
            onUpdateWeight={handleUpdateWeight}
            onUpdateQuantity={handleUpdateQuantity}
            onUpdateAvgPrice={handleUpdateAvgPrice}
            onDeleteTicker={handleDeleteTicker}
          />
        )}
      </div>
    )
  }

  // List view
  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-4">
          <h1 className="text-3xl font-bold">포트폴리오</h1>
          <Button variant="outline" size="sm" onClick={() => navigate('/portfolio/dashboard')}>
            <BarChart3 className="w-4 h-4 mr-1" />
            통합 대시보드
          </Button>
        </div>
        <Dialog open={createOpen} onOpenChange={setCreateOpen}>
          <DialogTrigger asChild>
            <Button>
              <Plus className="w-4 h-4 mr-2" />
              새 포트폴리오
            </Button>
          </DialogTrigger>
          <DialogContent>
            <DialogHeader>
              <DialogTitle>새 포트폴리오 생성</DialogTitle>
            </DialogHeader>
            <div className="space-y-4">
              <div className="space-y-2">
                <Label>포트폴리오 이름</Label>
                <Input
                  placeholder="포트폴리오 이름"
                  value={newName}
                  onChange={(e) => setNewName(e.target.value)}
                  onKeyDown={(e) => e.key === 'Enter' && handleCreate()}
                />
              </div>
              <div className="space-y-2">
                <Label>계산 기준</Label>
                <div className="flex gap-2">
                  <Button
                    size="sm"
                    variant={newBase === 'CURRENT_TOTAL' ? 'default' : 'outline'}
                    onClick={() => setNewBase('CURRENT_TOTAL')}
                    className="flex-1"
                  >
                    보유 총액
                  </Button>
                  <Button
                    size="sm"
                    variant={newBase === 'TARGET_AMOUNT' ? 'default' : 'outline'}
                    onClick={() => setNewBase('TARGET_AMOUNT')}
                    className="flex-1"
                  >
                    목표 금액
                  </Button>
                </div>
              </div>
              {newBase === 'TARGET_AMOUNT' && (
                <div className="space-y-2">
                  <Label>목표 금액</Label>
                  <Input
                    type="number"
                    placeholder="예: 10000000"
                    value={newAmount}
                    onChange={(e) => setNewAmount(e.target.value)}
                  />
                </div>
              )}
              <Button onClick={handleCreate} className="w-full">
                생성
              </Button>
            </div>
          </DialogContent>
        </Dialog>
      </div>

      {totalSummary && portfolios.length > 0 && (
        <Card>
          <CardContent className="py-4">
            <div className="flex flex-wrap items-center gap-6">
              <div>
                <div className="flex items-center gap-1">
                  <p className="text-sm text-muted-foreground">총 평가금액</p>
                  <button
                    onClick={toggleAmount}
                    className="text-muted-foreground hover:text-foreground transition-colors p-0.5"
                    aria-label={amountVisible ? '금액 숨기기' : '금액 보기'}
                  >
                    {amountVisible ? <Eye className="w-4 h-4" /> : <EyeOff className="w-4 h-4" />}
                  </button>
                </div>
                <p className="text-2xl font-bold font-mono">
                  {formatMaskedNumber(totalSummary.current_value, amountVisible)}{amountVisible && '원'}
                </p>
              </div>
              {totalSummary.daily && (
                <div>
                  <p className="text-sm text-muted-foreground">전일대비</p>
                  <p className={`text-lg font-mono font-semibold ${totalSummary.daily.amount >= 0 ? 'text-red-500' : 'text-blue-500'}`}>
                    {amountVisible ? (
                      <>
                        {totalSummary.daily.amount >= 0 ? '+' : ''}{formatNumber(totalSummary.daily.amount)}원
                        <span className="text-sm ml-1">
                          ({totalSummary.daily.rate >= 0 ? '+' : ''}{totalSummary.daily.rate.toFixed(2)}%)
                        </span>
                      </>
                    ) : (
                      '••••••'
                    )}
                  </p>
                </div>
              )}
              {totalSummary.ytd && (
                <div>
                  <p className="text-sm text-muted-foreground">YTD</p>
                  <p className={`text-lg font-mono font-semibold ${totalSummary.ytd.amount >= 0 ? 'text-red-500' : 'text-blue-500'}`}>
                    {totalSummary.ytd.rate >= 0 ? '+' : ''}{totalSummary.ytd.rate.toFixed(2)}%
                  </p>
                </div>
              )}
            </div>
          </CardContent>
        </Card>
      )}

      {portfolios.length === 0 ? (
        <Card>
          <CardContent className="py-12 text-center">
            <p className="text-muted-foreground mb-4">아직 포트폴리오가 없습니다</p>
            <Button onClick={() => setCreateOpen(true)}>
              <Plus className="w-4 h-4 mr-2" />
              첫 포트폴리오 만들기
            </Button>
          </CardContent>
        </Card>
      ) : (
        <DndContext sensors={sensors} collisionDetection={closestCenter} onDragEnd={handleDragEnd}>
          <SortableContext items={portfolios.map((p) => p.id)} strategy={rectSortingStrategy}>
            <div className="grid gap-4 md:grid-cols-2 lg:grid-cols-3">
              {portfolios.map((p) => (
                <SortablePortfolioCard
                  key={p.id}
                  portfolio={p}
                  onSelect={selectPortfolio}
                  onDelete={handleDelete}
                  onBackfill={handleBackfill}
                  backfillLoading={backfillLoading}
                  onDashboard={(id) => navigate(`/portfolio/${id}/dashboard`)}
                  amountVisible={amountVisible}
                  formatMaskedNumber={formatMaskedNumber}
                />
              ))}
            </div>
          </SortableContext>
        </DndContext>
      )}

      {/* Delete confirmation dialog */}
      <Dialog open={deleteTargetId !== null} onOpenChange={(open) => { if (!open) setDeleteTargetId(null) }}>
        <DialogContent className="max-w-sm">
          <DialogHeader>
            <DialogTitle>포트폴리오 삭제</DialogTitle>
            <DialogDescription>
              '{portfolios.find((p) => p.id === deleteTargetId)?.name}' 포트폴리오를 삭제하시겠습니까? 이 작업은 되돌릴 수 없습니다.
            </DialogDescription>
          </DialogHeader>
          <DialogFooter className="gap-2 sm:gap-0">
            <Button variant="outline" onClick={() => setDeleteTargetId(null)}>
              취소
            </Button>
            <Button variant="destructive" onClick={confirmDelete}>
              삭제
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  )
}
