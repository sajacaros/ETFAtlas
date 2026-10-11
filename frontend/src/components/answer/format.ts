import type { DataField, DataRow, ValueFormat } from '@/types/api'
import { formatKrwAmount, formatNumber } from '@/lib/utils'

/** 데이터셋의 원시값을 서식 힌트대로 표시한다 (백엔드는 숫자만 보낸다) */
export function formatValue(value: unknown, format: ValueFormat): string {
  if (value === null || value === undefined || value === '') return '-'
  if (typeof value !== 'number') return String(value)
  switch (format) {
    case 'percent':
      return `${value.toFixed(2)}%`
    case 'krw':
      return formatKrwAmount(value)
    case 'price':
      return `${Math.round(value).toLocaleString('ko-KR')}원`
    case 'number':
      return formatNumber(value)
    default:
      return String(value)
  }
}

/** 행 서식(_format)이 열 서식보다 우선 — 비교표는 행마다 단위가 다르다 */
export function cellFormat(row: DataRow, field: DataField): ValueFormat {
  return row._format ?? field.format
}

/** 축 눈금용 짧은 서식 */
export function axisFormatter(format: ValueFormat): (value: number) => string {
  if (format === 'percent') return (v) => `${v}%`
  if (format === 'krw') return (v) => formatKrwAmount(v)
  return (v) => v.toLocaleString('ko-KR')
}
