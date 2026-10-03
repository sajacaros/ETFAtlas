import { useEffect, useState, FormEvent } from 'react'
import { useParams } from 'react-router-dom'
import axios from 'axios'
import { authApi } from '@/lib/api'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'

export default function PasswordResetPage() {
  const { token = '' } = useParams<{ token: string }>()
  const [status, setStatus] = useState<{ valid: boolean; username: string | null } | null>(null)
  const [password, setPassword] = useState('')
  const [passwordConfirm, setPasswordConfirm] = useState('')
  const [error, setError] = useState<string | null>(null)
  const [submitting, setSubmitting] = useState(false)
  const [done, setDone] = useState(false)

  useEffect(() => {
    authApi.getPasswordResetStatus(token)
      .then(setStatus)
      .catch(() => setStatus({ valid: false, username: null }))
  }, [token])

  const handleSubmit = async (e: FormEvent) => {
    e.preventDefault()
    setError(null)
    if (password !== passwordConfirm) {
      setError('비밀번호가 일치하지 않습니다.')
      return
    }
    setSubmitting(true)
    try {
      await authApi.resetPassword(token, password)
      setDone(true)
    } catch (err) {
      const detail = axios.isAxiosError(err) ? err.response?.data?.detail : undefined
      setError(
        Array.isArray(detail) ? '비밀번호는 8자 이상이어야 합니다.'
          : detail === 'Invalid password reset link' ? '재설정 링크가 유효하지 않거나 만료되었습니다. 관리자에게 새 링크를 요청하세요.'
            : '요청을 처리하지 못했습니다. 잠시 후 다시 시도하세요.',
      )
    } finally {
      setSubmitting(false)
    }
  }

  if (status === null) {
    return (
      <div className="flex items-center justify-center min-h-[60vh]">
        <div className="text-muted-foreground">로딩 중...</div>
      </div>
    )
  }

  return (
    <div className="flex items-center justify-center min-h-[60vh]">
      <Card className="w-full max-w-md">
        <CardHeader className="text-center">
          <CardTitle className="text-2xl">비밀번호 재설정</CardTitle>
          <CardDescription>
            {done
              ? '비밀번호를 바꿨습니다. 새 비밀번호로 로그인하세요.'
              : status.valid
                ? `${status.username} 계정의 새 비밀번호를 입력하세요.`
                : '재설정 링크가 유효하지 않거나 만료되었습니다. 관리자에게 새 링크를 요청하세요.'}
          </CardDescription>
        </CardHeader>
        <CardContent>
          {status.valid && !done ? (
            <form onSubmit={handleSubmit} className="space-y-4">
              <div className="space-y-2">
                <Label htmlFor="reset-password">새 비밀번호</Label>
                <Input
                  id="reset-password"
                  type="password"
                  autoComplete="new-password"
                  value={password}
                  onChange={(e) => setPassword(e.target.value)}
                  minLength={8}
                  required
                />
              </div>
              <div className="space-y-2">
                <Label htmlFor="reset-password-confirm">비밀번호 확인</Label>
                <Input
                  id="reset-password-confirm"
                  type="password"
                  autoComplete="new-password"
                  value={passwordConfirm}
                  onChange={(e) => setPasswordConfirm(e.target.value)}
                  required
                />
              </div>
              {error && <p className="text-sm text-destructive">{error}</p>}
              <Button type="submit" className="w-full" disabled={submitting}>
                {submitting ? '처리 중...' : '비밀번호 바꾸기'}
              </Button>
            </form>
          ) : (
            // 전체 새로고침으로 이동: 재설정으로 이 브라우저의 세션이 끊겼을 수 있어 로그인 상태를 다시 확인한다
            <Button asChild variant="outline" className="w-full">
              <a href="/login">로그인 페이지로</a>
            </Button>
          )}
        </CardContent>
      </Card>
    </div>
  )
}
