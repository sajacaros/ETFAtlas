import type { CSSProperties } from 'react'
import { Check, Loader2, X } from 'lucide-react'

export const STATUS_FILTERS = {
  codeExamples: [
    { label: '전체', value: '' },
    { label: 'Active', value: 'active' },
    { label: 'Embedded', value: 'embedded' },
  ],
  chatLogs: [
    { label: '전체', value: '' },
    { label: 'Liked', value: 'liked' },
    { label: 'Approved', value: 'approved' },
    { label: 'Rejected', value: 'rejected' },
    { label: 'Embedded', value: 'embedded' },
  ],
}

export function statusBadgeVariant(status: string): 'default' | 'secondary' | 'destructive' | 'outline' {
  switch (status) {
    case 'active':
    case 'approved':
    case 'embedded':
      return 'default'
    case 'liked':
      return 'secondary'
    case 'rejected':
      return 'destructive'
    default:
      return 'outline'
  }
}

// 비밀값 입력칸. type="password"로 두면 크롬이 로그인 폼으로 보고, 탭을 옮겨 칸이 사라질 때
// "비밀번호 저장" 창을 띄운다. 일반 텍스트 칸에 글자만 가려서 비밀번호 관리자가 무시하게 한다.
export const SECRET_INPUT_PROPS = {
  type: 'text',
  autoComplete: 'off',
  spellCheck: false,
  'data-1p-ignore': true,
  'data-lpignore': 'true',
  style: { WebkitTextSecurity: 'disc' } as CSSProperties,
} as const

// 탭이 처음 값을 받아 오는 동안 보여 주는 자리
export function TabSpinner() {
  return <div className="flex justify-center py-10"><Loader2 className="h-5 w-5 animate-spin" /></div>
}

export function AITestLine({ label, ok, error, detail }: { label: string; ok: boolean; error: string | null; detail?: string }) {
  return (
    <div className="flex items-start gap-2">
      {ok ? <Check className="h-4 w-4 mt-0.5 text-green-600 shrink-0" /> : <X className="h-4 w-4 mt-0.5 text-destructive shrink-0" />}
      <span>
        <span className="font-medium">{label}</span>
        {ok ? ` 연결 성공${detail ? ` (${detail})` : ''}` : ` 실패: ${error}`}
      </span>
    </div>
  )
}
