import { useState, useEffect } from 'react'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { Textarea } from '@/components/ui/textarea'
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
  DialogFooter,
  DialogDescription,
} from '@/components/ui/dialog'

export interface ExampleForm { question: string; body: string; description: string }

// 예제 추가·수정과 채팅 로그 임베드가 같이 쓰는 질문·본문·설명 입력 대화상자
export default function ExampleFormDialog({
  open,
  onOpenChange,
  initial,
  title,
  description: dialogDescription,
  idPrefix = '',
  bodyLabel,
  placeholders,
  canSubmit = () => true,
  submitLabel,
  submittingLabel,
  onSubmit,
}: {
  open: boolean
  onOpenChange: (open: boolean) => void
  initial: ExampleForm | null  // 열릴 때 칸을 이 값으로 채운다 (null이면 그대로 둔다)
  title: string
  description: string
  idPrefix?: string
  bodyLabel: string
  placeholders?: Partial<ExampleForm>
  canSubmit?: (form: ExampleForm) => boolean
  submitLabel: string
  submittingLabel: string
  onSubmit: (form: ExampleForm) => Promise<void>
}) {
  const [question, setQuestion] = useState('')
  const [body, setBody] = useState('')
  const [description, setDescription] = useState('')
  const [saving, setSaving] = useState(false)

  useEffect(() => {
    if (open && initial) {
      setQuestion(initial.question)
      setBody(initial.body)
      setDescription(initial.description)
    }
  }, [open, initial])

  const form = { question, body, description }

  const handleSubmit = async () => {
    if (!canSubmit(form)) return
    setSaving(true)
    try {
      await onSubmit(form)
    } finally {
      setSaving(false)
    }
  }

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="max-w-2xl max-h-[80vh] overflow-y-auto">
        <DialogHeader>
          <DialogTitle>{title}</DialogTitle>
          <DialogDescription>{dialogDescription}</DialogDescription>
        </DialogHeader>
        <div className="space-y-4">
          <div>
            <Label htmlFor={`${idPrefix}question`}>Question</Label>
            <Input
              id={`${idPrefix}question`}
              value={question}
              onChange={(e) => setQuestion(e.target.value)}
              placeholder={placeholders?.question}
            />
          </div>
          <div>
            <Label htmlFor={`${idPrefix}code`}>{bodyLabel}</Label>
            <Textarea
              id={`${idPrefix}code`}
              value={body}
              onChange={(e) => setBody(e.target.value)}
              placeholder={placeholders?.body}
              rows={8}
              className="font-mono text-sm"
            />
          </div>
          <div>
            <Label htmlFor={`${idPrefix}description`}>Description</Label>
            <Textarea
              id={`${idPrefix}description`}
              value={description}
              onChange={(e) => setDescription(e.target.value)}
              placeholder={placeholders?.description}
              rows={3}
            />
          </div>
        </div>
        <DialogFooter>
          <Button variant="outline" onClick={() => onOpenChange(false)}>취소</Button>
          <Button onClick={handleSubmit} disabled={saving || !canSubmit(form)}>
            {saving ? submittingLabel : submitLabel}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}
