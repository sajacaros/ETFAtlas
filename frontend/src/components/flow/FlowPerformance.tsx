import { useEffect, useState } from 'react'
import { Loader2 } from 'lucide-react'
import { flowApi } from '@/lib/api'
import type { FlowPerformance as Performance, FlowScore } from '@/types/api'
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table'
import { cn } from '@/lib/utils'

const signed = (v: number | null | undefined, unit = '%p') => (v == null ? '-' : `${v > 0 ? '+' : ''}${v.toFixed(2)}${unit}`)
const tone = (v: number | null | undefined) => (v == null || v === 0 ? '' : v > 0 ? 'text-red-500' : 'text-blue-500')

function ScoreCell({ score }: { score: FlowScore | null | undefined }) {
  if (!score) return <TableCell className="text-right text-muted-foreground">-</TableCell>
  return (
    <TableCell className="text-right" title={`${score.exit_date} 종가 기준 · 평균 ${signed(score.ret, '%')} (지수 ${signed(score.bench, '%')}) · 적중 ${score.hit}% · 이긴 종목 ${signed(score.won)} · 진 종목 ${signed(score.lost)} · ${score.n}종목`}>
      <span className={tone(score.excess)}>{signed(score.excess)}</span>
    </TableCell>
  )
}

/** 저장한 스크리너의 사후 채점: 기간별 요약과 기록별 초과수익 */
export function FlowPerformance({ flowId }: { flowId: number }) {
  const [data, setData] = useState<Performance | null>(null)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    setData(null)
    setError(null)
    flowApi.getPerformance(flowId).then(setData).catch(() => setError('성과를 불러오지 못했습니다'))
  }, [flowId])

  if (error) return <p className="text-sm text-destructive">{error}</p>
  if (!data) {
    return (
      <p className="flex items-center gap-2 text-sm text-muted-foreground">
        <Loader2 className="h-4 w-4 animate-spin" /> 시세를 받아 채점하는 중
      </p>
    )
  }
  if (!data.runs.length) {
    return (
      <p className="text-sm text-muted-foreground">
        아직 기록이 없습니다. 저장한 스크리너를 고치지 않고 실행하거나 자동 실행을 켜면 그날 결과 노드에 닿은 종목이 기록됩니다.
      </p>
    )
  }

  const bench = data.benchmark.name
  return (
    <div className="space-y-4">
      <p className="text-xs text-muted-foreground">
        기록한 날 고른 종목을 <b>다음 거래일 종가</b>에 같은 금액으로 샀다고 보고, N거래일 뒤 수익률을 {bench}와 비교합니다.
        초과수익 = 평균 수익률 − {bench} 수익률. 매일 기록하면 기간이 겹쳐 기록 수만큼 독립적인 결과는 아닙니다.
        {data.as_of && ` 시세 기준일 ${data.as_of}.`}
      </p>

      <div className="grid gap-2 sm:grid-cols-3">
        {data.horizons.map((h) => {
          const s = data.summary[String(h)]
          return (
            <div key={h} className="rounded-lg border bg-card p-3">
              <div className="text-xs text-muted-foreground">{h}거래일 뒤</div>
              {s ? (
                <>
                  <div className={cn('text-xl font-semibold', tone(s.excess))}>{signed(s.excess)}</div>
                  <div className="mt-1 space-y-0.5 text-xs text-muted-foreground">
                    <div>평균 수익률 {signed(s.ret, '%')}</div>
                    <div>지수를 이긴 기록 {s.beat_runs}% · 종목 적중 {s.hit}%</div>
                    <div title="이긴 종목·진 종목의 평균 초과수익. 손익비 = 이긴 폭 ÷ 진 폭">
                      이긴 종목 {signed(s.won)} · 진 종목 {signed(s.lost)}
                      {s.payoff != null && ` · 손익비 ${s.payoff.toFixed(2)}`}
                    </div>
                    <div>가장 나빴던 기록 <span className={tone(s.worst)}>{signed(s.worst)}</span></div>
                    <div>채점된 기록 {s.runs}개</div>
                  </div>
                </>
              ) : (
                <div className="mt-1 text-sm text-muted-foreground">아직 {h}거래일이 지난 기록이 없습니다</div>
              )}
            </div>
          )
        })}
      </div>

      <div className="overflow-x-auto">
        <Table>
          <TableHeader>
            <TableRow>
              <TableHead>기록일</TableHead>
              <TableHead className="text-right">종목</TableHead>
              {data.horizons.map((h) => <TableHead key={h} className="text-right">{h}일</TableHead>)}
              <TableHead className="text-right">지금까지</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {data.runs.map((r) => (
              <TableRow key={r.run_date}>
                <TableCell className="whitespace-nowrap">
                  {r.run_date}
                  <span className="ml-1.5 text-xs text-muted-foreground">{r.trigger === 'schedule' ? '자동' : '수동'}</span>
                </TableCell>
                <TableCell className="text-right">{r.count}</TableCell>
                {data.horizons.map((h) => <ScoreCell key={h} score={r.horizons[String(h)]} />)}
                <ScoreCell score={r.so_far} />
              </TableRow>
            ))}
          </TableBody>
        </Table>
      </div>
      <p className="text-xs text-muted-foreground">칸에 마우스를 올리면 청산일·평균 수익률·적중률을 볼 수 있습니다. 투자 권유가 아닙니다.</p>
    </div>
  )
}
