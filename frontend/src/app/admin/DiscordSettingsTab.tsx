import { useState, useCallback, useEffect } from 'react'
import { ETFLink } from '@/components/ETFInfo'
import { useToast } from '@/hooks/use-toast'
import { adminApi, getErrorDetail } from '@/lib/api'
import { formatDateTime } from '@/lib/date'
import type { AdminDiscordSettings, AdminDiscordNotificationLog } from '@/types/api'
import { Button } from '@/components/ui/button'
import { Badge } from '@/components/ui/badge'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { Table, TableBody, TableCell, TableRow } from '@/components/ui/table'
import { Switch } from '@/components/ui/switch'
import { Loader2, ChevronDown, ChevronRight } from 'lucide-react'
import { SECRET_INPUT_PROPS, TabSpinner } from './common'

// ============ Discord Settings Tab ============

export default function DiscordSettingsTab() {
  const { toast } = useToast()
  const [settings, setSettings] = useState<AdminDiscordSettings | null>(null)
  const [enabled, setEnabled] = useState(true)
  const [threshold, setThreshold] = useState('3')
  const [addedThreshold, setAddedThreshold] = useState('2')
  const [riseThreshold, setRiseThreshold] = useState('3')
  const [webhookUrl, setWebhookUrl] = useState('')  // 비워 두면 기존 주소 유지
  const [saving, setSaving] = useState(false)
  const [testing, setTesting] = useState(false)

  const apply = useCallback((s: AdminDiscordSettings) => {
    setSettings(s)
    setEnabled(s.enabled)
    setThreshold(String(s.threshold))
    setAddedThreshold(String(s.added_threshold))
    setRiseThreshold(String(s.rise_threshold))
    setWebhookUrl('')
  }, [])

  useEffect(() => {
    adminApi.getDiscordSettings()
      .then(apply)
      .catch(() => toast({ title: '알림 설정 조회 실패', variant: 'destructive' }))
  }, [apply, toast])

  const save = async (body: { webhook_url?: string } = {}) => {
    const value = Number(threshold)
    const addedValue = Number(addedThreshold)
    const riseValue = Number(riseThreshold)
    if (![value, addedValue, riseValue].every((v) => v > 0 && v <= 100)) {
      toast({ title: '기준값은 0보다 크고 100 이하여야 합니다', variant: 'destructive' })
      return
    }
    setSaving(true)
    try {
      const url = webhookUrl.trim()
      apply(await adminApi.updateDiscordSettings({
        enabled,
        threshold: value,
        added_threshold: addedValue,
        rise_threshold: riseValue,
        ...(url ? { webhook_url: url } : {}),
        ...body,
      }))
      toast({ title: '알림 설정을 저장했습니다' })
    } catch (e: unknown) {
      const detail = getErrorDetail(e)
      toast({
        title: '알림 설정 저장 실패',
        description: Array.isArray(detail) ? '디스코드 웹훅 주소(https://discord.com/api/webhooks/...)만 입력할 수 있습니다' : undefined,
        variant: 'destructive',
      })
    } finally {
      setSaving(false)
    }
  }

  const test = async () => {
    setTesting(true)
    try {
      await adminApi.testDiscordWebhook()
      toast({ title: '테스트 메시지를 보냈습니다', description: '디스코드 채널을 확인하세요.' })
    } catch {
      toast({ title: '테스트 전송 실패', description: '저장된 웹훅 주소를 확인하세요.', variant: 'destructive' })
    } finally {
      setTesting(false)
    }
  }

  if (!settings) {
    return <TabSpinner />
  }

  return (
    <div className="max-w-xl space-y-6 py-2">
      <p className="text-sm text-muted-foreground">
        개장일마다 구성종목 공시를 받으면 액티브 ETF 전체에서 이전 공시보다 비중이 기준값보다 크게 바뀐 종목을 디스코드로 보냅니다. 웹의 비중 변화 화면도 같은 기준값을 씁니다.
        개장일 16:30 수집이 끝나면 수집 결과 요약과 기준값 이상 오른 ETF(구성종목 등락·LLM 분석 포함)를 일일 리포트로 보냅니다.
        메시지가 2,000자를 넘으면 나눠서 보냅니다.
      </p>

      <div className="flex items-center gap-3">
        <Switch id="discord-enabled" checked={enabled} onCheckedChange={setEnabled} />
        <Label htmlFor="discord-enabled">디스코드 알림 보내기</Label>
      </div>

      <div className="space-y-2">
        <Label htmlFor="discord-webhook">웹훅 주소</Label>
        <p className="text-sm text-muted-foreground">
          현재: {settings.webhook_url_masked ?? (settings.configured ? '없음' : '없음 (서버 환경변수 DISCORD_WEBHOOK_URL이 있으면 그것을 씁니다)')}
        </p>
        <Input
          id="discord-webhook"
          {...SECRET_INPUT_PROPS}
          value={webhookUrl}
          onChange={(e) => setWebhookUrl(e.target.value)}
          placeholder="새 주소 입력 — 비워 두면 기존 주소 유지"
        />
      </div>

      <div className="space-y-2">
        <Label htmlFor="discord-threshold">비중 변화 기준 (%p)</Label>
        <Input
          id="discord-threshold"
          type="number"
          min={0.1}
          max={100}
          step={0.5}
          value={threshold}
          onChange={(e) => setThreshold(e.target.value)}
          className="w-32"
        />
        <p className="text-sm text-muted-foreground">이 값보다 크게 바뀐 종목만 알립니다.</p>
      </div>

      <div className="space-y-2">
        <Label htmlFor="discord-added-threshold">신규편입 기준 (%p)</Label>
        <Input
          id="discord-added-threshold"
          type="number"
          min={0.1}
          max={100}
          step={0.5}
          value={addedThreshold}
          onChange={(e) => setAddedThreshold(e.target.value)}
          className="w-32"
        />
        <p className="text-sm text-muted-foreground">새로 편입된 종목은 비중이 이 값보다 크면 알립니다.</p>
      </div>

      <div className="space-y-2">
        <Label htmlFor="discord-rise-threshold">일일 리포트 상승 기준 (%)</Label>
        <Input
          id="discord-rise-threshold"
          type="number"
          min={0.1}
          max={100}
          step={0.5}
          value={riseThreshold}
          onChange={(e) => setRiseThreshold(e.target.value)}
          className="w-32"
        />
        <p className="text-sm text-muted-foreground">그날 1일 수익률이 이 값 이상인 ETF를 모두 보냅니다.</p>
      </div>

      <div className="flex flex-wrap gap-2">
        <Button onClick={() => save()} disabled={saving}>
          {saving && <Loader2 className="h-4 w-4 mr-1 animate-spin" />}저장
        </Button>
        <Button variant="outline" onClick={test} disabled={testing || !settings.webhook_url_masked}>
          {testing && <Loader2 className="h-4 w-4 mr-1 animate-spin" />}테스트 전송
        </Button>
        {settings.webhook_url_masked && (
          <Button variant="ghost" onClick={() => save({ webhook_url: '' })} disabled={saving}>
            주소 삭제
          </Button>
        )}
      </div>

      <DiscordNotificationLogs />
    </div>
  )
}

const CHANGE_TYPE_LABELS: Record<AdminDiscordNotificationLog['items'][number]['changes'][number]['change_type'], string> = {
  added: '신규편입',
  removed: '편출',
  increased: '증가',
  decreased: '감소',
}

const LOG_PAGE_SIZE = 30

function DiscordNotificationLogs() {
  const { toast } = useToast()
  const [logs, setLogs] = useState<AdminDiscordNotificationLog[] | null>(null)
  const [total, setTotal] = useState(0)
  const [loadingMore, setLoadingMore] = useState(false)
  const [openId, setOpenId] = useState<number | null>(null)

  useEffect(() => {
    adminApi.getDiscordNotificationLogs(LOG_PAGE_SIZE)
      .then((r) => {
        setLogs(r.logs)
        setTotal(r.total)
        setOpenId(r.logs[0]?.id ?? null)
      })
      .catch(() => toast({ title: '발송 이력 조회 실패', variant: 'destructive' }))
  }, [toast])

  const loadMore = async () => {
    if (!logs) return
    setLoadingMore(true)
    try {
      const r = await adminApi.getDiscordNotificationLogs(LOG_PAGE_SIZE, logs.length)
      setLogs([...logs, ...r.logs])
      setTotal(r.total)
    } catch {
      toast({ title: '발송 이력 조회 실패', variant: 'destructive' })
    } finally {
      setLoadingMore(false)
    }
  }

  return (
    <div className="space-y-3 border-t pt-6">
      <div>
        <Label>발송 이력</Label>
        <p className="text-sm text-muted-foreground">디스코드로 보낸 비중 변화입니다. 변화가 없어 보내지 않은 날은 남지 않습니다.</p>
      </div>

      {logs === null ? (
        <div className="flex justify-center py-4"><Loader2 className="h-5 w-5 animate-spin" /></div>
      ) : logs.length === 0 ? (
        <p className="text-sm text-muted-foreground">아직 보낸 알림이 없습니다.</p>
      ) : (
        <div className="border rounded-md divide-y">
          {logs.map((log) => {
            const open = openId === log.id
            const stockCount = log.items.reduce((n, item) => n + item.changes.length, 0)
            return (
              <div key={log.id}>
                <button
                  type="button"
                  className="w-full flex items-center gap-3 px-3 py-2 text-sm text-left hover:bg-muted"
                  onClick={() => setOpenId(open ? null : log.id)}
                  aria-expanded={open}
                >
                  {open ? <ChevronDown className="h-4 w-4 shrink-0" /> : <ChevronRight className="h-4 w-4 shrink-0" />}
                  <span className="font-medium">{log.base_date}</span>
                  <span className="text-muted-foreground flex-1">
                    ETF {log.items.length}개 · 종목 {stockCount}건 · 기준 {log.threshold}%p
                  </span>
                  {log.status === 'failed'
                    ? <Badge variant="destructive">실패</Badge>
                    : <span className="text-xs text-muted-foreground">{formatDateTime(log.sent_at)}</span>}
                </button>
                {open && (
                  <div className="px-3 pb-3 space-y-3">
                    {log.error && <p className="text-sm text-destructive">전송 실패: {log.error}</p>}
                    {log.items.map((item) => (
                      <div key={item.etf_code} className="space-y-1">
                        <div className="text-sm">
                          <ETFLink code={item.etf_code} name={item.etf_name} className="font-medium">{item.etf_name}</ETFLink>
                          <span className="text-muted-foreground"> ({item.etf_code}) · {item.prev_date} → {log.base_date}</span>
                        </div>
                        <Table>
                          <TableBody>
                            {item.changes.map((c) => (
                              <TableRow key={c.stock_code}>
                                <TableCell className="py-1.5 w-20">
                                  <Badge variant={c.weight_change > 0 ? 'default' : 'destructive'}>{CHANGE_TYPE_LABELS[c.change_type]}</Badge>
                                </TableCell>
                                <TableCell className="py-1.5">{c.stock_name}</TableCell>
                                <TableCell className="py-1.5 text-right tabular-nums text-muted-foreground">
                                  {c.previous_weight.toFixed(2)}% → {c.current_weight.toFixed(2)}%
                                </TableCell>
                                <TableCell className={`py-1.5 text-right tabular-nums w-24 ${c.weight_change > 0 ? 'text-green-600' : 'text-red-600'}`}>
                                  {c.weight_change > 0 ? '+' : ''}{c.weight_change.toFixed(2)}%p
                                </TableCell>
                              </TableRow>
                            ))}
                          </TableBody>
                        </Table>
                      </div>
                    ))}
                  </div>
                )}
              </div>
            )
          })}
        </div>
      )}

      {logs && logs.length < total && (
        <Button variant="outline" size="sm" onClick={loadMore} disabled={loadingMore}>
          {loadingMore && <Loader2 className="h-4 w-4 mr-1 animate-spin" />}더 보기
        </Button>
      )}
    </div>
  )
}
