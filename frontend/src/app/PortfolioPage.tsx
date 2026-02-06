import { useEffect, useState, useCallback } from 'react'
import { Link } from 'react-router-dom'
import { Plus, Trash2, ArrowLeft, AlertTriangle } from 'lucide-react'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
  DialogTrigger,
} from '@/components/ui/dialog'
import { portfolioApi } from '@/lib/api'
import { useAuth } from '@/hooks/useAuth'
import { useToast } from '@/hooks/use-toast'
import type { Portfolio, PortfolioDetail, CalculationResult, CalculationBase } from '@/types/api'
import PortfolioTable from '@/components/PortfolioTable'
import AddTickerDialog from '@/components/AddTickerDialog'

function formatNumber(n: number): string {
  return new Intl.NumberFormat('ko-KR').format(Math.round(n))
}

export default function PortfolioPage() {
  const { isAuthenticated } = useAuth()
  const { toast } = useToast()

  const [portfolios, setPortfolios] = useState<Portfolio[]>([])
  const [loading, setLoading] = useState(true)
  const [selectedId, setSelectedId] = useState<number | null>(null)
  const [detail, setDetail] = useState<PortfolioDetail | null>(null)
  const [calcResult, setCalcResult] = useState<CalculationResult | null>(null)
  const [calcLoading, setCalcLoading] = useState(false)

  // Create dialog
  const [createOpen, setCreateOpen] = useState(false)
  const [newName, setNewName] = useState('')
  const [newBase, setNewBase] = useState<CalculationBase>('CURRENT_TOTAL')
  const [newAmount, setNewAmount] = useState('')

  // Settings editing
  const [editName, setEditName] = useState('')
  const [editAmount, setEditAmount] = useState('')

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
    fetchPortfolios()
  }, [isAuthenticated])

  const loadDetail = useCallback(async (id: number) => {
    try {
      const d = await portfolioApi.get(id)
      setDetail(d)
      setEditName(d.name)
      setEditAmount(d.target_total_amount ? String(d.target_total_amount) : '')
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

  const selectPortfolio = useCallback(async (id: number) => {
    setSelectedId(id)
    await Promise.all([loadDetail(id), loadCalc(id)])
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

  const handleDelete = async (id: number) => {
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

  const handleUpdateSettings = async (field: string, value: string) => {
    if (!selectedId || !detail) return
    try {
      const params: Record<string, string | number | null> = {}
      if (field === 'name') params.name = value
      if (field === 'target_total_amount') params.target_total_amount = value ? parseFloat(value) : null

      const updated = await portfolioApi.update(selectedId, params)
      setDetail({ ...detail, ...updated })
      setPortfolios(portfolios.map((p) => (p.id === selectedId ? { ...p, ...updated } : p)))

      if (field === 'target_total_amount') {
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

  const handleAddTicker = async (ticker: string, targetWeight: number, quantity: number) => {
    if (!selectedId) return
    try {
      await portfolioApi.addTarget(selectedId, { ticker, target_weight: targetWeight })
      if (quantity > 0) {
        await portfolioApi.addHolding(selectedId, { ticker, quantity })
      }
      await Promise.all([loadDetail(selectedId), loadCalc(selectedId)])
      toast({ title: '종목이 추가되었습니다' })
    } catch {
      toast({ title: '종목 추가 실패', variant: 'destructive' })
    }
  }

  const handleUpdateWeight = async (targetId: number, weight: number) => {
    if (!selectedId) return
    try {
      await portfolioApi.updateTarget(selectedId, targetId, { target_weight: weight })
      loadCalc(selectedId)
    } catch {
      toast({ title: '비중 업데이트 실패', variant: 'destructive' })
    }
  }

  const handleUpdateQuantity = async (holdingId: number, quantity: number) => {
    if (!selectedId) return
    try {
      await portfolioApi.updateHolding(selectedId, holdingId, { quantity })
      loadCalc(selectedId)
    } catch {
      toast({ title: '수량 업데이트 실패', variant: 'destructive' })
    }
  }

  const handleDeleteTicker = async (ticker: string, targetId?: number, holdingId?: number) => {
    if (!selectedId) return
    try {
      if (targetId) await portfolioApi.deleteTarget(selectedId, targetId)
      if (holdingId) await portfolioApi.deleteHolding(selectedId, holdingId)
      await Promise.all([loadDetail(selectedId), loadCalc(selectedId)])
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
            onClick={() => {
              setSelectedId(null)
              setDetail(null)
              setCalcResult(null)
            }}
          >
            <ArrowLeft className="w-4 h-4 mr-1" />
            목록
          </Button>
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
        </div>

        {/* Settings bar */}
        <Card>
          <CardContent className="py-4">
            <div className="flex flex-wrap items-center gap-6">
              <div className="flex items-center gap-2">
                <Label className="text-sm whitespace-nowrap">계산 기준:</Label>
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
              </div>

              {detail.calculation_base === 'TARGET_AMOUNT' && (
                <div className="flex items-center gap-2">
                  <Label className="text-sm whitespace-nowrap">목표 금액:</Label>
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

        {/* Actions */}
        <div className="flex items-center justify-between">
          <AddTickerDialog onAdd={handleAddTicker} />
          {calcLoading && <span className="text-sm text-muted-foreground">계산 중...</span>}
        </div>

        {/* Table */}
        {calcResult && (
          <PortfolioTable
            rows={calcResult.rows}
            totalWeight={calcResult.total_weight}
            totalHoldingAmount={calcResult.total_holding_amount}
            totalAdjustmentAmount={calcResult.total_adjustment_amount}
            targetAllocations={detail.target_allocations}
            holdings={detail.holdings}
            onUpdateWeight={handleUpdateWeight}
            onUpdateQuantity={handleUpdateQuantity}
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
        <h1 className="text-3xl font-bold">포트폴리오</h1>
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
        <div className="grid gap-4 md:grid-cols-2 lg:grid-cols-3">
          {portfolios.map((p) => (
            <Card
              key={p.id}
              className="cursor-pointer hover:shadow-md transition-shadow"
              onClick={() => selectPortfolio(p.id)}
            >
              <CardHeader className="flex flex-row items-center justify-between pb-2">
                <CardTitle className="text-lg">{p.name}</CardTitle>
                <Button
                  variant="ghost"
                  size="sm"
                  className="text-destructive hover:text-destructive"
                  onClick={(e) => {
                    e.stopPropagation()
                    handleDelete(p.id)
                  }}
                >
                  <Trash2 className="w-4 h-4" />
                </Button>
              </CardHeader>
              <CardContent>
                <div className="text-sm text-muted-foreground">
                  {p.calculation_base === 'CURRENT_TOTAL' ? '보유 총액 기준' : '목표 금액 기준'}
                  {p.target_total_amount && (
                    <span className="ml-2 font-mono">
                      ({formatNumber(p.target_total_amount)}원)
                    </span>
                  )}
                </div>
              </CardContent>
            </Card>
          ))}
        </div>
      )}
    </div>
  )
}
