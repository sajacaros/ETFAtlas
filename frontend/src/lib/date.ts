// 서버 시각은 오프셋(+00:00·Z)을 붙여 보낸다. 예전 서버는 UTC를 시간대 없이 보냈으므로 오프셋이 없으면 UTC로 읽는다
const HAS_OFFSET = /(Z|[+-]\d{2}:?\d{2})$/i

export function parseServerDate(iso: string): Date {
  // 날짜만 있는 값('2026-10-31')은 오프셋을 붙이지 않는다 — Date가 이미 UTC 자정으로 읽는다
  if (!iso.includes('T') && !iso.includes(' ')) return new Date(iso)
  const normalized = iso.replace(' ', 'T')
  return new Date(HAS_OFFSET.test(normalized) ? normalized : `${normalized}Z`)
}

/** 2026. 10. 31. 오후 04:07 */
export function formatDateTime(iso: string | null | undefined): string {
  if (!iso) return '-'
  return parseServerDate(iso).toLocaleString('ko-KR', {
    year: 'numeric', month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit',
  })
}

/** 서버 시각의 날짜 부분(브라우저 시간대 기준) */
export function formatServerDate(iso: string | null | undefined): string {
  if (!iso) return '-'
  return parseServerDate(iso).toLocaleDateString()
}

/** 로컬 날짜를 YYYY-MM-DD로 (toISOString은 UTC라 한국 시간 오전 9시 전에는 하루 전 날짜가 된다) */
export function toLocalDateString(d: Date = new Date()): string {
  const pad = (n: number) => String(n).padStart(2, '0')
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}`
}
