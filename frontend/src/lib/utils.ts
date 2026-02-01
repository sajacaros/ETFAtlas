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

export function formatCurrency(num: number | null | undefined): string {
  if (num === null || num === undefined) return '-'
  if (num >= 1e12) return `${(num / 1e12).toFixed(1)}조`
  if (num >= 1e8) return `${(num / 1e8).toFixed(1)}억`
  if (num >= 1e4) return `${(num / 1e4).toFixed(1)}만`
  return formatNumber(num)
}
