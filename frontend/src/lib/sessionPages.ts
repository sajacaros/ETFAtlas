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
