import { useEffect, useState, FormEvent } from 'react'
import axios from 'axios'
import { useAuth } from '@/hooks/useAuth'
import { useToast } from '@/hooks/use-toast'
import { authApi } from '@/lib/api'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { Badge } from '@/components/ui/badge'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'
import { LogOut } from 'lucide-react'

function ProfileSection() {
  const { user, updateProfile } = useAuth()
  const { toast } = useToast()
  const [name, setName] = useState(user?.name ?? '')
  const [error, setError] = useState<string | null>(null)
  const [submitting, setSubmitting] = useState(false)

  useEffect(() => {
    setName(user?.name ?? '')
  }, [user?.name])

  const trimmed = name.trim()
  const changed = trimmed !== (user?.name ?? '')

  const handleSubmit = async (e: FormEvent) => {
    e.preventDefault()
    setError(null)
    if (!trimmed) {
      setError('이름을 입력하세요.')
      return
    }
    setSubmitting(true)
    try {
      await updateProfile(trimmed)
      toast({ title: '이름을 바꿨습니다' })
    } catch {
      setError('요청을 처리하지 못했습니다. 잠시 후 다시 시도하세요.')
    } finally {
      setSubmitting(false)
    }
  }

  return (
    <Card>
      <CardHeader>
        <CardTitle className="text-lg">기본 정보</CardTitle>
        <CardDescription>화면에 표시되는 이름을 바꿀 수 있습니다.</CardDescription>
      </CardHeader>
      <CardContent>
        <form onSubmit={handleSubmit} className="space-y-4">
          <div className="space-y-2">
            <Label htmlFor="profile-username">아이디</Label>
            <Input id="profile-username" value={user?.username ?? ''} disabled />
          </div>
          <div className="space-y-2">
            <Label htmlFor="profile-name">이름</Label>
            <Input
              id="profile-name"
              value={name}
              onChange={(e) => setName(e.target.value)}
              maxLength={255}
              required
            />
          </div>
          {error && <p className="text-sm text-destructive">{error}</p>}
          <div className="flex justify-end">
            <Button type="submit" disabled={submitting || !changed}>
              {submitting ? '저장 중...' : '저장'}
            </Button>
          </div>
        </form>
      </CardContent>
    </Card>
  )
}

function PasswordSection() {
  const { toast } = useToast()
  const [currentPassword, setCurrentPassword] = useState('')
  const [password, setPassword] = useState('')
  const [passwordConfirm, setPasswordConfirm] = useState('')
  const [error, setError] = useState<string | null>(null)
  const [submitting, setSubmitting] = useState(false)

  const handleSubmit = async (e: FormEvent) => {
    e.preventDefault()
    setError(null)
    if (password !== passwordConfirm) {
      setError('새 비밀번호가 일치하지 않습니다.')
      return
    }
    setSubmitting(true)
    try {
      await authApi.changePassword(currentPassword, password)
      setCurrentPassword('')
      setPassword('')
      setPasswordConfirm('')
      toast({ title: '비밀번호를 바꿨습니다', description: '다른 기기의 로그인은 모두 끊겼습니다.' })
    } catch (err) {
      const detail = axios.isAxiosError(err) ? err.response?.data?.detail : undefined
      setError(
        detail === 'Current password is incorrect' ? '현재 비밀번호가 맞지 않습니다.'
          : Array.isArray(detail) ? '새 비밀번호는 8자 이상, 72바이트 이하여야 합니다.'
            : '요청을 처리하지 못했습니다. 잠시 후 다시 시도하세요.',
      )
    } finally {
      setSubmitting(false)
    }
  }

  return (
    <Card>
      <CardHeader>
        <CardTitle className="text-lg">비밀번호 변경</CardTitle>
        <CardDescription>바꾸면 이 브라우저를 뺀 다른 기기의 로그인은 끊깁니다.</CardDescription>
      </CardHeader>
      <CardContent>
        <form onSubmit={handleSubmit} className="space-y-4">
          <div className="space-y-2">
            <Label htmlFor="current-password">현재 비밀번호</Label>
            <Input
              id="current-password"
              type="password"
              autoComplete="current-password"
              value={currentPassword}
              onChange={(e) => setCurrentPassword(e.target.value)}
              required
            />
          </div>
          <div className="space-y-2">
            <Label htmlFor="new-password">새 비밀번호</Label>
            <Input
              id="new-password"
              type="password"
              autoComplete="new-password"
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              minLength={8}
              required
            />
          </div>
          <div className="space-y-2">
            <Label htmlFor="new-password-confirm">새 비밀번호 확인</Label>
            <Input
              id="new-password-confirm"
              type="password"
              autoComplete="new-password"
              value={passwordConfirm}
              onChange={(e) => setPasswordConfirm(e.target.value)}
              required
            />
          </div>
          {error && <p className="text-sm text-destructive">{error}</p>}
          <div className="flex justify-end">
            <Button type="submit" disabled={submitting}>
              {submitting ? '처리 중...' : '비밀번호 바꾸기'}
            </Button>
          </div>
        </form>
      </CardContent>
    </Card>
  )
}

export default function ProfilePage() {
  const { user, logout } = useAuth()
  const displayName = user?.name || user?.username || ''

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between gap-4">
        <div className="flex items-center gap-4">
          <span className="flex h-12 w-12 shrink-0 items-center justify-center rounded-full bg-gradient-to-br from-slate-700 to-slate-900 text-lg font-semibold text-white">
            {displayName.charAt(0).toUpperCase() || '?'}
          </span>
          <div>
            <h1 className="text-2xl font-bold">프로필 설정</h1>
            <div className="mt-1 flex items-center gap-2 text-sm text-muted-foreground">
              {user?.username}
              <Badge variant="secondary">{user?.is_admin ? '관리자' : '사용자'}</Badge>
            </div>
          </div>
        </div>
        <Button variant="outline" onClick={logout}>
          <LogOut className="mr-2 h-4 w-4" />
          로그아웃
        </Button>
      </div>
      <div className="grid items-start gap-6 lg:grid-cols-2">
        <ProfileSection />
        <PasswordSection />
      </div>
    </div>
  )
}
