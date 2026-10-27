import { lazy, Suspense, useEffect, useState } from 'react'
import { AlertCircle, BarChart3, ChevronLeft, ChevronRight, Table2 } from 'lucide-react'
import ReactMarkdown from 'react-markdown'
import { MARKDOWN_COMPONENTS, MARKDOWN_PLUGINS } from '@/lib/markdown'
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
  // 모든 영역이 같은 안내로 비었으면(분석하지 않는 종목·ETF) 영역마다 되풀이하지 않고 한 번만 보여 준다
  const notice = sharedNotice(layout, slots)
  if (notice) return <Notice status="empty" message={notice} />
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

function slotIds(node: LayoutNode): string[] {
  return node.type === 'slot' ? [node.id] : node.children.flatMap(slotIds)
}

function sharedNotice(layout: LayoutNode, slots: Record<string, SlotState>): string | undefined {
  const states = slotIds(layout).map((id) => slots[id])
  if (states.length < 2 || states.some((s) => s?.status !== 'empty' || !s.message)) return undefined
  const messages = new Set(states.map((s) => s.message))
  return messages.size === 1 ? states[0].message : undefined
}

function Notice({ status, message }: { status: SlotState['status']; message?: string }) {
  return (
    <div className={cn(
      'flex items-center gap-2 rounded-md bg-muted/50 px-3 py-4 text-sm',
      status === 'failed' ? 'text-destructive' : 'text-muted-foreground',
    )}>
      <AlertCircle className="w-4 h-4 shrink-0" />
      {message ?? (status === 'stopped' ? '중지했습니다' : '데이터가 없습니다')}
    </div>
  )
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
          <ReactMarkdown remarkPlugins={MARKDOWN_PLUGINS} components={MARKDOWN_COMPONENTS}>{content.text}</ReactMarkdown>
          {state.status === 'running' && <span className="inline-block w-1.5 h-4 align-middle bg-foreground/60 animate-pulse" />}
        </div>
      )
  } else if (state.status === 'empty' || state.status === 'failed' || state.status === 'stopped') {
    body = <Notice status={state.status} message={state.message} />
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
  const [panel, setPanel] = useState(0)
  const option = useChartOption(content, { panel })
  const [asTable, setAsTable] = useState(false)
  const isChart = content.view.kind !== 'table'
  const tableOrientation = content.view.kind === 'table' ? content.view.orientation
    : content.view.kind === 'radar' ? 'compare' : 'list'
  const panels = content.view.kind === 'candlestick' ? content.view.panels ?? [] : []
  const showChart = isChart && option && !asTable

  return (
    <div>
      {isChart && option && (
        <div className="flex items-center justify-end gap-3 -mt-1 mb-1">
          {/* 보조지표 칸은 하나씩 넘겨 본다 */}
          {showChart && panels.length > 1 && (
            <div className="flex items-center gap-1 text-xs text-muted-foreground">
              <button
                type="button"
                aria-label="이전 보조지표"
                onClick={() => setPanel((p) => (p + panels.length - 1) % panels.length)}
                className="hover:text-foreground"
              >
                <ChevronLeft className="w-3.5 h-3.5" />
              </button>
              <span className="min-w-[7rem] text-center">{panels[panel % panels.length].label}</span>
              <button
                type="button"
                aria-label="다음 보조지표"
                onClick={() => setPanel((p) => (p + 1) % panels.length)}
                className="hover:text-foreground"
              >
                <ChevronRight className="w-3.5 h-3.5" />
              </button>
            </div>
          )}
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
      {showChart
        ? (
          <Suspense fallback={<ChartSkeleton display={display} />}>
            <ChartView option={option} height={chartHeight(display, content)} />
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
