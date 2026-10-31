import { parseServerDate } from '@/lib/date'
import { formatWon } from '@/lib/format'
import type { Portfolio } from '@/types/api'

/** 부호를 붙인 원 금액 (0도 '+') — 예: +12,345원 */
export function formatSignedWon(n: number): string {
  return `${n >= 0 ? '+' : ''}${formatWon(n)}원`
}

/** 서버 시각을 브라우저 시간대의 MM/DD HH:mm으로 */
export function formatShortDateTime(iso: string): string {
  const d = parseServerDate(iso)
  const pad = (n: number) => String(n).padStart(2, '0')
  return `${pad(d.getMonth() + 1)}/${pad(d.getDate())} ${pad(d.getHours())}:${pad(d.getMinutes())}`
}

/** 투자원금이 있으면 평가금액 - 투자원금, 없으면 null */
export function portfolioProfit(p: Portfolio): number | null {
  return p.current_value != null && p.invested_amount != null ? p.current_value - p.invested_amount : null
}
