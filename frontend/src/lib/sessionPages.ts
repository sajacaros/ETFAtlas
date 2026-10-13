import type { ChatSessionPage, ChatSessionSummary } from '@/types/api'

export interface SessionListState {
  items: ChatSessionSummary[]
  nextCursor: string | null
}

// 목록 순서(최근 활동 순)에서 a가 b보다 뒤인가 — 서버와 같은 (updated_at, id) 기준. updated_at은 ISO 문자열이라 문자열로 비교된다
function isAfter(a: ChatSessionSummary, b: ChatSessionSummary): boolean {
  return a.updated_at < b.updated_at || (a.updated_at === b.updated_at && a.id < b.id)
}

/** 첫 페이지를 다시 받았을 때: 첫 페이지로 바꾸되, 스크롤로 이미 불러온 더 오래된 세션은 남긴다.
 * 대화를 이어가 위로 올라온 세션은 첫 페이지에만 남고, 지워진 세션은 첫 페이지 범위 안에서만 빠진다(그 밖은 지울 때 따로 뺀다). */
export function mergeFirstPage(prev: SessionListState, first: ChatSessionPage): SessionListState {
  const last = first.items[first.items.length - 1]
  if (!last || first.next_cursor === null) return { items: first.items, nextCursor: first.next_cursor }
  const ids = new Set(first.items.map((s) => s.id))
  const older = prev.items.filter((s) => !ids.has(s.id) && isAfter(s, last))
  // 더 오래된 걸 이미 불러왔으면 그 다음부터 이어서 불러온다
  return { items: [...first.items, ...older], nextCursor: older.length > 0 ? prev.nextCursor : first.next_cursor }
}

/** 스크롤로 다음 페이지를 받았을 때: 뒤에 붙인다 (사이에 위로 올라온 세션이 겹치면 한 번만). */
export function appendPage(prev: SessionListState, page: ChatSessionPage): SessionListState {
  const ids = new Set(prev.items.map((s) => s.id))
  return { items: [...prev.items, ...page.items.filter((s) => !ids.has(s.id))], nextCursor: page.next_cursor }
}

export interface SessionGroup {
  label: string
  items: ChatSessionSummary[]
}

/** 최근 활동 날짜로 묶는다 (오늘·어제·지난 7일·지난 30일·그 이전). 목록이 이미 최근 순이라 묶음도 그 순서다. */
export function groupByDate(items: ChatSessionSummary[], now: Date = new Date()): SessionGroup[] {
  const today = new Date(now.getFullYear(), now.getMonth(), now.getDate()).getTime()
  const day = 24 * 60 * 60 * 1000
  const label = (s: ChatSessionSummary) => {
    const t = new Date(s.updated_at.endsWith('Z') ? s.updated_at : s.updated_at + 'Z').getTime()  // 서버는 UTC를 시간대 없이 보낸다
    if (t >= today) return '오늘'
    if (t >= today - day) return '어제'
    if (t >= today - 7 * day) return '지난 7일'
    if (t >= today - 30 * day) return '지난 30일'
    return '이전'
  }
  const groups: SessionGroup[] = []
  for (const s of items) {
    const l = label(s)
    const last = groups[groups.length - 1]
    if (last?.label === l) last.items.push(s)
    else groups.push({ label: l, items: [s] })
  }
  return groups
}
