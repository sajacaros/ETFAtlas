import { useEffect, useState } from 'react'
import { useNavigate, useSearchParams } from 'react-router-dom'
import { useAuth } from '@/hooks/useAuth'
import { setToken } from '@/lib/auth'

export default function AuthCallbackPage() {
  const navigate = useNavigate()
  const [searchParams] = useSearchParams()
  const { login } = useAuth()
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    const processCallback = async () => {
      const accessToken = searchParams.get('access_token')
      const errorParam = searchParams.get('error')
      const googleToken = searchParams.get('token')

      if (errorParam) {
        setError(errorParam)
        setTimeout(() => navigate('/login'), 3000)
        return
      }

      if (accessToken) {
        setToken(accessToken)
        navigate('/')
        return
      }

      if (googleToken) {
        try {
          await login(googleToken)
          navigate('/')
        } catch (err) {
          console.error('Login failed:', err)
          setError('로그인에 실패했습니다')
          setTimeout(() => navigate('/login'), 3000)
        }
        return
      }

      setError('잘못된 인증 요청입니다')
      setTimeout(() => navigate('/login'), 3000)
    }

    processCallback()
  }, [searchParams, navigate, login])

  if (error) {
    return (
      <div className="flex flex-col items-center justify-center min-h-[60vh] space-y-4">
        <div className="text-destructive text-lg">{error}</div>
        <div className="text-muted-foreground">잠시 후 로그인 페이지로 이동합니다...</div>
      </div>
    )
  }

  return (
    <div className="flex flex-col items-center justify-center min-h-[60vh] space-y-4">
      <div className="animate-spin rounded-full h-8 w-8 border-b-2 border-primary"></div>
      <div className="text-muted-foreground">로그인 처리 중...</div>
    </div>
  )
}
