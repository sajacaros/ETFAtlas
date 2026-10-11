import { useMemo, useState } from 'react'
import { ArrowDown, ArrowUp } from 'lucide-react'
import type { DataRow, Dataset } from '@/types/api'
import { cn } from '@/lib/utils'
import { cellFormat, formatValue } from './format'

/** 데이터 슬롯의 표. list는 행이 대상(정렬 가능), compare는 행이 항목이고 열이 대상(행마다 서식·우열 강조) */
export function DataTable({ dataset, orientation = 'list' }: { dataset: Dataset; orientation?: 'list' | 'compare' }) {
  const [sort, setSort] = useState<{ key: string; desc: boolean } | null>(null)
  const [first, ...rest] = dataset.fields

  const rows = useMemo(() => {
    if (!sort || orientation === 'compare') return dataset.rows
    const value = (r: DataRow) => r[sort.key]
    return [...dataset.rows].sort((a, b) => {
      const av = value(a)
      const bv = value(b)
      if (av === bv) return 0
      if (av === null || av === undefined) return 1  // 빈 값은 항상 뒤로
      if (bv === null || bv === undefined) return -1
      const cmp = typeof av === 'number' && typeof bv === 'number' ? av - bv : String(av).localeCompare(String(bv), 'ko')
      return sort.desc ? -cmp : cmp
    })
  }, [dataset.rows, sort, orientation])

  const toggleSort = (key: string) => {
    if (orientation === 'compare') return
    setSort((prev) => (prev?.key === key ? { key, desc: !prev.desc } : { key, desc: true }))
  }

  // compare 표에서 행마다 가장 좋은 값의 열
  const bestKey = (row: DataRow): string | null => {
    if (!row._better) return null
    const numeric = rest.filter((f) => typeof row[f.key] === 'number')
    if (numeric.length < 2) return null
    const pick = row._better === 'high' ? Math.max : Math.min
    const best = pick(...numeric.map((f) => row[f.key] as number))
    return numeric.find((f) => row[f.key] === best)?.key ?? null
  }

  return (
    <div className="overflow-x-auto">
      <table className="w-full text-sm">
        <thead>
          <tr className="border-b text-muted-foreground">
            {dataset.fields.map((f, i) => (
              <th
                key={f.key}
                onClick={() => toggleSort(f.key)}
                className={cn(
                  'px-2 py-1.5 font-medium whitespace-nowrap',
                  i === 0 ? 'sticky left-0 bg-background text-left'
                    : orientation === 'list' && (f.format === 'text' || f.format === 'date') ? 'text-left' : 'text-right',
                  orientation === 'list' && 'cursor-pointer select-none hover:text-foreground',
                )}
              >
                {f.label}
                {sort?.key === f.key && (sort.desc
                  ? <ArrowDown className="inline w-3 h-3 ml-0.5" />
                  : <ArrowUp className="inline w-3 h-3 ml-0.5" />)}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {rows.map((row, ri) => {
            const best = orientation === 'compare' ? bestKey(row) : null
            return (
              <tr key={ri} className="border-b last:border-0">
                <td className="sticky left-0 bg-background px-2 py-1.5 whitespace-nowrap">
                  {formatValue(row[first.key], cellFormat(row, first))}
                </td>
                {rest.map((f) => {
                  const format = cellFormat(row, f)
                  const raw = row._raw?.[f.key]
                  return (
                    <td
                      key={f.key}
                      className={cn(
                        'px-2 py-1.5 whitespace-nowrap tabular-nums',
                        // compare 표는 열이 대상이라 서식과 관계없이 열 제목과 같이 오른쪽에 맞춘다
                        orientation === 'list' && (format === 'text' || format === 'date') ? 'text-left' : 'text-right',
                        best === f.key && 'font-semibold text-primary',
                      )}
                    >
                      {row._raw ? (
                        // 점수화한 값: 원값을 보이고 점수는 곁들인다
                        <>
                          {formatValue(raw, format)}
                          <span className="ml-1 text-xs text-muted-foreground">({formatValue(row[f.key], 'number')}점)</span>
                        </>
                      ) : formatValue(row[f.key], format)}
                    </td>
                  )
                })}
              </tr>
            )
          })}
        </tbody>
      </table>
    </div>
  )
}
