import { useState, useCallback, useEffect } from 'react'
import { useToast } from '@/hooks/use-toast'
import { adminApi } from '@/lib/api'
import { copyText } from '@/lib/clipboard'
import { formatDateTime, formatServerDate } from '@/lib/date'
import type { AdminInvitation } from '@/types/api'
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
import { Plus, Loader2, Copy, Trash2 } from 'lucide-react'
import { TabSpinner } from './common'

// ============ Invitations Tab ============

const INVITATION_STATUS: Record<AdminInvitation['status'], { label: string; variant: 'default' | 'secondary' | 'outline' }> = {
  active: { label: '사용 가능', variant: 'default' },
  used: { label: '사용됨', variant: 'secondary' },
  expired: { label: '만료', variant: 'outline' },
}

const inviteUrl = (token: string) => `${window.location.origin}/invite/${token}`

export default function InvitationsTab() {
  const { toast } = useToast()
  const [items, setItems] = useState<AdminInvitation[] | null>(null)
  const [creating, setCreating] = useState(false)

  const load = useCallback(() => {
    adminApi.listInvitations()
      .then(setItems)
      .catch(() => toast({ title: '초대 목록 조회 실패', variant: 'destructive' }))
  }, [toast])

  useEffect(() => { load() }, [load])

  // 복사마저 실패하면 표의 링크를 직접 복사
  const copy = async (token: string) => {
    try {
      await copyText(inviteUrl(token))
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
    return <TabSpinner />
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
              <TableCell>{formatServerDate(inv.created_at)}</TableCell>
              <TableCell>{formatDateTime(inv.expires_at)}</TableCell>
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
