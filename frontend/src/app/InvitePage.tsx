import { useEffect, useState } from 'react'
import { Link, useNavigate, useParams } from 'react-router-dom'
import { useAuth } from '@/hooks/useAuth'
import { authApi } from '@/lib/api'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'
import AccountForm from '@/components/AccountForm'

export default function InvitePage() {
  const { token = '' } = useParams<{ token: string }>()
  const navigate = useNavigate()
  const { isAuthenticated, isLoading, register } = useAuth()
  const [valid, setValid] = useState<boolean | null>(null)

  useEffect(() => {
    if (isAuthenticated && !isLoading) {
      navigate('/', { replace: true })
    }
  }, [isAuthenticated, isLoading, navigate])

  useEffect(() => {
    authApi.getInvitationStatus(token)
      .then((s) => setValid(s.valid))
      .catch(() => setValid(false))
  }, [token])

  if (isLoading || valid === null) {
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
          <CardTitle className="text-2xl">ETF Atlas 가입</CardTitle>
          <CardDescription>
            {valid
              ? '초대받은 멤버 계정을 만들어 주세요.'
              : '초대 링크가 유효하지 않거나 만료되었습니다. 관리자에게 새 링크를 요청하세요.'}
          </CardDescription>
        </CardHeader>
        <CardContent>
          {valid ? (
            <AccountForm
              mode="register"
              submitLabel="가입하기"
              onSubmit={(payload) => register(payload, token)}
            />
          ) : (
            <Button asChild variant="outline" className="w-full">
              <Link to="/login">로그인 페이지로</Link>
            </Button>
          )}
        </CardContent>
      </Card>
    </div>
  )
}
