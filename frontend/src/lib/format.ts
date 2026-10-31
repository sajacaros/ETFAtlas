// 숫자·금액·등락률 표기와 상승/하락 색을 한곳에 모은다

export function formatNumber(num: number | null | undefined): string {
  if (num === null || num === undefined) return '-'
  return new Intl.NumberFormat('ko-KR').format(num)
}

/** 원 단위 정수로 반올림해 천 단위 구분 (예: 1,234,568) */
export function formatWon(n: number): string {
  return new Intl.NumberFormat('ko-KR').format(Math.round(n))
}

export function formatPercent(num: number | null | undefined): string {
  if (num === null || num === undefined) return '-'
  return `${num.toFixed(2)}%`
}

/**
 * 부호를 붙인 등락률 (예: +1.23%, -0.50%). null이면 '-'.
 * plusOnZero=false면 0에는 '+'를 붙이지 않는다
 */
export function formatRate(rate: number | null | undefined, digits = 2, plusOnZero = true): string {
  if (rate === null || rate === undefined) return '-'
  const sign = rate > 0 || (plusOnZero && rate >= 0) ? '+' : ''
  return `${sign}${rate.toFixed(digits)}%`
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

/** 차트 축용 짧은 만원 표기 (예: 1억2,000만, 3,500만) */
export function formatManwon(n: number): string {
  const man = Math.floor(Math.abs(n) / 10000)
  const sign = n < 0 ? '-' : ''
  if (man >= 10000) {
    const eok = Math.floor(man / 10000)
    const rest = man % 10000
    return rest > 0
      ? `${sign}${eok}억${new Intl.NumberFormat('ko-KR').format(rest)}만`
      : `${sign}${eok}억`
  }
  return `${sign}${new Intl.NumberFormat('ko-KR').format(man)}만`
}

export function formatCurrency(num: number | null | undefined): string {
  if (num === null || num === undefined) return '-'
  if (num >= 1e12) return `${(num / 1e12).toFixed(1)}조`
  if (num >= 1e8) return `${(num / 1e8).toFixed(1)}억`
  if (num >= 1e4) return `${(num / 1e4).toFixed(1)}만`
  return formatNumber(num)
}

/**
 * 상승은 빨강, 하락은 파랑. 0과 값 없음은 neutral(기본: 색 없음)로 둔다
 */
export function changeColor(value: number | null | undefined, neutral = ''): string {
  if (value == null || value === 0) return neutral
  return value > 0 ? 'text-red-500' : 'text-blue-500'
}
