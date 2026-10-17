import type { FlowCategory } from '@/types/api'

/** 단계별 이름과 색. 팔레트 묶음과 캔버스 노드의 왼쪽 띠가 같은 색을 쓴다 */
export const CATEGORIES: Record<FlowCategory, { step: number; label: string; bar: string; dot: string }> = {
  source: { step: 1, label: '종목 가져오기', bar: 'border-l-sky-500', dot: 'bg-sky-500' },
  filter: { step: 2, label: '거르기', bar: 'border-l-violet-500', dot: 'bg-violet-500' },
  combine: { step: 3, label: '합치기', bar: 'border-l-indigo-500', dot: 'bg-indigo-500' },
  ai: { step: 4, label: 'AI 분석', bar: 'border-l-teal-500', dot: 'bg-teal-500' },
  result: { step: 5, label: '결과 확인', bar: 'border-l-amber-500', dot: 'bg-amber-500' },
}

export const CATEGORY_ORDER: FlowCategory[] = ['source', 'filter', 'combine', 'ai', 'result']
