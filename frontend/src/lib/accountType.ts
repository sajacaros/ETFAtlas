import type { AccountType } from '@/types/api'

// 계좌 유형마다 편입 조건이 다르다 (IRP: 개인형 퇴직연금, 연금저축)
export const ACCOUNT_TYPES: { value: AccountType; label: string }[] = [
  { value: 'IRP', label: 'IRP' },
  { value: 'PENSION_SAVINGS', label: '연금저축' },
]

export const DEFAULT_ACCOUNT_TYPE: AccountType = 'PENSION_SAVINGS'

export function accountTypeLabel(type: AccountType) {
  return ACCOUNT_TYPES.find((t) => t.value === type)?.label ?? type
}
