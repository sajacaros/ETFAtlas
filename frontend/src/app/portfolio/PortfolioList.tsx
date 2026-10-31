import { useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { Plus, BarChart3 } from 'lucide-react'
import { Card, CardContent } from '@/components/ui/card'
import { Button } from '@/components/ui/button'
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog'
import {
  DndContext,
  closestCenter,
  PointerSensor,
  useSensor,
  useSensors,
  DragEndEvent,
} from '@dnd-kit/core'
import { SortableContext, rectSortingStrategy } from '@dnd-kit/sortable'
import { useAmountVisibility } from '@/hooks/useAmountVisibility'
import type { DashboardSummary, Portfolio } from '@/types/api'
import SortablePortfolioCard from './PortfolioCard'
import CreatePortfolioDialog, { type NewPortfolioParams } from './CreatePortfolioDialog'
import TotalSummaryCard from './TotalSummaryCard'
import { formatShortDateTime } from './format'

/** 포트폴리오 목록 화면 — 카드는 끌어서 순서를 바꾼다. 삭제·스냅샷 끄기는 확인을 받고 부른다 */
export default function PortfolioList({
  portfolios,
  totalSummary,
  onSelect,
  onCreate,
  onDuplicate,
  onDelete,
  onSnapshotToggle,
  onReorder,
}: {
  portfolios: Portfolio[]
  totalSummary: DashboardSummary | null
  onSelect: (id: number) => void
  onCreate: (params: NewPortfolioParams) => Promise<boolean>
  onDuplicate: (id: number) => void
  onDelete: (id: number) => void
  onSnapshotToggle: (id: number, enabled: boolean) => void
  onReorder: (activeId: number, overId: number) => void
}) {
  const navigate = useNavigate()
  const { visible: amountVisible, toggle: toggleAmount } = useAmountVisibility()
  const [createOpen, setCreateOpen] = useState(false)
  const [deleteTargetId, setDeleteTargetId] = useState<number | null>(null)
  const [snapshotOffTargetId, setSnapshotOffTargetId] = useState<number | null>(null)

  const sensors = useSensors(
    useSensor(PointerSensor, { activationConstraint: { distance: 8 } })
  )

  const handleDragEnd = (event: DragEndEvent) => {
    const { active, over } = event
    if (!over || active.id === over.id) return
    onReorder(Number(active.id), Number(over.id))
  }

  const handleToggleSnapshot = (id: number, enabled: boolean) => {
    // 끄면 쌓인 기록이 모두 지워지므로 먼저 확인받는다
    if (!enabled) {
      setSnapshotOffTargetId(id)
      return
    }
    onSnapshotToggle(id, true)
  }

  // 가격 수집 시각은 모든 포트폴리오에 같은 값이라 목록 위에 한 번만 보여준다
  const priceUpdatedRaw = portfolios.find((p) => p.current_value_updated_at)?.current_value_updated_at
  const priceUpdatedAt = priceUpdatedRaw ? formatShortDateTime(priceUpdatedRaw) : null

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <div className="flex items-center gap-4">
          <h1 className="text-2xl font-bold whitespace-nowrap">포트폴리오</h1>
          <Button variant="outline" size="sm" onClick={() => navigate('/portfolio/dashboard')}>
            <BarChart3 className="w-4 h-4 mr-1" />
            통합 대시보드
          </Button>
        </div>
        <CreatePortfolioDialog open={createOpen} onOpenChange={setCreateOpen} onCreate={onCreate} />
      </div>
      {priceUpdatedAt && (
        <p className="text-xs text-muted-foreground -mt-2" title="평가금액 계산에 쓴 ETF 가격을 마지막으로 수집한 시각">
          가격 기준 {priceUpdatedAt}
        </p>
      )}

      {totalSummary && portfolios.length > 0 && (
        <TotalSummaryCard summary={totalSummary} amountVisible={amountVisible} onToggleAmount={toggleAmount} />
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
                  onSelect={onSelect}
                  onDuplicate={onDuplicate}
                  onComposition={(id) => navigate(`/composition?portfolio=${id}`)}
                  onDelete={setDeleteTargetId}
                  onToggleSnapshot={handleToggleSnapshot}
                  onDashboard={(id) => navigate(`/portfolio/${id}/dashboard`)}
                  amountVisible={amountVisible}
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
            <Button
              variant="destructive"
              onClick={() => {
                const id = deleteTargetId
                setDeleteTargetId(null)
                if (id !== null) onDelete(id)
              }}
            >
              삭제
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
      <Dialog open={snapshotOffTargetId !== null} onOpenChange={(open) => { if (!open) setSnapshotOffTargetId(null) }}>
        <DialogContent className="max-w-sm">
          <DialogHeader>
            <DialogTitle>스냅샷 끄기</DialogTitle>
            <DialogDescription>
              '{portfolios.find((p) => p.id === snapshotOffTargetId)?.name}'의 스냅샷을 끄면 지금까지 쌓인 평가금액 기록이 모두 삭제되고, 대시보드와 통합 대시보드에서도 사라집니다. 다시 켜면 그날부터 새로 쌓입니다. 이 작업은 되돌릴 수 없습니다.
            </DialogDescription>
          </DialogHeader>
          <DialogFooter className="gap-2 sm:gap-0">
            <Button variant="outline" onClick={() => setSnapshotOffTargetId(null)}>
              취소
            </Button>
            <Button
              variant="destructive"
              onClick={() => {
                const id = snapshotOffTargetId
                setSnapshotOffTargetId(null)
                if (id !== null) onSnapshotToggle(id, false)
              }}
            >
              스냅샷 끄기
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  )
}
