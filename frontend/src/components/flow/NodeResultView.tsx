import type { FlowNodeResult } from '@/types/api'
import { DataTable } from '@/components/answer/DataTable'
import { formatValue } from '@/components/answer/format'

/** 노드 하나의 실행 결과: 노트, AI 근거(있으면 카드로), 표 */
export function NodeResultView({ result }: { result: FlowNodeResult }) {
  const { dataset } = result
  const aiField = dataset.fields.find((f) => f.key === 'ai')
  const tableDataset = aiField ? { ...dataset, fields: dataset.fields.filter((f) => f.key !== 'ai') } : dataset
  const metrics = tableDataset.fields.filter((f) => !['code', 'name', 'as_of'].includes(f.key)).slice(0, 4)

  return (
    <div className="space-y-4">
      <div className="text-sm">
        <span className="text-lg font-semibold">{result.count.toLocaleString()}</span>
        <span className="ml-1 text-muted-foreground">종목 · {result.seconds}초</span>
      </div>
      {result.notes.length > 0 && (
        <ul className="space-y-1 rounded-md bg-muted/60 p-3 text-xs text-muted-foreground">
          {result.notes.map((n) => <li key={n}>{n}</li>)}
        </ul>
      )}
      {aiField && (
        <div className="space-y-2">
          {dataset.rows.map((row) => (
            <div key={String(row.code)} className="rounded-lg border p-3">
              <div className="flex items-baseline justify-between gap-2">
                <span className="font-medium">{String(row.name)}</span>
                <span className="text-xs text-muted-foreground">{String(row.code)}</span>
              </div>
              <div className="mt-1 flex flex-wrap gap-x-3 gap-y-0.5 text-xs text-muted-foreground">
                {metrics.filter((f) => row[f.key] != null).map((f) => (
                  <span key={f.key}>{f.label} <span className="tabular-nums text-foreground">{formatValue(row[f.key], f.format)}</span></span>
                ))}
              </div>
              <p className="mt-2 whitespace-pre-line text-sm leading-relaxed">{String(row.ai || '')}</p>
            </div>
          ))}
        </div>
      )}
      {dataset.rows.length > 0 ? (
        <DataTable dataset={tableDataset} />
      ) : (
        <p className="text-sm text-muted-foreground">조건을 통과한 종목이 없습니다.</p>
      )}
      {dataset.rows.length > 0 && (
        <p className="text-xs text-muted-foreground">
          시세는 yfinance 일봉(수정주가) 기준입니다. 연구·교육용 결과이며 투자 권유가 아닙니다.
        </p>
      )}
    </div>
  )
}
