import { useState, FormEvent } from 'react'
import axios from 'axios'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import type { RegisterPayload } from '@/types/api'

interface AccountFormProps {
  mode: 'login' | 'register'
  submitLabel: string
  onSubmit: (payload: RegisterPayload) => Promise<void>
}

const ERROR_MESSAGES: Record<string, string> = {
  'Invalid username or password': '아이디 또는 비밀번호가 올바르지 않습니다.',
  'Username already exists': '이미 사용 중인 아이디입니다.',
  'Setup already completed': '이미 초기 설정이 완료되었습니다.',
  'Setup required first': '초기 설정이 먼저 필요합니다.',
}

function toErrorMessage(err: unknown): string {
  if (axios.isAxiosError(err)) {
    const detail = err.response?.data?.detail
    if (typeof detail === 'string') return ERROR_MESSAGES[detail] ?? detail
    if (Array.isArray(detail)) {
      return '아이디는 3~50자의 영문/숫자/._-, 비밀번호는 8자 이상이어야 합니다.'
    }
  }
  return '요청을 처리하지 못했습니다. 잠시 후 다시 시도하세요.'
}

export default function AccountForm({ mode, submitLabel, onSubmit }: AccountFormProps) {
  const [username, setUsername] = useState('')
  const [password, setPassword] = useState('')
  const [passwordConfirm, setPasswordConfirm] = useState('')
  const [name, setName] = useState('')
  const [error, setError] = useState<string | null>(null)
  const [submitting, setSubmitting] = useState(false)

  const handleSubmit = async (e: FormEvent) => {
    e.preventDefault()
    setError(null)
    if (mode === 'register' && password !== passwordConfirm) {
      setError('비밀번호가 일치하지 않습니다.')
      return
    }
    setSubmitting(true)
    try {
      await onSubmit({ username, password, name: name || undefined })
    } catch (err) {
      setError(toErrorMessage(err))
    } finally {
      setSubmitting(false)
    }
  }

  return (
    <form onSubmit={handleSubmit} className="space-y-4">
      <div className="space-y-2">
        <Label htmlFor={`${mode}-username`}>아이디</Label>
        <Input
          id={`${mode}-username`}
          autoComplete="username"
          value={username}
          onChange={(e) => setUsername(e.target.value)}
          required
        />
      </div>
      {mode === 'register' && (
        <div className="space-y-2">
          <Label htmlFor={`${mode}-name`}>이름 (선택)</Label>
          <Input id={`${mode}-name`} value={name} onChange={(e) => setName(e.target.value)} />
        </div>
      )}
      <div className="space-y-2">
        <Label htmlFor={`${mode}-password`}>비밀번호</Label>
        <Input
          id={`${mode}-password`}
          type="password"
          autoComplete={mode === 'login' ? 'current-password' : 'new-password'}
          value={password}
          onChange={(e) => setPassword(e.target.value)}
          required
        />
      </div>
      {mode === 'register' && (
        <div className="space-y-2">
          <Label htmlFor={`${mode}-password-confirm`}>비밀번호 확인</Label>
          <Input
            id={`${mode}-password-confirm`}
            type="password"
            autoComplete="new-password"
            value={passwordConfirm}
            onChange={(e) => setPasswordConfirm(e.target.value)}
            required
          />
        </div>
      )}
      {error && <p className="text-sm text-destructive">{error}</p>}
      <Button type="submit" className="w-full" disabled={submitting}>
        {submitting ? '처리 중...' : submitLabel}
      </Button>
    </form>
  )
}
