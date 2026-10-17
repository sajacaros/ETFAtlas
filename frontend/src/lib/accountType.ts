import type { AccountType } from '@/types/api'

// 계좌 유형 태그. 유형마다 편입 조건이 다르다 (IRP: 개인형 퇴직연금, 연금저축). 포트폴리오마다 1개 이상
export const ACCOUNT_TYPES: { value: AccountType; label: string }[] = [
  { value: 'IRP', label: 'IRP' },
  { value: 'PENSION_SAVINGS', label: '연금저축' },
]

export const DEFAULT_ACCOUNT_TYPES: AccountType[] = ['PENSION_SAVINGS']

export function accountTypeLabel(type: AccountType) {
  return ACCOUNT_TYPES.find((t) => t.value === type)?.label ?? type
}

/** 태그를 켜고 끈다. 마지막 하나는 끌 수 없고, 결과는 ACCOUNT_TYPES 순서를 따른다 */
export function toggleAccountType(types: AccountType[], type: AccountType): AccountType[] {
  if (types.includes(type)) return types.length > 1 ? types.filter((t) => t !== type) : types
  return ACCOUNT_TYPES.map((t) => t.value).filter((t) => t === type || types.includes(t))
}
