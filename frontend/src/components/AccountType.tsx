import type { AccountType } from '@/types/api'
import { ACCOUNT_TYPES, accountTypeLabel, toggleAccountType } from '@/lib/accountType'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { cn } from '@/lib/utils'

/** compact면 제목 옆 한 줄에 들어가도록 작게 */
export function AccountTypeBadges({ types, className, compact = false }: {
  types: AccountType[]
  className?: string
  compact?: boolean
}) {
  return (
    <div className={cn('flex flex-wrap gap-1', className)}>
      {types.map((t) => (
        <Badge key={t} variant="outline" className={cn(compact && 'px-1.5 py-0 text-[11px] font-medium')}>
          {accountTypeLabel(t)}
        </Badge>
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
