import { useState, useCallback, useEffect } from 'react'
import { ETFLink } from '@/components/ETFInfo'
import { useAuth } from '@/hooks/useAuth'
import { useToast } from '@/hooks/use-toast'
import { adminApi } from '@/lib/api'
import type { AdminCodeExample, AdminChatLog, AdminETFTag, AdminDiscordSettings, AdminInvitation, AdminMember } from '@/types/api'
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs'
import { Button } from '@/components/ui/button'
import { Badge } from '@/components/ui/badge'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { Textarea } from '@/components/ui/textarea'
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from '@/components/ui/table'
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
  DialogFooter,
  DialogDescription,
} from '@/components/ui/dialog'
import { Switch } from '@/components/ui/switch'
import { ShieldAlert, Plus, Pencil, Archive, Check, X, Upload, Undo2, Search, Loader2, RotateCcw, Copy, Trash2, KeyRound, LogOut } from 'lucide-react'

const STATUS_FILTERS = {
  codeExamples: [
    { label: '전체', value: '' },
    { label: 'Active', value: 'active' },
    { label: 'Embedded', value: 'embedded' },
  ],
  chatLogs: [
    { label: '전체', value: '' },
    { label: 'Liked', value: 'liked' },
    { label: 'Approved', value: 'approved' },
    { label: 'Rejected', value: 'rejected' },
    { label: 'Embedded', value: 'embedded' },
  ],
}

function statusBadgeVariant(status: string): 'default' | 'secondary' | 'destructive' | 'outline' {
  switch (status) {
    case 'active':
    case 'approved':
    case 'embedded':
      return 'default'
    case 'liked':
      return 'secondary'
    case 'rejected':
      return 'destructive'
    default:
      return 'outline'
  }
}

export default function AdminPage() {
  const { user } = useAuth()

  if (!user?.is_admin) {
    return (
      <div className="flex flex-col items-center justify-center py-20 text-muted-foreground">
        <ShieldAlert className="w-16 h-16 mb-4" />
        <h2 className="text-xl font-semibold mb-2">접근 권한이 없습니다</h2>
        <p>관리자 권한이 필요합니다.</p>
      </div>
    )
  }

  return (
    <div className="space-y-6">
      <h1 className="text-2xl font-bold">관리자</h1>
      <Tabs defaultValue="code-examples">
        <TabsList>
          <TabsTrigger value="code-examples">코드 예제</TabsTrigger>
          <TabsTrigger value="chat-logs">채팅 로그</TabsTrigger>
          <TabsTrigger value="etf-tags">ETF 태그</TabsTrigger>
          <TabsTrigger value="notifications">알림</TabsTrigger>
          <TabsTrigger value="members">멤버</TabsTrigger>
          <TabsTrigger value="invitations">멤버 초대</TabsTrigger>
        </TabsList>
        <TabsContent value="code-examples">
          <CodeExamplesTab />
        </TabsContent>
        <TabsContent value="chat-logs">
          <ChatLogsTab />
        </TabsContent>
        <TabsContent value="etf-tags">
          <ETFTagsTab />
        </TabsContent>
        <TabsContent value="notifications">
          <DiscordSettingsTab />
        </TabsContent>
        <TabsContent value="members">
          <MembersTab />
        </TabsContent>
        <TabsContent value="invitations">
          <InvitationsTab />
        </TabsContent>
      </Tabs>
    </div>
  )
}

// ============ Discord Settings Tab ============

function DiscordSettingsTab() {
  const { toast } = useToast()
  const [settings, setSettings] = useState<AdminDiscordSettings | null>(null)
  const [enabled, setEnabled] = useState(true)
  const [threshold, setThreshold] = useState('3')
  const [webhookUrl, setWebhookUrl] = useState('')  // 비워 두면 기존 주소 유지
  const [saving, setSaving] = useState(false)
  const [testing, setTesting] = useState(false)

  const apply = useCallback((s: AdminDiscordSettings) => {
    setSettings(s)
    setEnabled(s.enabled)
    setThreshold(String(s.threshold))
    setWebhookUrl('')
  }, [])

  useEffect(() => {
    adminApi.getDiscordSettings()
      .then(apply)
      .catch(() => toast({ title: '알림 설정 조회 실패', variant: 'destructive' }))
  }, [apply, toast])

  const save = async (body: { webhook_url?: string } = {}) => {
    const value = Number(threshold)
    if (!(value > 0 && value <= 100)) {
      toast({ title: '기준값은 0보다 크고 100 이하여야 합니다', variant: 'destructive' })
      return
    }
    setSaving(true)
    try {
      const url = webhookUrl.trim()
      apply(await adminApi.updateDiscordSettings({
        enabled,
        threshold: value,
        ...(url ? { webhook_url: url } : {}),
        ...body,
      }))
      toast({ title: '알림 설정을 저장했습니다' })
    } catch (e: unknown) {
      const detail = (e as { response?: { data?: { detail?: unknown } } }).response?.data?.detail
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
    return <div className="flex justify-center py-10"><Loader2 className="h-5 w-5 animate-spin" /></div>
  }

  return (
    <div className="max-w-xl space-y-6 py-2">
      <p className="text-sm text-muted-foreground">
        매일 수집이 끝나면 관리자가 즐겨찾기한 ETF 중 일주일 전보다 구성종목 비중이 기준값보다 크게 바뀐 종목을 디스코드로 보냅니다.
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
          type="password"
          autoComplete="off"
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
    </div>
  )
}

// ============ Members Tab ============

const resetUrl = (token: string) => `${window.location.origin}/reset-password/${token}`
const formatDateTime = (iso: string | null) => (iso ? new Date(iso + 'Z').toLocaleString() : '-')

function MembersTab() {
  const { user } = useAuth()
  const { toast } = useToast()
  const [items, setItems] = useState<AdminMember[] | null>(null)
  const [busyId, setBusyId] = useState<number | null>(null)
  const [deleting, setDeleting] = useState<AdminMember | null>(null)
  const [resetLink, setResetLink] = useState<{ username: string; url: string; expiresAt: string } | null>(null)

  const load = useCallback(() => {
    adminApi.listMembers()
      .then(setItems)
      .catch(() => toast({ title: '멤버 목록 조회 실패', variant: 'destructive' }))
  }, [toast])

  useEffect(() => { load() }, [load])

  const run = async (id: number, action: () => Promise<void>, failTitle: string) => {
    setBusyId(id)
    try {
      await action()
      load()
    } catch {
      toast({ title: failTitle, variant: 'destructive' })
    } finally {
      setBusyId(null)
    }
  }

  const toggleAdmin = (m: AdminMember) => run(m.id, async () => {
    await adminApi.updateMemberRole(m.id, !m.is_admin)
    toast({ title: m.is_admin ? `${m.username}의 관리자 권한을 회수했습니다` : `${m.username}에게 관리자 권한을 줬습니다` })
  }, '권한 변경 실패')

  const forceLogout = (m: AdminMember) => run(m.id, async () => {
    const { revoked } = await adminApi.logoutMember(m.id)
    toast({ title: `${m.username}의 세션 ${revoked}개를 끊었습니다` })
  }, '강제 로그아웃 실패')

  const createReset = (m: AdminMember) => run(m.id, async () => {
    const { token, expires_at } = await adminApi.createPasswordReset(m.id)
    setResetLink({ username: m.username, url: resetUrl(token), expiresAt: expires_at })
  }, '재설정 링크 생성 실패')

  const confirmDelete = async () => {
    if (!deleting) return
    const target = deleting
    setDeleting(null)
    await run(target.id, async () => {
      await adminApi.deleteMember(target.id)
      toast({ title: `${target.username}을(를) 삭제했습니다` })
    }, '멤버 삭제 실패')
  }

  // http로 접속하면 클립보드 API가 없을 수 있다 — 그때는 대화상자의 링크를 직접 복사
  const copyReset = async () => {
    if (!resetLink) return
    try {
      await navigator.clipboard.writeText(resetLink.url)
      toast({ title: '재설정 링크를 복사했습니다' })
    } catch {
      toast({ title: '복사하지 못했습니다', description: '링크를 직접 복사하세요.', variant: 'destructive' })
    }
  }

  if (!items) {
    return <div className="flex justify-center py-10"><Loader2 className="h-5 w-5 animate-spin" /></div>
  }

  return (
    <div className="space-y-4 py-2">
      <p className="text-sm text-muted-foreground">
        자기 자신의 권한 변경과 삭제는 할 수 없습니다. 비밀번호를 잊은 멤버에게는 재설정 링크(24시간 유효, 1회용)를 만들어 전달하세요.
      </p>

      <Table>
        <TableHeader>
          <TableRow>
            <TableHead>아이디</TableHead>
            <TableHead>역할</TableHead>
            <TableHead>초대한 사람</TableHead>
            <TableHead>가입일</TableHead>
            <TableHead>최근 로그인</TableHead>
            <TableHead className="text-right">포트폴리오</TableHead>
            <TableHead className="w-32" />
          </TableRow>
        </TableHeader>
        <TableBody>
          {items.map((m) => {
            const isSelf = m.id === user?.id
            const busy = busyId === m.id
            return (
              <TableRow key={m.id}>
                <TableCell>
                  <div className="font-medium">
                    {m.username}
                    {isSelf && <span className="ml-1 text-xs text-muted-foreground">(나)</span>}
                  </div>
                  {m.name && m.name !== m.username && <div className="text-xs text-muted-foreground">{m.name}</div>}
                </TableCell>
                <TableCell>
                  <div className="flex items-center gap-2">
                    <Badge variant={m.is_admin ? 'default' : 'secondary'}>{m.is_admin ? '관리자' : '멤버'}</Badge>
                    {!isSelf && (
                      <Button variant="link" size="sm" className="h-auto p-0 text-xs" disabled={busy} onClick={() => toggleAdmin(m)}>
                        {m.is_admin ? '권한 회수' : '관리자로'}
                      </Button>
                    )}
                  </div>
                </TableCell>
                <TableCell>{m.invited_by ?? '-'}</TableCell>
                <TableCell>{m.created_at ? new Date(m.created_at + 'Z').toLocaleDateString() : '-'}</TableCell>
                <TableCell>
                  <div>{formatDateTime(m.last_login_at)}</div>
                  {m.active_sessions > 0 && (
                    <div className="text-xs text-muted-foreground">세션 {m.active_sessions}개</div>
                  )}
                </TableCell>
                <TableCell className="text-right tabular-nums">{m.portfolio_count}</TableCell>
                <TableCell>
                  <div className="flex gap-1 justify-end">
                    {busy && <Loader2 className="h-4 w-4 animate-spin text-muted-foreground self-center" />}
                    <Button variant="ghost" size="icon" title="비밀번호 재설정 링크" disabled={busy} onClick={() => createReset(m)}>
                      <KeyRound className="h-4 w-4" />
                    </Button>
                    <Button
                      variant="ghost"
                      size="icon"
                      title={isSelf ? '로그아웃은 상단 메뉴에서' : '강제 로그아웃'}
                      disabled={busy || isSelf || m.active_sessions === 0}
                      onClick={() => forceLogout(m)}
                    >
                      <LogOut className="h-4 w-4" />
                    </Button>
                    <Button variant="ghost" size="icon" title="삭제" disabled={busy || isSelf} onClick={() => setDeleting(m)}>
                      <Trash2 className="h-4 w-4" />
                    </Button>
                  </div>
                </TableCell>
              </TableRow>
            )
          })}
        </TableBody>
      </Table>

      <Dialog open={deleting !== null} onOpenChange={(open) => !open && setDeleting(null)}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>{deleting?.username} 삭제</DialogTitle>
            <DialogDescription>
              계정과 함께 포트폴리오 {deleting?.portfolio_count ?? 0}개, 즐겨찾기, 로그인 세션이 모두 지워지며 되돌릴 수 없습니다.
              챗봇 대화 기록은 작성자 정보만 지우고 남깁니다.
            </DialogDescription>
          </DialogHeader>
          <DialogFooter>
            <Button variant="outline" onClick={() => setDeleting(null)}>취소</Button>
            <Button variant="destructive" onClick={confirmDelete}>삭제</Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      <Dialog open={resetLink !== null} onOpenChange={(open) => !open && setResetLink(null)}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>{resetLink?.username} 비밀번호 재설정 링크</DialogTitle>
            <DialogDescription>
              이 링크는 지금만 볼 수 있습니다. 멤버에게 전달하세요. {resetLink && formatDateTime(resetLink.expiresAt)}까지 한 번 쓸 수 있고,
              이전에 만든 링크는 무효가 됩니다.
            </DialogDescription>
          </DialogHeader>
          <p className="font-mono text-xs break-all rounded-md border p-3 select-all">{resetLink?.url}</p>
          <DialogFooter>
            <Button variant="outline" onClick={() => setResetLink(null)}>닫기</Button>
            <Button onClick={copyReset}><Copy className="h-4 w-4 mr-1" />복사</Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  )
}

// ============ Invitations Tab ============

const INVITATION_STATUS: Record<AdminInvitation['status'], { label: string; variant: 'default' | 'secondary' | 'outline' }> = {
  active: { label: '사용 가능', variant: 'default' },
  used: { label: '사용됨', variant: 'secondary' },
  expired: { label: '만료', variant: 'outline' },
}

const inviteUrl = (token: string) => `${window.location.origin}/invite/${token}`

function InvitationsTab() {
  const { toast } = useToast()
  const [items, setItems] = useState<AdminInvitation[] | null>(null)
  const [creating, setCreating] = useState(false)

  const load = useCallback(() => {
    adminApi.listInvitations()
      .then(setItems)
      .catch(() => toast({ title: '초대 목록 조회 실패', variant: 'destructive' }))
  }, [toast])

  useEffect(() => { load() }, [load])

  // http로 접속하면 클립보드 API가 없을 수 있다 — 그때는 표의 링크를 직접 복사
  const copy = async (token: string) => {
    try {
      await navigator.clipboard.writeText(inviteUrl(token))
      toast({ title: '초대 링크를 복사했습니다' })
    } catch {
      toast({ title: '복사하지 못했습니다', description: '표의 링크를 직접 복사하세요.', variant: 'destructive' })
    }
  }

  const create = async () => {
    setCreating(true)
    try {
      const inv = await adminApi.createInvitation()
      load()
      await copy(inv.token)
    } catch {
      toast({ title: '초대 링크 생성 실패', variant: 'destructive' })
    } finally {
      setCreating(false)
    }
  }

  const revoke = async (id: number) => {
    try {
      await adminApi.deleteInvitation(id)
      load()
    } catch {
      toast({ title: '초대 취소 실패', variant: 'destructive' })
    }
  }

  if (!items) {
    return <div className="flex justify-center py-10"><Loader2 className="h-5 w-5 animate-spin" /></div>
  }

  return (
    <div className="space-y-4 py-2">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <p className="text-sm text-muted-foreground">
          초대 링크로만 가입할 수 있습니다. 링크는 한 번만 쓸 수 있고 7일 뒤 만료됩니다.
        </p>
        <Button onClick={create} disabled={creating}>
          {creating ? <Loader2 className="h-4 w-4 mr-1 animate-spin" /> : <Plus className="h-4 w-4 mr-1" />}
          초대 링크 만들기
        </Button>
      </div>

      <Table>
        <TableHeader>
          <TableRow>
            <TableHead>링크</TableHead>
            <TableHead>상태</TableHead>
            <TableHead>가입자</TableHead>
            <TableHead>만든 날</TableHead>
            <TableHead>만료</TableHead>
            <TableHead className="w-24" />
          </TableRow>
        </TableHeader>
        <TableBody>
          {items.length === 0 ? (
            <TableRow>
              <TableCell colSpan={6} className="text-center text-muted-foreground py-8">
                아직 만든 초대 링크가 없습니다
              </TableCell>
            </TableRow>
          ) : items.map((inv) => (
            <TableRow key={inv.id}>
              <TableCell className="font-mono text-xs break-all">
                {inv.status === 'active' ? inviteUrl(inv.token) : '-'}
              </TableCell>
              <TableCell>
                <Badge variant={INVITATION_STATUS[inv.status].variant}>{INVITATION_STATUS[inv.status].label}</Badge>
              </TableCell>
              <TableCell>{inv.used_by_username ?? '-'}</TableCell>
              <TableCell>{inv.created_at ? new Date(inv.created_at + 'Z').toLocaleDateString() : '-'}</TableCell>
              <TableCell>{new Date(inv.expires_at + 'Z').toLocaleString()}</TableCell>
              <TableCell>
                {inv.status === 'active' && (
                  <div className="flex gap-1">
                    <Button variant="ghost" size="icon" title="링크 복사" onClick={() => copy(inv.token)}>
                      <Copy className="h-4 w-4" />
                    </Button>
                    <Button variant="ghost" size="icon" title="초대 취소" onClick={() => revoke(inv.id)}>
                      <Trash2 className="h-4 w-4" />
                    </Button>
                  </div>
                )}
              </TableCell>
            </TableRow>
          ))}
        </TableBody>
      </Table>
    </div>
  )
}

// ============ ETF Tags Tab ============

const ETF_TAG_FILTERS = [
  { label: '전체', value: 'all' },
  { label: '태그 없음', value: 'untagged' },
  { label: '수동 지정', value: 'manual' },
] as const

type ETFTagFilter = (typeof ETF_TAG_FILTERS)[number]['value']

function ETFTagsTab() {
  const { toast } = useToast()
  const [items, setItems] = useState<AdminETFTag[]>([])
  const [tagOptions, setTagOptions] = useState<string[]>([])
  const [loading, setLoading] = useState(false)
  const [filter, setFilter] = useState<ETFTagFilter>('all')
  const [query, setQuery] = useState('')
  const [savingCode, setSavingCode] = useState<string | null>(null)

  const fetchItems = useCallback(async () => {
    setLoading(true)
    try {
      const res = await adminApi.listETFTags()
      setItems(res.items)
      setTagOptions(res.tags)
    } catch {
      toast({ title: 'ETF 태그 목록 조회 실패', variant: 'destructive' })
    } finally {
      setLoading(false)
    }
  }, [toast])

  useEffect(() => {
    fetchItems()
  }, [fetchItems])

  const save = useCallback(async (code: string, tags: string[] | null) => {
    setSavingCode(code)
    try {
      const updated = await adminApi.updateETFTags(code, tags)
      setItems((prev) => prev.map((item) => (item.code === code ? updated : item)))
      if (tags === null) {
        toast({ title: '수동 지정을 해제했습니다', description: '다음 태깅(토요일 03:00) 때 자동으로 다시 정해집니다.' })
      }
    } catch {
      toast({ title: '태그 저장 실패', variant: 'destructive' })
    } finally {
      setSavingCode(null)
    }
  }, [toast])

  const q = query.trim().toLowerCase()
  const visible = items.filter((item) => {
    if (filter === 'untagged' && item.tags.length > 0) return false
    if (filter === 'manual' && !item.manual) return false
    return !q || item.name.toLowerCase().includes(q) || item.code.toLowerCase().includes(q)
  })

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center gap-2">
        {ETF_TAG_FILTERS.map((f) => (
          <Button
            key={f.value}
            variant={filter === f.value ? 'default' : 'outline'}
            size="sm"
            onClick={() => setFilter(f.value)}
          >
            {f.label}
          </Button>
        ))}
        <Input
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          placeholder="ETF 이름 또는 코드"
          className="w-56 h-8"
        />
        <span className="text-sm text-muted-foreground ml-2">
          {visible.length} / {items.length}개
        </span>
      </div>
      <p className="text-sm text-muted-foreground">
        태그를 바꾸면 수동 지정이 되어 매주 자동 태깅에서 제외됩니다. 해제하면 다음 태깅 때 자동으로 다시 정해집니다.
      </p>

      <Table>
        <TableHeader>
          <TableRow>
            <TableHead className="w-[90px]">코드</TableHead>
            <TableHead>ETF</TableHead>
            <TableHead>태그</TableHead>
            <TableHead className="w-[100px]">구분</TableHead>
          </TableRow>
        </TableHeader>
        <TableBody>
          {loading ? (
            <TableRow>
              <TableCell colSpan={4} className="text-center py-8 text-muted-foreground">
                로딩 중...
              </TableCell>
            </TableRow>
          ) : visible.length === 0 ? (
            <TableRow>
              <TableCell colSpan={4} className="text-center py-8 text-muted-foreground">
                데이터가 없습니다
              </TableCell>
            </TableRow>
          ) : (
            visible.map((item) => {
              const saving = savingCode === item.code
              const remaining = tagOptions.filter((t) => !item.tags.includes(t))
              return (
                <TableRow key={item.code}>
                  <TableCell className="font-mono text-sm">{item.code}</TableCell>
                  <TableCell>
                    <ETFLink code={item.code} name={item.name}>{item.name}</ETFLink>
                  </TableCell>
                  <TableCell>
                    <div className="flex flex-wrap items-center gap-1">
                      {item.tags.map((tag) => (
                        <Badge key={tag} variant="secondary" className="gap-1 pr-1">
                          {tag}
                          <button
                            type="button"
                            aria-label={`${tag} 태그 제거`}
                            disabled={saving}
                            onClick={() => save(item.code, item.tags.filter((t) => t !== tag))}
                            className="rounded-full hover:bg-muted-foreground/20 disabled:opacity-50"
                          >
                            <X className="w-3 h-3" />
                          </button>
                        </Badge>
                      ))}
                      <select
                        aria-label={`${item.name} 태그 추가`}
                        value=""
                        disabled={saving || remaining.length === 0}
                        onChange={(e) => e.target.value && save(item.code, [...item.tags, e.target.value])}
                        className="h-7 rounded-md border border-input bg-background px-2 text-xs disabled:opacity-50"
                      >
                        <option value="">+ 태그</option>
                        {remaining.map((t) => (
                          <option key={t} value={t}>{t}</option>
                        ))}
                      </select>
                      {saving && <Loader2 className="w-3 h-3 animate-spin text-muted-foreground" />}
                    </div>
                  </TableCell>
                  <TableCell>
                    {item.manual ? (
                      <div className="flex items-center gap-1">
                        <Badge>수동</Badge>
                        <Button
                          variant="ghost"
                          size="sm"
                          className="h-7 w-7 p-0"
                          title="수동 지정 해제"
                          disabled={saving}
                          onClick={() => save(item.code, null)}
                        >
                          <RotateCcw className="w-3.5 h-3.5" />
                        </Button>
                      </div>
                    ) : (
                      <Badge variant="outline">자동</Badge>
                    )}
                  </TableCell>
                </TableRow>
              )
            })
          )}
        </TableBody>
      </Table>
    </div>
  )
}

// ============ Code Examples Tab ============

interface SearchResult {
  id: number
  question: string
  question_generalized: string | null
  description: string | null
  distance: number
}

function CodeExamplesTab() {
  const { toast } = useToast()
  const [items, setItems] = useState<AdminCodeExample[]>([])
  const [total, setTotal] = useState(0)
  const [statusFilter, setStatusFilter] = useState('')
  const [loading, setLoading] = useState(false)
  const [dialogOpen, setDialogOpen] = useState(false)
  const [editItem, setEditItem] = useState<AdminCodeExample | null>(null)
  const [searchQuery, setSearchQuery] = useState('')
  const [searchResults, setSearchResults] = useState<SearchResult[] | null>(null)
  const [searching, setSearching] = useState(false)
  const [generalize, setGeneralize] = useState(false)
  const [queryGeneralized, setQueryGeneralized] = useState<string | null>(null)

  const fetchItems = useCallback(async () => {
    setLoading(true)
    try {
      const res = await adminApi.listCodeExamples(statusFilter || undefined)
      setItems(res.items)
      setTotal(res.total)
    } catch {
      toast({ title: '코드 예제 목록 조회 실패', variant: 'destructive' })
    } finally {
      setLoading(false)
    }
  }, [statusFilter, toast])

  useEffect(() => {
    fetchItems()
  }, [fetchItems])

  const handleArchive = useCallback(async (id: number) => {
    try {
      await adminApi.archiveCodeExample(id)
      toast({ title: '아카이브 처리되었습니다' })
      fetchItems()
    } catch {
      toast({ title: '아카이브 실패', variant: 'destructive' })
    }
  }, [fetchItems, toast])

  const handleSave = useCallback(async (form: { question: string; code: string; description: string }) => {
    try {
      if (editItem) {
        await adminApi.updateCodeExample(editItem.id, form)
        toast({ title: '수정되었습니다' })
      } else {
        await adminApi.createCodeExample(form)
        toast({ title: '추가되었습니다' })
      }
      setDialogOpen(false)
      setEditItem(null)
      fetchItems()
    } catch {
      toast({ title: '저장 실패', variant: 'destructive' })
    }
  }, [editItem, fetchItems, toast])

  const handleSearch = useCallback(async () => {
    if (!searchQuery.trim()) {
      setSearchResults(null)
      setQueryGeneralized(null)
      return
    }
    setSearching(true)
    try {
      const res = await adminApi.searchSimilarExamples(searchQuery.trim(), 5, generalize)
      setSearchResults(res.results)
      setQueryGeneralized(res.query_generalized)
    } catch {
      toast({ title: '유사도 검색 실패', variant: 'destructive' })
    } finally {
      setSearching(false)
    }
  }, [searchQuery, generalize, toast])

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <div className="flex flex-wrap items-center gap-2">
          {STATUS_FILTERS.codeExamples.map((f) => (
            <Button
              key={f.value}
              variant={statusFilter === f.value ? 'default' : 'outline'}
              size="sm"
              onClick={() => { setStatusFilter(f.value); setSearchResults(null); setSearchQuery('') }}
            >
              {f.label}
            </Button>
          ))}
          <span className="text-sm text-muted-foreground ml-2 whitespace-nowrap">총 {total}건</span>
        </div>
        <Button
          size="sm"
          onClick={() => { setEditItem(null); setDialogOpen(true) }}
        >
          <Plus className="w-4 h-4 mr-1" />
          추가
        </Button>
      </div>

      {statusFilter === 'embedded' && (
        <div className="space-y-2">
          <div className="flex gap-2 items-center">
            <div className="relative flex-1">
              <Search className="absolute left-2.5 top-2.5 h-4 w-4 text-muted-foreground" />
              <Input
                value={searchQuery}
                onChange={(e) => setSearchQuery(e.target.value)}
                onKeyDown={(e) => e.key === 'Enter' && handleSearch()}
                placeholder="질문을 입력하여 유사도 검색 테스트..."
                className="pl-9"
              />
            </div>
            <div className="flex items-center gap-1.5 shrink-0">
              <Switch checked={generalize} onCheckedChange={setGeneralize} />
              <Label className="text-sm cursor-pointer" onClick={() => setGeneralize(!generalize)}>일반화</Label>
            </div>
            <Button size="sm" onClick={handleSearch} disabled={searching || !searchQuery.trim()}>
              {searching ? <Loader2 className="w-4 h-4 animate-spin" /> : '검색'}
            </Button>
            {searchResults && (
              <Button size="sm" variant="ghost" onClick={() => { setSearchResults(null); setSearchQuery(''); setQueryGeneralized(null) }}>
                초기화
              </Button>
            )}
          </div>
          {queryGeneralized && (
            <div className="text-sm text-muted-foreground px-1">
              일반화 결과: <span className="text-foreground">{queryGeneralized}</span>
            </div>
          )}
        </div>
      )}

      {searchResults && (
        <div className="rounded-md border bg-muted/50 p-3 space-y-2">
          <div className="text-sm font-medium">유사도 검색 결과 ({searchResults.length}건)</div>
          {searchResults.length === 0 ? (
            <p className="text-sm text-muted-foreground">매칭된 예제가 없습니다.</p>
          ) : (
            searchResults.map((r) => (
              <div key={r.id} className="flex items-center gap-3 text-sm">
                <Badge variant="outline" className="shrink-0 w-16 justify-center">
                  {Math.round((1 - r.distance) * 100)}%
                </Badge>
                <span className="text-muted-foreground shrink-0">#{r.id}</span>
                <span className="truncate">{r.question}</span>
                {r.question_generalized && r.question_generalized !== r.question && (
                  <span className="text-muted-foreground truncate shrink-0 max-w-[200px]">
                    → {r.question_generalized}
                  </span>
                )}
              </div>
            ))
          )}
        </div>
      )}

      <Table>
        <TableHeader>
          <TableRow>
            <TableHead className="w-[60px]">ID</TableHead>
            <TableHead>Question</TableHead>
            <TableHead>일반화</TableHead>
            <TableHead className="w-[100px]">상태</TableHead>
            <TableHead className="w-[140px]">생성일</TableHead>
            <TableHead className="w-[100px]">작업</TableHead>
          </TableRow>
        </TableHeader>
        <TableBody>
          {loading ? (
            <TableRow>
              <TableCell colSpan={6} className="text-center py-8 text-muted-foreground">
                로딩 중...
              </TableCell>
            </TableRow>
          ) : items.length === 0 ? (
            <TableRow>
              <TableCell colSpan={6} className="text-center py-8 text-muted-foreground">
                데이터가 없습니다
              </TableCell>
            </TableRow>
          ) : (
            items.map((item) => {
              const match = searchResults?.find((r) => r.id === item.id)
              return (
                <TableRow key={item.id} className={match ? 'bg-primary/10' : undefined}>
                  <TableCell>
                    <div className="flex items-center gap-1">
                      {item.id}
                      {match && (
                        <Badge variant="secondary" className="text-[10px] px-1 py-0">
                          {Math.round((1 - match.distance) * 100)}%
                        </Badge>
                      )}
                    </div>
                  </TableCell>
                  <TableCell className="max-w-[300px] truncate">{item.question}</TableCell>
                  <TableCell className="max-w-[300px] truncate text-muted-foreground">
                    {item.question_generalized && item.question_generalized !== item.question
                      ? item.question_generalized
                      : <span className="text-muted-foreground/50">동일</span>}
                  </TableCell>
                  <TableCell>
                    <Badge variant={statusBadgeVariant(item.status)}>{item.status}</Badge>
                  </TableCell>
                  <TableCell className="text-sm text-muted-foreground">
                    {item.created_at ? new Date(item.created_at).toLocaleDateString() : '-'}
                  </TableCell>
                  <TableCell>
                    <div className="flex gap-1">
                      <Button
                        variant="ghost"
                        size="icon"
                        className="h-8 w-8"
                        onClick={() => { setEditItem(item); setDialogOpen(true) }}
                      >
                        <Pencil className="w-4 h-4" />
                      </Button>
                      {item.status === 'embedded' && (
                        <Button
                          variant="ghost"
                          size="icon"
                          className="h-8 w-8 text-destructive"
                          onClick={() => handleArchive(item.id)}
                        >
                          <Archive className="w-4 h-4" />
                        </Button>
                      )}
                    </div>
                  </TableCell>
                </TableRow>
              )
            })
          )}
        </TableBody>
      </Table>

      <CodeExampleDialog
        open={dialogOpen}
        onOpenChange={(open) => { setDialogOpen(open); if (!open) setEditItem(null) }}
        editItem={editItem}
        onSave={handleSave}
      />
    </div>
  )
}

function CodeExampleDialog({
  open,
  onOpenChange,
  editItem,
  onSave,
}: {
  open: boolean
  onOpenChange: (open: boolean) => void
  editItem: AdminCodeExample | null
  onSave: (form: { question: string; code: string; description: string }) => void
}) {
  const [question, setQuestion] = useState('')
  const [code, setCode] = useState('')
  const [description, setDescription] = useState('')
  const [saving, setSaving] = useState(false)

  useEffect(() => {
    if (open) {
      setQuestion(editItem?.question || '')
      setCode(editItem?.code || '')
      setDescription(editItem?.description || '')
    }
  }, [open, editItem])

  const hasChanges = editItem
    ? question !== editItem.question ||
      code !== editItem.code ||
      description !== (editItem.description ?? '')
    : true // 추가 모드에서는 항상 활성화

  const handleSubmit = async () => {
    if (!question.trim() || !code.trim()) return
    setSaving(true)
    await onSave({ question, code, description })
    setSaving(false)
  }

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="max-w-2xl max-h-[80vh] overflow-y-auto">
        <DialogHeader>
          <DialogTitle>{editItem ? '코드 예제 수정' : '코드 예제 추가'}</DialogTitle>
          <DialogDescription>
            {editItem ? '코드 예제를 수정합니다.' : '새 코드 예제를 추가합니다.'}
          </DialogDescription>
        </DialogHeader>
        <div className="space-y-4">
          <div>
            <Label htmlFor="question">Question</Label>
            <Input
              id="question"
              value={question}
              onChange={(e) => setQuestion(e.target.value)}
              placeholder="질문을 입력하세요"
            />
          </div>
          <div>
            <Label htmlFor="code">Code</Label>
            <Textarea
              id="code"
              value={code}
              onChange={(e) => setCode(e.target.value)}
              placeholder="코드를 입력하세요"
              rows={8}
              className="font-mono text-sm"
            />
          </div>
          <div>
            <Label htmlFor="description">Description</Label>
            <Textarea
              id="description"
              value={description}
              onChange={(e) => setDescription(e.target.value)}
              placeholder="설명 (선택)"
              rows={3}
            />
          </div>
        </div>
        <DialogFooter>
          <Button variant="outline" onClick={() => onOpenChange(false)}>취소</Button>
          <Button onClick={handleSubmit} disabled={saving || !question.trim() || !code.trim() || !hasChanges}>
            {saving ? '저장 중...' : '저장'}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}

// ============ Chat Logs Tab ============

function ChatLogsTab() {
  const { toast } = useToast()
  const [items, setItems] = useState<AdminChatLog[]>([])
  const [total, setTotal] = useState(0)
  const [statusFilter, setStatusFilter] = useState('')
  const [loading, setLoading] = useState(false)
  const [embedDialogOpen, setEmbedDialogOpen] = useState(false)
  const [embedTarget, setEmbedTarget] = useState<AdminChatLog | null>(null)
  const [detailDialog, setDetailDialog] = useState<AdminChatLog | null>(null)

  const fetchItems = useCallback(async () => {
    setLoading(true)
    try {
      const res = await adminApi.listChatLogs(statusFilter || undefined)
      setItems(res.items)
      setTotal(res.total)
    } catch {
      toast({ title: '채팅 로그 목록 조회 실패', variant: 'destructive' })
    } finally {
      setLoading(false)
    }
  }, [statusFilter, toast])

  useEffect(() => {
    fetchItems()
  }, [fetchItems])

  const handleReview = useCallback(async (id: number, action: string) => {
    try {
      await adminApi.reviewChatLog(id, action)
      toast({ title: action === 'approve' ? '승인되었습니다' : '거절되었습니다' })
      fetchItems()
    } catch {
      toast({ title: '리뷰 처리 실패', variant: 'destructive' })
    }
  }, [fetchItems, toast])

  const handleWithdraw = useCallback(async (id: number) => {
    try {
      await adminApi.withdrawChatLog(id)
      toast({ title: '철회되었습니다' })
      fetchItems()
    } catch {
      toast({ title: '철회 실패', variant: 'destructive' })
    }
  }, [fetchItems, toast])

  const handleEmbed = useCallback(async (form: { question?: string; code?: string; description?: string }) => {
    if (!embedTarget) return
    try {
      await adminApi.embedChatLog(embedTarget.id, form)
      toast({ title: '임베드되었습니다' })
      setEmbedDialogOpen(false)
      setEmbedTarget(null)
      fetchItems()
    } catch {
      toast({ title: '임베드 실패', variant: 'destructive' })
    }
  }, [embedTarget, fetchItems, toast])

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center gap-2">
        {STATUS_FILTERS.chatLogs.map((f) => (
          <Button
            key={f.value}
            variant={statusFilter === f.value ? 'default' : 'outline'}
            size="sm"
            onClick={() => setStatusFilter(f.value)}
          >
            {f.label}
          </Button>
        ))}
        <span className="text-sm text-muted-foreground ml-2 whitespace-nowrap">총 {total}건</span>
      </div>

      <Table>
        <TableHeader>
          <TableRow>
            <TableHead className="w-[60px]">ID</TableHead>
            <TableHead>Question</TableHead>
            <TableHead className="max-w-[200px]">Answer</TableHead>
            <TableHead className="w-[100px]">상태</TableHead>
            <TableHead className="w-[140px]">생성일</TableHead>
            <TableHead className="w-[160px]">작업</TableHead>
          </TableRow>
        </TableHeader>
        <TableBody>
          {loading ? (
            <TableRow>
              <TableCell colSpan={6} className="text-center py-8 text-muted-foreground">
                로딩 중...
              </TableCell>
            </TableRow>
          ) : items.length === 0 ? (
            <TableRow>
              <TableCell colSpan={6} className="text-center py-8 text-muted-foreground">
                데이터가 없습니다
              </TableCell>
            </TableRow>
          ) : (
            items.map((item) => (
              <TableRow key={item.id}>
                <TableCell>{item.id}</TableCell>
                <TableCell
                  className="max-w-[300px] truncate cursor-pointer hover:text-primary"
                  onClick={() => setDetailDialog(item)}
                >
                  {item.question}
                  {item.refined_question && (
                    <div className="text-xs text-muted-foreground truncate">→ {item.refined_question}</div>
                  )}
                </TableCell>
                <TableCell className="max-w-[200px] truncate text-muted-foreground">
                  {item.answer.slice(0, 80)}
                  {item.answer.length > 80 && '...'}
                </TableCell>
                <TableCell>
                  <Badge variant={statusBadgeVariant(item.status)}>{item.status}</Badge>
                </TableCell>
                <TableCell className="text-sm text-muted-foreground">
                  {new Date(item.created_at).toLocaleDateString()}
                </TableCell>
                <TableCell>
                  <div className="flex gap-1">
                    {(item.status === 'liked' || item.status === 'rejected') && (
                      <Button
                        variant="ghost"
                        size="icon"
                        className="h-8 w-8 text-green-600"
                        title="승인"
                        onClick={() => handleReview(item.id, 'approve')}
                      >
                        <Check className="w-4 h-4" />
                      </Button>
                    )}
                    {(item.status === 'liked' || item.status === 'approved') && (
                      <Button
                        variant="ghost"
                        size="icon"
                        className="h-8 w-8 text-destructive"
                        title="거절"
                        onClick={() => handleReview(item.id, 'reject')}
                      >
                        <X className="w-4 h-4" />
                      </Button>
                    )}
                    {item.status === 'approved' && (
                      <Button
                        variant="ghost"
                        size="icon"
                        className="h-8 w-8 text-blue-600"
                        title="임베드"
                        onClick={() => { setEmbedTarget(item); setEmbedDialogOpen(true) }}
                      >
                        <Upload className="w-4 h-4" />
                      </Button>
                    )}
                    {item.status === 'embedded' && (
                      <Button
                        variant="ghost"
                        size="icon"
                        className="h-8 w-8 text-orange-600"
                        title="철회"
                        onClick={() => handleWithdraw(item.id)}
                      >
                        <Undo2 className="w-4 h-4" />
                      </Button>
                    )}
                  </div>
                </TableCell>
              </TableRow>
            ))
          )}
        </TableBody>
      </Table>

      <EmbedDialog
        open={embedDialogOpen}
        onOpenChange={(open) => { setEmbedDialogOpen(open); if (!open) setEmbedTarget(null) }}
        chatLog={embedTarget}
        onEmbed={handleEmbed}
      />

      <ChatLogDetailDialog
        chatLog={detailDialog}
        onOpenChange={(open) => { if (!open) setDetailDialog(null) }}
      />
    </div>
  )
}

function EmbedDialog({
  open,
  onOpenChange,
  chatLog,
  onEmbed,
}: {
  open: boolean
  onOpenChange: (open: boolean) => void
  chatLog: AdminChatLog | null
  onEmbed: (form: { question?: string; code?: string; description?: string }) => void
}) {
  const [question, setQuestion] = useState('')
  const [code, setCode] = useState('')
  const [description, setDescription] = useState('')
  const [saving, setSaving] = useState(false)

  useEffect(() => {
    if (open && chatLog) {
      // 맥락에 기대는 원문보다 재작성된 독립 질문이 예시로 쓸모 있다
      setQuestion(chatLog.refined_question || chatLog.question)
      setCode(chatLog.generated_code || '')
      setDescription('')
    }
  }, [open, chatLog])

  const handleSubmit = async () => {
    setSaving(true)
    await onEmbed({ question, code, description })
    setSaving(false)
  }

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="max-w-2xl max-h-[80vh] overflow-y-auto">
        <DialogHeader>
          <DialogTitle>코드 예제로 임베드</DialogTitle>
          <DialogDescription>승인된 채팅 로그를 코드 예제로 변환합니다.</DialogDescription>
        </DialogHeader>
        <div className="space-y-4">
          <div>
            <Label htmlFor="embed-question">Question</Label>
            <Input
              id="embed-question"
              value={question}
              onChange={(e) => setQuestion(e.target.value)}
            />
          </div>
          <div>
            <Label htmlFor="embed-code">Code</Label>
            <Textarea
              id="embed-code"
              value={code}
              onChange={(e) => setCode(e.target.value)}
              rows={8}
              className="font-mono text-sm"
            />
          </div>
          <div>
            <Label htmlFor="embed-description">Description</Label>
            <Textarea
              id="embed-description"
              value={description}
              onChange={(e) => setDescription(e.target.value)}
              rows={3}
            />
          </div>
        </div>
        <DialogFooter>
          <Button variant="outline" onClick={() => onOpenChange(false)}>취소</Button>
          <Button onClick={handleSubmit} disabled={saving}>
            {saving ? '임베드 중...' : '임베드'}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}

function ChatLogDetailDialog({
  chatLog,
  onOpenChange,
}: {
  chatLog: AdminChatLog | null
  onOpenChange: (open: boolean) => void
}) {
  return (
    <Dialog open={!!chatLog} onOpenChange={onOpenChange}>
      <DialogContent className="max-w-2xl max-h-[80vh] overflow-y-auto">
        <DialogHeader>
          <DialogTitle>채팅 로그 상세</DialogTitle>
          <DialogDescription>ID: {chatLog?.id}</DialogDescription>
        </DialogHeader>
        {chatLog && (
          <div className="space-y-4">
            <div>
              <Label className="text-muted-foreground">Question</Label>
              <p className="mt-1 whitespace-pre-wrap">{chatLog.question}</p>
            </div>
            <div>
              <Label className="text-muted-foreground">Answer</Label>
              <p className="mt-1 whitespace-pre-wrap text-sm">{chatLog.answer}</p>
            </div>
            {chatLog.generated_code && (
              <div>
                <Label className="text-muted-foreground">Generated Code</Label>
                <pre className="mt-1 p-3 bg-muted rounded text-sm overflow-x-auto font-mono">
                  {chatLog.generated_code}
                </pre>
              </div>
            )}
            <div className="flex gap-4 text-sm text-muted-foreground">
              <span>상태: <Badge variant={statusBadgeVariant(chatLog.status)}>{chatLog.status}</Badge></span>
              <span>생성일: {new Date(chatLog.created_at).toLocaleString()}</span>
            </div>
          </div>
        )}
      </DialogContent>
    </Dialog>
  )
}
