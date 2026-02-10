import { useNavigate } from 'react-router-dom'
import { useAuth } from '@/hooks/useAuth'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'
import { useEffect } from 'react'
import { GoogleLogin } from '@react-oauth/google'

export default function LoginPage() {
  const navigate = useNavigate()
  const { isAuthenticated, isLoading, login } = useAuth()

  useEffect(() => {
    if (isAuthenticated && !isLoading) {
      navigate('/')
    }
  }, [isAuthenticated, isLoading, navigate])

  const handleGoogleSuccess = async (credentialResponse: { credential?: string }) => {
    if (credentialResponse.credential) {
      try {
        await login(credentialResponse.credential)
        navigate('/')
      } catch (err) {
        console.error('Login failed:', err)
      }
    }
  }

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
            ETF 정보 관리 및 인사이트 서비스에 로그인하세요
          </CardDescription>
        </CardHeader>
        <CardContent className="space-y-4">
          <div className="flex justify-center">
            <GoogleLogin
              onSuccess={handleGoogleSuccess}
              onError={() => console.error('Google Login Failed')}
              size="large"
              width="350"
              text="continue_with"
            />
          </div>
          <p className="text-center text-sm text-muted-foreground">
            로그인하면 워치리스트와 AI 추천 기능을 사용할 수 있습니다
          </p>
        </CardContent>
      </Card>
    </div>
  )
}
