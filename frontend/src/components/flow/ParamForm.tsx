import type { FlowParamSpec, Portfolio } from '@/types/api'
import { Input } from '@/components/ui/input'
import { Switch } from '@/components/ui/switch'
import { EtfPicker } from './EtfPicker'

const selectClass =
  'flex h-9 w-full rounded-md border border-input bg-background px-2 text-sm focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring'

interface Props {
  specs: FlowParamSpec[]
  values: Record<string, unknown>
  onChange: (key: string, value: unknown) => void
  portfolios: Portfolio[]
  fieldOptions: { key: string; label: string }[]  // 앞 노드 결과의 열 (정렬 기준 고르기)
}

const visible = (spec: FlowParamSpec, values: Record<string, unknown>) =>
  !spec.show_if || Object.entries(spec.show_if).every(([k, allowed]) => allowed.includes(values[k] ?? null))

/** 노드 설정 폼. 서버가 보낸 설정 명세(타입·선택지·조건부 표시)대로 그린다 */
export function ParamForm({ specs, values, onChange, portfolios, fieldOptions }: Props) {
  // 설정하지 않은 값은 명세의 기본값으로 보여 준다
  const current = Object.fromEntries(specs.map((s) => [s.key, s.key in values ? values[s.key] : s.default]))
  return (
    <div className="space-y-4">
      {specs.filter((s) => visible(s, current)).map((spec) => {
        const value = current[spec.key]
        const id = `param-${spec.key}`
        return (
          <div key={spec.key} className="space-y-1">
            {spec.type === 'bool' ? (
              <label htmlFor={id} className="flex cursor-pointer items-center justify-between gap-3 text-sm font-medium">
                {spec.label}
                <Switch id={id} checked={Boolean(value)} onCheckedChange={(v) => onChange(spec.key, v)} />
              </label>
            ) : (
              <label htmlFor={id} className="text-sm font-medium">{spec.label}</label>
            )}
            {spec.type === 'select' && (
              <select id={id} className={selectClass} value={String(value ?? '')} onChange={(e) => onChange(spec.key, e.target.value)}>
                {spec.options?.map((o) => <option key={o.value} value={o.value}>{o.label}</option>)}
              </select>
            )}
            {spec.type === 'portfolio' && (
              <select
                id={id}
                className={selectClass}
                value={value == null ? '' : String(value)}
                onChange={(e) => onChange(spec.key, e.target.value ? Number(e.target.value) : null)}
              >
                <option value="">포트폴리오 선택</option>
                {portfolios.map((p) => <option key={p.id} value={p.id}>{p.name}</option>)}
              </select>
            )}
            {spec.type === 'field' && (
              <select id={id} className={selectClass} value={String(value ?? '')} onChange={(e) => onChange(spec.key, e.target.value)}>
                <option value="">들어온 순서</option>
                {fieldOptions.map((f) => <option key={f.key} value={f.key}>{f.label}</option>)}
                {typeof value === 'string' && value && !fieldOptions.some((f) => f.key === value) && <option value={value}>{value}</option>}
              </select>
            )}
            {spec.type === 'number' && (
              <Input
                id={id}
                type="number"
                inputMode="decimal"
                value={value == null ? '' : String(value)}
                placeholder={spec.nullable ? '끔' : undefined}
                onChange={(e) => {
                  const raw = e.target.value
                  if (raw === '') onChange(spec.key, spec.nullable ? null : spec.default)
                  else if (!Number.isNaN(Number(raw))) onChange(spec.key, Number(raw))
                }}
              />
            )}
            {spec.type === 'etf' && (
              <EtfPicker
                id={id}
                value={String(value ?? '')}
                name={String(values[`${spec.key}_name`] ?? '')}
                onPick={(code, name) => {
                  onChange(spec.key, code)
                  onChange(`${spec.key}_name`, name)  // 화면 표시용, 서버는 무시한다
                }}
                onType={(text) => {
                  onChange(spec.key, text)
                  onChange(`${spec.key}_name`, '')
                }}
              />
            )}
            {spec.type === 'text' && (
              <Input id={id} value={String(value ?? '')} onChange={(e) => onChange(spec.key, e.target.value)} />
            )}
            {spec.help && <p className="text-xs text-muted-foreground">{spec.help}</p>}
          </div>
        )
      })}
    </div>
  )
}
