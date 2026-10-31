import { useState, useEffect } from 'react'
import { useToast } from '@/hooks/use-toast'
import { adminApi, getErrorDetail } from '@/lib/api'
import type { AdminAISettings, AdminAISettingField, AdminAITestResult } from '@/types/api'
import { Button } from '@/components/ui/button'
import { Badge } from '@/components/ui/badge'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { Loader2, RotateCcw } from 'lucide-react'
import { AITestLine, SECRET_INPUT_PROPS, TabSpinner } from './common'

// ============ AI Settings Tab ============

const AI_SETTING_GROUPS: {
  title: string
  description: string
  fields: { name: AdminAISettingField; label: string; secret?: boolean; placeholder: string }[]
}[] = [
  {
    title: 'LLM',
    description: '챗봇 답변, 질문 재작성·일반화, ETF 자동 태깅에 씁니다. OpenAI 호환 API(LiteLLM 프록시 등) 주소를 넣으세요.',
    fields: [
      { name: 'llm_api_base', label: 'API 주소', placeholder: 'https://example.com/v1' },
      { name: 'llm_api_key', label: 'API 키', secret: true, placeholder: '새 키 입력' },
      { name: 'llm_model', label: '모델', placeholder: '모델 이름' },
    ],
  },
  {
    title: '임베딩',
    description: '챗봇의 참고 예시 검색에 씁니다. 768차원 모델만 쓸 수 있고, 모델을 바꾸면 기존 예시를 다시 임베딩해야 검색이 맞게 됩니다.',
    fields: [
      { name: 'embedding_api_base', label: 'API 주소', placeholder: 'https://example.com/v1' },
      { name: 'embedding_api_key', label: 'API 키', secret: true, placeholder: '새 키 입력' },
      { name: 'embedding_model', label: '모델', placeholder: '모델 이름' },
    ],
  },
]

export default function AISettingsTab() {
  const { toast } = useToast()
  const [settings, setSettings] = useState<AdminAISettings | null>(null)
  const [drafts, setDrafts] = useState<Partial<Record<AdminAISettingField, string>>>({})  // 비워 두면 기존 값 유지
  const [saving, setSaving] = useState(false)
  const [testing, setTesting] = useState(false)
  const [testResult, setTestResult] = useState<AdminAITestResult | null>(null)

  useEffect(() => {
    adminApi.getAISettings()
      .then(setSettings)
      .catch(() => toast({ title: 'AI 설정 조회 실패', variant: 'destructive' }))
  }, [toast])

  const save = async (body: Partial<Record<AdminAISettingField, string>>) => {
    setSaving(true)
    try {
      setSettings(await adminApi.updateAISettings(body))
      setDrafts({})
      setTestResult(null)
      toast({ title: 'AI 설정을 저장했습니다', description: '다음 채팅 요청부터 적용됩니다.' })
    } catch (e: unknown) {
      const detail = getErrorDetail(e)
      toast({
        title: 'AI 설정 저장 실패',
        description: Array.isArray(detail) ? 'API 주소는 http:// 또는 https://로 시작해야 합니다' : undefined,
        variant: 'destructive',
      })
    } finally {
      setSaving(false)
    }
  }

  const saveDrafts = () => {
    const body = Object.fromEntries(
      Object.entries(drafts).map(([k, v]) => [k, v?.trim()]).filter(([, v]) => v),
    ) as Partial<Record<AdminAISettingField, string>>
    if (Object.keys(body).length === 0) {
      toast({ title: '바꿀 값을 입력하세요' })
      return
    }
    save(body)
  }

  const test = async () => {
    setTesting(true)
    try {
      setTestResult(await adminApi.testAISettings())
    } catch {
      toast({ title: '연결 테스트 실패', variant: 'destructive' })
    } finally {
      setTesting(false)
    }
  }

  if (!settings) {
    return <TabSpinner />
  }

  return (
    <div className="max-w-xl space-y-8 py-2">
      <p className="text-sm text-muted-foreground">
        여기서 저장한 값이 서버 환경변수(.env)보다 우선합니다. 비워 둔 항목은 환경변수 값을 씁니다.
        챗봇은 다음 요청부터, Airflow 태깅·임베딩 DAG는 다음 실행부터 적용됩니다.
      </p>

      {AI_SETTING_GROUPS.map((group) => (
        <section key={group.title} className="space-y-4">
          <div>
            <h3 className="font-semibold">{group.title}</h3>
            <p className="text-sm text-muted-foreground">{group.description}</p>
          </div>
          {group.fields.map((field) => {
            const current = settings[field.name]
            const id = `ai-${field.name}`
            return (
              <div key={field.name} className="space-y-2">
                <Label htmlFor={id}>{field.label}</Label>
                <div className="flex flex-wrap items-center gap-2 text-sm text-muted-foreground">
                  <span className="break-all">현재: {current.value ?? '없음'}</span>
                  <Badge variant={current.source === 'db' ? 'default' : 'outline'}>
                    {current.source === 'db' ? '관리자 설정' : '서버 환경변수'}
                  </Badge>
                  {current.source === 'db' && (
                    <Button
                      variant="ghost"
                      size="sm"
                      className="h-6 px-2"
                      onClick={() => save({ [field.name]: '' })}
                      disabled={saving}
                    >
                      <RotateCcw className="h-3 w-3 mr-1" />환경변수로 되돌리기
                    </Button>
                  )}
                </div>
                <Input
                  id={id}
                  {...(field.secret ? SECRET_INPUT_PROPS : { type: 'text', autoComplete: 'off' })}
                  value={drafts[field.name] ?? ''}
                  onChange={(e) => setDrafts((d) => ({ ...d, [field.name]: e.target.value }))}
                  placeholder={`${field.placeholder} — 비워 두면 기존 값 유지`}
                />
              </div>
            )
          })}
        </section>
      ))}

      <div className="flex flex-wrap gap-2">
        <Button onClick={saveDrafts} disabled={saving}>
          {saving && <Loader2 className="h-4 w-4 mr-1 animate-spin" />}저장
        </Button>
        <Button variant="outline" onClick={test} disabled={testing}>
          {testing && <Loader2 className="h-4 w-4 mr-1 animate-spin" />}연결 테스트
        </Button>
      </div>

      {testResult && (
        <div className="space-y-1 text-sm">
          <AITestLine label="LLM" ok={testResult.llm.ok} error={testResult.llm.error} />
          <AITestLine
            label="임베딩"
            ok={testResult.embedding.ok}
            error={testResult.embedding.error}
            detail={testResult.embedding.dim ? `${testResult.embedding.dim}차원` : undefined}
          />
        </div>
      )}
    </div>
  )
}
