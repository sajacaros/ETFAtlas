import { lazy, Suspense, useEffect, useState } from 'react'
import { AlertCircle, BarChart3, Table2 } from 'lucide-react'
import ReactMarkdown from 'react-markdown'
import { MARKDOWN_PLUGINS } from '@/lib/markdown'
import type { DataContent, LayoutNode, SlotContent, SlotState } from '@/types/api'
import { chatApi } from '@/lib/api'
import { cn } from '@/lib/utils'
import { DataTable } from './DataTable'
import { chartHeight, useChartOption } from './useChartOption'

const ChartView = lazy(() => import('./ChartView'))

type SlotNode = Extract<LayoutNode, { type: 'slot' }>

const ROW_COLUMNS: Record<number, string> = { 1: 'md:grid-cols-1', 2: 'md:grid-cols-2', 3: 'md:grid-cols-3' }

const PROSE = 'prose prose-sm dark:prose-invert max-w-none prose-table:text-sm prose-td:px-2 prose-td:py-1 prose-th:px-2 prose-th:py-1 prose-th:text-left'

// 가져온 슬롯 내용 — 스트림이 끝나 대화 목록으로 옮겨 다시 그려져도 또 받지 않는다
const contentCache = new Map<string, SlotContent>()

/** 답변 화면: 레이아웃 트리를 그리고, 각 영역은 완료되면 내용을 가져와 채운다 */
export function AnswerView({ chatLogId, layout, slots }: {
  chatLogId: number
  layout: LayoutNode
  slots: Record<string, SlotState>
}) {
  const render = (node: LayoutNode, key: string): JSX.Element => {
    if (node.type === 'slot') {
      return <SlotView key={key} chatLogId={chatLogId} node={node} state={slots[node.id] ?? { status: 'pending' }} />
    }
    if (node.type === 'row') {
      return (
        <div key={key} className={cn('grid grid-cols-1 gap-3', ROW_COLUMNS[node.children.length] ?? 'md:grid-cols-3')}>
          {node.children.map((child, i) => render(child, `${key}.${i}`))}
        </div>
      )
    }
    return (
      <div key={key} className="flex flex-col gap-3">
        {node.children.map((child, i) => render(child, `${key}.${i}`))}
      </div>
    )
  }
  return render(layout, 'root')
}

function useSlotContent(chatLogId: number, node: SlotNode, state: SlotState): SlotContent | undefined {
  const cacheKey = `${chatLogId}:${node.id}`
  const [content, setContent] = useState<SlotContent | undefined>(() => contentCache.get(cacheKey))
  // 텍스트 영역은 흘려받은 본문이 이미 있다
  const streamed = state.text !== undefined
  const needsFetch = state.status === 'complete' && !content && !streamed

  useEffect(() => {
    if (!needsFetch) return
    let cancelled = false
    chatApi.getSlot(chatLogId, node.id)
      .then((slot) => {
        if (!slot.content) return
        contentCache.set(cacheKey, slot.content)
        if (!cancelled) setContent(slot.content)
      })
      .catch(() => { /* 영역만 비워 둔다 — 다시 열면 다시 시도한다 */ })
    return () => { cancelled = true }
  }, [needsFetch, chatLogId, node.id, cacheKey])

  if (content) return content
  if (streamed) return { type: node.slot === 'markdown' ? 'markdown' : 'text', text: state.text ?? '' }
  return undefined
}

function SlotView({ chatLogId, node, state }: { chatLogId: number; node: SlotNode; state: SlotState }) {
  const content = useSlotContent(chatLogId, node, state)
  const textSlot = node.slot === 'text' || node.slot === 'markdown'

  let body: JSX.Element
  if (content) {
    body = content.type === 'data'
      ? <DataSlot content={content} display={node.display} />
      : (
        <div className={PROSE}>
          <ReactMarkdown remarkPlugins={MARKDOWN_PLUGINS}>{content.text}</ReactMarkdown>
          {state.status === 'running' && <span className="inline-block w-1.5 h-4 align-middle bg-foreground/60 animate-pulse" />}
        </div>
      )
  } else if (state.status === 'empty' || state.status === 'failed' || state.status === 'stopped') {
    body = (
      <div className={cn(
        'flex items-center gap-2 rounded-md bg-muted/50 px-3 py-4 text-sm',
        state.status === 'failed' ? 'text-destructive' : 'text-muted-foreground',
      )}>
        <AlertCircle className="w-4 h-4 shrink-0" />
        {state.message ?? (state.status === 'stopped' ? '중지했습니다' : '데이터가 없습니다')}
      </div>
    )
  } else {
    body = <Skeleton node={node} />
  }

  // 해설·마크다운은 테두리 없이 본문처럼, 데이터 영역은 카드로
  return (
    <section className={cn('min-w-0', !textSlot && 'rounded-md border bg-background p-3')}>
      {node.title && <h3 className="mb-2 text-sm font-semibold">{node.title}</h3>}
      {body}
    </section>
  )
}

function DataSlot({ content, display }: { content: DataContent; display: string }) {
  const option = useChartOption(content)
  const [asTable, setAsTable] = useState(false)
  const isChart = content.view.kind !== 'table'
  const tableOrientation = content.view.kind === 'table' ? content.view.orientation
    : content.view.kind === 'radar' ? 'compare' : 'list'

  return (
    <div>
      {isChart && option && (
        <div className="flex justify-end -mt-1 mb-1">
          <button
            type="button"
            onClick={() => setAsTable((v) => !v)}
            className="flex items-center gap-1 text-xs text-muted-foreground hover:text-foreground"
          >
            {asTable ? <BarChart3 className="w-3.5 h-3.5" /> : <Table2 className="w-3.5 h-3.5" />}
            {asTable ? '차트로 보기' : '표로 보기'}
          </button>
        </div>
      )}
      {/* 모르는 차트이거나 그리지 못하면 같은 데이터를 표로 */}
      {isChart && option && !asTable
        ? (
          <Suspense fallback={<ChartSkeleton display={display} />}>
            <ChartView option={option} height={chartHeight(display)} />
          </Suspense>
        )
        : <DataTable dataset={content.dataset} orientation={tableOrientation} />}
      {(content.notes.length > 0 || content.sources.length > 0) && (
        <div className="mt-2 space-y-0.5 text-xs text-muted-foreground">
          {content.notes.map((note) => <p key={note}>{note}</p>)}
          {content.sources.length > 0 && (
            <p>
              출처: {content.sources.map((s) => (s.as_of ? `${s.label} (기준 ${s.as_of})` : s.label)).join(', ')}
            </p>
          )}
        </div>
      )}
    </div>
  )
}

function ChartSkeleton({ display }: { display: string }) {
  return <div className="w-full rounded bg-muted animate-pulse" style={{ height: chartHeight(display) }} />
}

function Skeleton({ node }: { node: SlotNode }) {
  if (node.slot === 'chart') return <ChartSkeleton display={node.display} />
  const lines = node.slot === 'table' ? 5 : 3
  return (
    <div className="space-y-2">
      {Array.from({ length: lines }, (_, i) => (
        <div key={i} className={cn('h-4 rounded bg-muted animate-pulse', i === lines - 1 ? 'w-2/3' : 'w-full')} />
      ))}
    </div>
  )
}
