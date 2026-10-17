import { Plus, Star } from 'lucide-react'
import type { FlowCatalog, FlowNodeSpec, FlowTemplate } from '@/types/api'
import { cn } from '@/lib/utils'
import { CATEGORIES, CATEGORY_ORDER } from './categories'

export const DRAG_TYPE = 'application/x-flow-node'

interface Props {
  catalog: FlowCatalog
  onAddNode: (spec: FlowNodeSpec) => void
  onLoadTemplate: (template: FlowTemplate) => void
}

/** 왼쪽 팔레트: 추천 조합과 단계별 노드. 누르면 캔버스에 추가하고, 끌어다 놓을 수도 있다 */
export function NodePalette({ catalog, onAddNode, onLoadTemplate }: Props) {
  const typeLabel = (type: string) => catalog.nodes.find((n) => n.type === type)?.label ?? type
  return (
    <div className="space-y-5 text-sm">
      <section>
        <h3 className="mb-2 flex items-center gap-1.5 text-xs font-semibold text-muted-foreground">
          <Star className="h-3.5 w-3.5" /> 추천 조합
        </h3>
        <div className="space-y-1.5">
          {catalog.templates.map((t) => (
            <button
              key={t.key}
              type="button"
              onClick={() => onLoadTemplate(t)}
              className="w-full rounded-md border px-2.5 py-2 text-left transition-colors hover:bg-muted"
              title={t.description}
            >
              <div className="font-medium">{t.name}</div>
              <div className="truncate text-xs text-muted-foreground">
                {t.graph.nodes.map((n) => typeLabel(n.type)).join(' → ')}
              </div>
            </button>
          ))}
        </div>
      </section>
      {CATEGORY_ORDER.map((category) => {
        const nodes = catalog.nodes.filter((n) => n.category === category)
        if (!nodes.length) return null
        const meta = CATEGORIES[category]
        return (
          <section key={category}>
            <h3 className="mb-2 flex items-center gap-1.5 text-xs font-semibold text-muted-foreground">
              <span className={cn('flex h-4 w-4 items-center justify-center rounded text-[10px] text-white', meta.dot)}>{meta.step}</span>
              {meta.label}
            </h3>
            <div className="space-y-1.5">
              {nodes.map((spec) => (
                <button
                  key={spec.type}
                  type="button"
                  draggable
                  onDragStart={(e) => {
                    e.dataTransfer.setData(DRAG_TYPE, spec.type)
                    e.dataTransfer.effectAllowed = 'move'
                  }}
                  onClick={() => onAddNode(spec)}
                  className="flex w-full items-center gap-2 rounded-md border px-2.5 py-2 text-left transition-colors hover:bg-muted"
                  title={spec.description}
                >
                  <span className={cn('h-2 w-2 shrink-0 rounded-full', meta.dot)} />
                  <span className="flex-1 truncate font-medium">{spec.label}</span>
                  <Plus className="h-3.5 w-3.5 shrink-0 text-muted-foreground" />
                </button>
              ))}
            </div>
          </section>
        )
      })}
    </div>
  )
}
