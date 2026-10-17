import { Handle, Position, type Node, type NodeProps } from '@xyflow/react'
import { AlertCircle, Check, Loader2, MinusCircle } from 'lucide-react'
import type { FlowNodeSpec } from '@/types/api'
import { cn } from '@/lib/utils'
import { CATEGORIES } from './categories'

export type RunState = 'idle' | 'running' | 'done' | 'error' | 'skipped'

export type FlowNodeData = {
  spec: FlowNodeSpec
  params: Record<string, unknown>
  // 아래는 실행 상태 — 저장하지 않고 화면에 그릴 때만 붙인다
  state?: RunState
  badge?: string
  message?: string
}

export type FlowCanvasNode = Node<FlowNodeData, 'stock'>

/** 캔버스의 노드 카드: 아이콘·이름·단계, 실행 뒤에는 건수 배지나 오류 */
export function FlowNodeCard({ data, selected }: NodeProps<FlowCanvasNode>) {
  const { spec, state = 'idle', badge, message } = data
  const category = CATEGORIES[spec.category]
  return (
    <div
      className={cn(
        'w-48 rounded-lg border border-l-4 bg-card px-3 py-2 shadow-md transition-shadow',
        category.bar,
        selected && 'ring-2 ring-primary/60',
        state === 'error' && 'border-destructive',
      )}
    >
      {spec.max_inputs !== 0 && <Handle type="target" position={Position.Left} className="!h-2.5 !w-2.5 !bg-muted-foreground" />}
      <div className="flex items-center gap-1.5 text-sm font-semibold">
        <span aria-hidden>{spec.icon}</span>
        <span className="truncate">{spec.label}</span>
      </div>
      <div className="text-xs text-muted-foreground">{category.label}</div>
      {state !== 'idle' && (
        <div
          className={cn(
            'mt-1.5 inline-flex max-w-full items-center gap-1 rounded-md px-1.5 py-0.5 text-xs',
            state === 'done' && 'bg-emerald-500/10 text-emerald-700 dark:text-emerald-400',
            state === 'running' && 'bg-muted text-muted-foreground',
            state === 'error' && 'bg-destructive/10 text-destructive',
            state === 'skipped' && 'bg-muted text-muted-foreground',
          )}
          title={message}
        >
          {state === 'done' && <Check className="h-3 w-3 shrink-0" />}
          {state === 'running' && <Loader2 className="h-3 w-3 shrink-0 animate-spin" />}
          {state === 'error' && <AlertCircle className="h-3 w-3 shrink-0" />}
          {state === 'skipped' && <MinusCircle className="h-3 w-3 shrink-0" />}
          <span className="truncate">{state === 'done' ? badge : state === 'running' ? message || '실행 중' : state === 'error' ? '오류' : '건너뜀'}</span>
        </div>
      )}
      {spec.category !== 'result' && <Handle type="source" position={Position.Right} className="!h-2.5 !w-2.5 !bg-muted-foreground" />}
    </div>
  )
}
