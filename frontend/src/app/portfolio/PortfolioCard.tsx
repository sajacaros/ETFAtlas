import { Trash2, BarChart3, GripVertical, Copy, Layers } from 'lucide-react'
import { useSortable } from '@dnd-kit/sortable'
import { CSS } from '@dnd-kit/utilities'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { Switch } from '@/components/ui/switch'
import { Button } from '@/components/ui/button'
import { AccountTypeBadges } from '@/components/AccountType'
import type { Portfolio } from '@/types/api'
import { PortfolioCardStats } from './PortfolioStats'

export default function SortablePortfolioCard({
  portfolio: p,
  onSelect,
  onDuplicate,
  onComposition,
  onDelete,
  onToggleSnapshot,
  onDashboard,
  amountVisible,
}: {
  portfolio: Portfolio
  onSelect: (id: number) => void
  onDuplicate: (id: number) => void
  onComposition: (id: number) => void
  onDelete: (id: number) => void
  onToggleSnapshot: (id: number, enabled: boolean) => void
  onDashboard: (id: number) => void
  amountVisible: boolean
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
      <CardHeader className="flex flex-row items-center justify-between gap-2 pb-2">
        <div className="flex items-center gap-1 min-w-0 flex-1">
          <button
            className="cursor-grab active:cursor-grabbing touch-none p-1 -ml-1 text-muted-foreground hover:text-foreground"
            {...attributes}
            {...listeners}
            onClick={(e) => e.stopPropagation()}
          >
            <GripVertical className="w-4 h-4" />
          </button>
          <CardTitle className="text-lg min-w-0 truncate" title={p.name}>{p.name}</CardTitle>
          <AccountTypeBadges types={p.account_types} className="ml-1 shrink-0 flex-nowrap" compact />
        </div>
        <div className="flex items-center shrink-0 -mr-2">
          <Button
            variant="ghost"
            size="sm"
            className="h-8 w-8 p-0"
            title="구성종목 보기"
            onClick={(e) => {
              e.stopPropagation()
              onComposition(p.id)
            }}
          >
            <Layers className="w-4 h-4" />
          </Button>
          <Button
            variant="ghost"
            size="sm"
            className="h-8 w-8 p-0"
            title="복제"
            onClick={(e) => {
              e.stopPropagation()
              onDuplicate(p.id)
            }}
          >
            <Copy className="w-4 h-4" />
          </Button>
          <Button
            variant="ghost"
            size="sm"
            className="h-8 w-8 p-0 text-destructive hover:text-destructive"
            title="삭제"
            onClick={(e) => {
              e.stopPropagation()
              onDelete(p.id)
            }}
          >
            <Trash2 className="w-4 h-4" />
          </Button>
        </div>
      </CardHeader>
      <CardContent>
        <PortfolioCardStats portfolio={p} amountVisible={amountVisible} />

        {/* 대시보드 버튼(h-9)이 없어도 높이가 같도록 고정 */}
        <div className="flex items-center justify-between mt-3 h-9">
          <div className="flex items-center gap-2">
            <Switch
              checked={p.snapshot_enabled}
              onCheckedChange={(checked) => {
                onToggleSnapshot(p.id, checked)
              }}
              onClick={(e) => e.stopPropagation()}
            />
            <span className="text-xs text-muted-foreground">
              {p.snapshot_enabled ? '스냅샷 활성' : '스냅샷 비활성'}
            </span>
          </div>
          {/* 스냅샷을 끄면 기록이 지워져 대시보드에 보여줄 추이가 없다 */}
          {p.snapshot_enabled && (
            <Button
              variant="outline"
              size="sm"
              onClick={(e) => {
                e.stopPropagation()
                onDashboard(p.id)
              }}
            >
              <BarChart3 className="w-4 h-4 mr-1" />
              대시보드
            </Button>
          )}
        </div>
      </CardContent>
    </Card>
  )
}
