import type { AccountType } from '@/types/api'
import { ACCOUNT_TYPES, accountTypeLabel, toggleAccountType } from '@/lib/accountType'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { cn } from '@/lib/utils'

export function AccountTypeBadges({ types, className }: { types: AccountType[]; className?: string }) {
  return (
    <div className={cn('flex flex-wrap gap-1', className)}>
      {types.map((t) => (
        <Badge key={t} variant="outline">{accountTypeLabel(t)}</Badge>
      ))}
    </div>
  )
}

/** 계좌 유형 태그 선택 (여러 개, 최소 1개). compact면 편집 헤더에 맞는 작은 버튼 */
export function AccountTypePicker({ value, onChange, compact = false }: {
  value: AccountType[]
  onChange: (types: AccountType[]) => void
  compact?: boolean
}) {
  return (
    <div className="flex gap-2" role="group" aria-label="계좌 유형">
      {ACCOUNT_TYPES.map((t) => {
        const selected = value.includes(t.value)
        const locked = selected && value.length === 1
        return (
          <Button
            key={t.value}
            type="button"
            size="sm"
            variant={selected ? 'default' : 'outline'}
            aria-pressed={selected}
            title={locked ? '계좌 유형은 하나 이상 선택해야 합니다' : undefined}
            onClick={() => onChange(toggleAccountType(value, t.value))}
            className={cn(!compact && 'flex-1', locked && 'cursor-not-allowed')}
          >
            {t.label}
          </Button>
        )
      })}
    </div>
  )
}
