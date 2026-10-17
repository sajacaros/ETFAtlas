import type { AccountType } from '@/types/api'
import { ACCOUNT_TYPES, accountTypeLabel } from '@/lib/accountType'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'

export function AccountTypeBadge({ type, className }: { type: AccountType; className?: string }) {
  return <Badge variant="outline" className={className}>{accountTypeLabel(type)}</Badge>
}

/** 계좌 유형 선택 버튼 묶음 (계산 기준 선택과 같은 모양) */
export function AccountTypePicker({ value, onChange }: { value: AccountType; onChange: (type: AccountType) => void }) {
  return (
    <div className="flex gap-2">
      {ACCOUNT_TYPES.map((t) => (
        <Button
          key={t.value}
          type="button"
          size="sm"
          variant={value === t.value ? 'default' : 'outline'}
          onClick={() => onChange(t.value)}
          className="flex-1"
        >
          {t.label}
        </Button>
      ))}
    </div>
  )
}
