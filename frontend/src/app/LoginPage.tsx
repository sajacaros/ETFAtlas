import { useEffect } from 'react'
import { useNavigate } from 'react-router-dom'
import { useAuth } from '@/hooks/useAuth'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'
import { Tabs, TabsList, TabsTrigger, TabsContent } from '@/components/ui/tabs'
import AccountForm from '@/components/AccountForm'

export default function LoginPage() {
  const navigate = useNavigate()
  const { isAuthenticated, isLoading, login, register } = useAuth()

  useEffect(() => {
    if (isAuthenticated && !isLoading) {
      navigate('/')
    }
  }, [isAuthenticated, isLoading, navigate])

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
            로그인하면 포트폴리오, 워치리스트, AI 챗봇을 사용할 수 있습니다
          </CardDescription>
        </CardHeader>
        <CardContent>
          <Tabs defaultValue="login">
            <TabsList className="grid w-full grid-cols-2 mb-4">
              <TabsTrigger value="login">로그인</TabsTrigger>
              <TabsTrigger value="register">회원가입</TabsTrigger>
            </TabsList>
            <TabsContent value="login">
              <AccountForm
                mode="login"
                submitLabel="로그인"
                onSubmit={({ username, password }) => login(username, password)}
              />
            </TabsContent>
            <TabsContent value="register">
              <AccountForm mode="register" submitLabel="가입하기" onSubmit={register} />
            </TabsContent>
          </Tabs>
        </CardContent>
      </Card>
    </div>
  )
}
