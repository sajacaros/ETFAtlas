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

/** 원 단위 금액을 조·억 단위로 표기 (예: 25조 7,959억원, 7,959억원, 3,200만원) */
export function formatKrwAmount(won: number | null | undefined): string {
  if (won === null || won === undefined) return '-'
  const eok = Math.floor(won / 1e8)
  if (eok < 1) return `${Math.floor(won / 1e4).toLocaleString('ko-KR')}만원`
  const jo = Math.floor(eok / 1e4)
  const rest = eok % 1e4
  if (jo < 1) return `${eok.toLocaleString('ko-KR')}억원`
  return rest > 0 ? `${jo.toLocaleString('ko-KR')}조 ${rest.toLocaleString('ko-KR')}억원` : `${jo.toLocaleString('ko-KR')}조원`
}

export function formatCurrency(num: number | null | undefined): string {
  if (num === null || num === undefined) return '-'
  if (num >= 1e12) return `${(num / 1e12).toFixed(1)}조`
  if (num >= 1e8) return `${(num / 1e8).toFixed(1)}억`
  if (num >= 1e4) return `${(num / 1e4).toFixed(1)}만`
  return formatNumber(num)
}
