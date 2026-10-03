import { useEffect } from 'react'
import { useLocation, useNavigate } from 'react-router-dom'
import type { Location } from 'react-router-dom'
import { useAuth } from '@/hooks/useAuth'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'
import AccountForm from '@/components/AccountForm'

export default function LoginPage() {
  const navigate = useNavigate()
  const location = useLocation()
  const from = (location.state as { from?: Location } | null)?.from
  const redirectTo = from ? `${from.pathname}${from.search}${from.hash}` : '/'
  const { isAuthenticated, isLoading, login } = useAuth()

  useEffect(() => {
    if (isAuthenticated && !isLoading) {
      navigate(redirectTo, { replace: true })
    }
  }, [isAuthenticated, isLoading, navigate, redirectTo])

  if (isLoading) {
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
          <CardTitle className="text-2xl">ETF Atlas</CardTitle>
          <CardDescription>
            로그인 후 이용할 수 있습니다. 계정이 없으면 관리자에게 초대 링크를 요청하세요.
          </CardDescription>
        </CardHeader>
        <CardContent>
          <AccountForm
            mode="login"
            submitLabel="로그인"
            onSubmit={({ username, password }) => login(username, password)}
          />
        </CardContent>
      </Card>
    </div>
  )
}
