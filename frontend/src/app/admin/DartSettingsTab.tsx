import { useState, useEffect } from 'react'
import { useToast } from '@/hooks/use-toast'
import { adminApi } from '@/lib/api'
import type { AdminDartSettings, AdminDartTestResult } from '@/types/api'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { Loader2, Trash2 } from 'lucide-react'
import { AITestLine, SECRET_INPUT_PROPS, TabSpinner } from './common'

// ============ DART Settings Tab ============

export default function DartSettingsTab() {
  const { toast } = useToast()
  const [settings, setSettings] = useState<AdminDartSettings | null>(null)
  const [draft, setDraft] = useState('')  // 비워 두면 기존 값 유지
  const [saving, setSaving] = useState(false)
  const [testing, setTesting] = useState(false)
  const [testResult, setTestResult] = useState<AdminDartTestResult | null>(null)

  useEffect(() => {
    adminApi.getDartSettings()
      .then(setSettings)
      .catch(() => toast({ title: 'DART 설정 조회 실패', variant: 'destructive' }))
  }, [toast])

  const save = async (apiKey: string) => {
    setSaving(true)
    try {
      setSettings(await adminApi.updateDartSettings({ api_key: apiKey }))
      setDraft('')
      setTestResult(null)
      toast({ title: 'DART 설정을 저장했습니다', description: '다음 DART 수집부터 적용됩니다.' })
    } catch {
      toast({ title: 'DART 설정 저장 실패', variant: 'destructive' })
    } finally {
      setSaving(false)
    }
  }

  const saveDraft = () => {
    if (!draft.trim()) {
      toast({ title: '바꿀 값을 입력하세요' })
      return
    }
    save(draft.trim())
  }

  const test = async () => {
    setTesting(true)
    try {
      setTestResult(await adminApi.testDartSettings())
    } catch {
      toast({ title: '연결 테스트 실패', variant: 'destructive' })
    } finally {
      setTesting(false)
    }
  }

  if (!settings) {
    return <TabSpinner />
  }

  const current = settings.api_key_masked
  return (
    <div className="max-w-xl space-y-6 py-2">
      <p className="text-sm text-muted-foreground">
        챗봇 기업 분석의 실적·공시는 DART OpenAPI(opendart.fss.or.kr)에서 매일 수집합니다.
        키는 여기서만 저장합니다(암호화해 DB에 보관). 다음 DART 수집 DAG 실행부터 적용되며, 키가 없으면 수집을 건너뜁니다.
      </p>
      <div className="space-y-2">
        <Label htmlFor="dart-api-key">API 키</Label>
        <div className="flex flex-wrap items-center gap-2 text-sm text-muted-foreground">
          <span className="break-all">현재: {current ?? '없음'}</span>
          {current && (
            <Button variant="ghost" size="sm" className="h-6 px-2" onClick={() => save('')} disabled={saving}>
              <Trash2 className="h-3 w-3 mr-1" />삭제
            </Button>
          )}
        </div>
        <Input
          id="dart-api-key"
          {...SECRET_INPUT_PROPS}
          value={draft}
          onChange={(e) => setDraft(e.target.value)}
          placeholder="새 키 입력 — 비워 두면 기존 값 유지"
        />
      </div>
      <div className="flex flex-wrap gap-2">
        <Button onClick={saveDraft} disabled={saving}>
          {saving && <Loader2 className="h-4 w-4 mr-1 animate-spin" />}저장
        </Button>
        <Button variant="outline" onClick={test} disabled={testing}>
          {testing && <Loader2 className="h-4 w-4 mr-1 animate-spin" />}연결 테스트
        </Button>
      </div>
      {testResult && (
        <div className="text-sm">
          <AITestLine label="DART" ok={testResult.ok} error={testResult.error} />
        </div>
      )}
    </div>
  )
}
