import { type ClassValue, clsx } from 'clsx'
import { twMerge } from 'tailwind-merge'

export function cn(...inputs: ClassValue[]) {
  return twMerge(clsx(inputs))
}

export function formatNumber(num: number | null | undefined): string {
  if (num === null || num === undefined) return '-'
  return new Intl.NumberFormat('ko-KR').format(num)
}

export function formatPercent(num: number | null | undefined): string {
  if (num === null || num === undefined) return '-'
  return `${num.toFixed(2)}%`
}

/** 원 단위 금액을 조·억 단위로 표기 (예: 25조 7,959억원, -7,959억원, 3,200만원). suffix로 끝 단위('원')를 바꾼다 */
export function formatKrwAmount(won: number | null | undefined, suffix = '원'): string {
  if (won === null || won === undefined) return '-'
  const sign = won < 0 ? '-' : ''
  const abs = Math.abs(won)
  const eok = Math.floor(abs / 1e8)
  if (eok < 1) return `${sign}${Math.floor(abs / 1e4).toLocaleString('ko-KR')}만${suffix}`
  const jo = Math.floor(eok / 1e4)
  const rest = eok % 1e4
  if (jo < 1) return `${sign}${eok.toLocaleString('ko-KR')}억${suffix}`
  return rest > 0
    ? `${sign}${jo.toLocaleString('ko-KR')}조 ${rest.toLocaleString('ko-KR')}억${suffix}`
    : `${sign}${jo.toLocaleString('ko-KR')}조${suffix}`
}

export function formatCurrency(num: number | null | undefined): string {
  if (num === null || num === undefined) return '-'
  if (num >= 1e12) return `${(num / 1e12).toFixed(1)}조`
  if (num >= 1e8) return `${(num / 1e8).toFixed(1)}억`
  if (num >= 1e4) return `${(num / 1e4).toFixed(1)}만`
  return formatNumber(num)
}
