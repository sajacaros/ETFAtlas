import { useState, useCallback, useEffect } from 'react'
import { useAuth } from '@/hooks/useAuth'
import { useToast } from '@/hooks/use-toast'
import { adminApi } from '@/lib/api'
import { copyText } from '@/lib/clipboard'
import { formatDateTime, formatServerDate } from '@/lib/date'
import type { AdminMember } from '@/types/api'
import { Button } from '@/components/ui/button'
import { Badge } from '@/components/ui/badge'
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
import { Loader2, Copy, Trash2, KeyRound, LogOut } from 'lucide-react'
import { TabSpinner } from './common'

// ============ Members Tab ============

const resetUrl = (token: string) => `${window.location.origin}/reset-password/${token}`

export default function MembersTab() {
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

  // 복사마저 실패하면 대화상자의 링크를 직접 복사
  const copyReset = async () => {
    if (!resetLink) return
    try {
      await copyText(resetLink.url)
      toast({ title: '재설정 링크를 복사했습니다' })
    } catch {
      toast({ title: '복사하지 못했습니다', description: '링크를 직접 복사하세요.', variant: 'destructive' })
    }
  }

  if (!items) {
    return <TabSpinner />
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
                <TableCell>{formatServerDate(m.created_at)}</TableCell>
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
