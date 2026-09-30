import { useEffect } from 'react'
import { useNavigate } from 'react-router-dom'
import { useAuth } from '@/hooks/useAuth'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'
import AccountForm from '@/components/AccountForm'

export default function SetupPage() {
  const navigate = useNavigate()
  const { isLoading, setupRequired, setup } = useAuth()

  useEffect(() => {
    if (!isLoading && !setupRequired) {
      navigate('/', { replace: true })
    }
  }, [isLoading, setupRequired, navigate])

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
          <CardTitle className="text-2xl">ETF Atlas 초기 설정</CardTitle>
          <CardDescription>
            관리자 계정을 만들어 주세요. 이 계정은 관리 페이지 권한을 가집니다.
          </CardDescription>
        </CardHeader>
        <CardContent>
          <AccountForm mode="register" submitLabel="관리자 계정 생성" onSubmit={setup} />
        </CardContent>
      </Card>
    </div>
  )
}
