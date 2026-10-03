import { useState, useRef, useEffect, useCallback, KeyboardEvent } from 'react'
import {
  Send, Loader2, MessageCircle, ChevronRight, Trash2, BookOpen, Plus, Pencil, Check, X, History, CornerDownRight,
} from 'lucide-react'
import { Card, CardContent } from '@/components/ui/card'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Textarea } from '@/components/ui/textarea'
import {
  Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle,
} from '@/components/ui/dialog'
import { chatApi } from '@/lib/api'
import type { ChatSessionDetail, ChatSessionSummary, ChatStep, MatchedCodeExample } from '@/types/api'
import ReactMarkdown from 'react-markdown'
import remarkGfm from 'remark-gfm'

const EXAMPLE_QUESTIONS = [
  '삼성전자를 가장 많이 보유한 ETF는?',
  '반도체 관련 ETF 목록 보여줘',
  'SK하이닉스를 보유한 ETF 중 배당 태그가 있는 건?',
  'KODEX 200과 비슷한 ETF는?',
]

interface DisplayMessage {
  role: 'user' | 'assistant'
  content: string
  refinedQuestion?: string | null
  steps?: ChatStep[]
  matchedExamples?: MatchedCodeExample[]
}

function toDisplayMessages(detail: ChatSessionDetail): DisplayMessage[] {
  return detail.messages.flatMap((m): DisplayMessage[] => [
    { role: 'user', content: m.question, refinedQuestion: m.refined_question },
    { role: 'assistant', content: m.answer, steps: m.steps },
  ])
}

export default function ChatPage() {
  const [sessions, setSessions] = useState<ChatSessionSummary[]>([])
  const [sessionId, setSessionId] = useState<number | null>(null)
  const [messages, setMessages] = useState<DisplayMessage[]>([])
  const [input, setInput] = useState('')
  const [isLoading, setIsLoading] = useState(false)
  const [isLoadingSession, setIsLoadingSession] = useState(false)
  const [streamingSteps, setStreamingSteps] = useState<ChatStep[]>([])
  const [streamingExamples, setStreamingExamples] = useState<MatchedCodeExample[]>([])
  const [showSessions, setShowSessions] = useState(false)
  const [deleteTarget, setDeleteTarget] = useState<ChatSessionSummary | null>(null)
  const messagesEndRef = useRef<HTMLDivElement>(null)
  const textareaRef = useRef<HTMLTextAreaElement>(null)

  const refreshSessions = useCallback(async () => {
    try {
      setSessions(await chatApi.listSessions())
    } catch { /* 목록은 다음 갱신 때 다시 시도 */ }
  }, [])

  useEffect(() => {
    refreshSessions()
  }, [refreshSessions])

  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' })
  }, [messages, isLoading, streamingSteps])

  const startNewChat = () => {
    setSessionId(null)
    setMessages([])
    setStreamingSteps([])
    setShowSessions(false)
    textareaRef.current?.focus()
  }

  const openSession = async (id: number) => {
    setShowSessions(false)
    if (id === sessionId) return
    setIsLoadingSession(true)
    try {
      const detail = await chatApi.getSession(id)
      setSessionId(detail.id)
      setMessages(toDisplayMessages(detail))
    } catch {
      refreshSessions()  // 다른 탭에서 지워졌을 수 있다
    } finally {
      setIsLoadingSession(false)
    }
  }

  const confirmDelete = async () => {
    if (!deleteTarget) return
    const id = deleteTarget.id
    setDeleteTarget(null)
    try {
      await chatApi.deleteSession(id)
    } finally {
      if (id === sessionId) startNewChat()
      refreshSessions()
    }
  }

  const renameSession = async (id: number, title: string) => {
    const updated = await chatApi.renameSession(id, title)
    setSessions((prev) => prev.map((s) => (s.id === id ? { ...s, title: updated.title } : s)))
  }

  const sendMessage = async (text: string) => {
    const trimmed = text.trim()
    if (!trimmed || isLoading) return

    const userMessage: DisplayMessage = { role: 'user', content: trimmed }
    let newMessages = [...messages, userMessage]
    setMessages(newMessages)
    setInput('')
    setIsLoading(true)
    setStreamingSteps([])
    setStreamingExamples([])

    const collectedSteps: ChatStep[] = []
    let collectedExamples: MatchedCodeExample[] = []

    const finish = (content: string) => {
      setMessages([
        ...newMessages,
        { role: 'assistant', content, steps: collectedSteps, matchedExamples: collectedExamples },
      ])
      setStreamingSteps([])
      setStreamingExamples([])
      setIsLoading(false)
      textareaRef.current?.focus()
    }

    chatApi.streamMessage(trimmed, sessionId, {
      onSession: ({ session_id }) => setSessionId(session_id),
      onRefinedQuestion: (question) => {
        newMessages = [...newMessages.slice(0, -1), { ...userMessage, refinedQuestion: question }]
        setMessages(newMessages)
      },
      onStep: (step) => {
        collectedSteps.push(step)
        setStreamingSteps([...collectedSteps])
      },
      onAnswer: (answer) => finish(answer),
      onError: (error) => finish(`죄송합니다. 오류가 발생했습니다: ${error}`),
      onMatchedExamples: (examples) => {
        collectedExamples = examples
        setStreamingExamples(examples)
      },
      // 새 세션 추가·최근 활동 순서를 반영
      onDone: () => refreshSessions(),
    })
  }

  const handleKeyDown = (e: KeyboardEvent<HTMLTextAreaElement>) => {
    if (e.key === 'Enter' && !e.shiftKey && !e.nativeEvent.isComposing) {
      e.preventDefault()
      sendMessage(input)
    }
  }

  const sessionList = (
    <SessionList
      sessions={sessions}
      activeId={sessionId}
      disabled={isLoading}
      onNew={startNewChat}
      onOpen={openSession}
      onRename={renameSession}
      onDelete={setDeleteTarget}
    />
  )

  return (
    <div className="flex gap-4 h-[calc(100dvh-6.5rem)] lg:h-[calc(100dvh-4rem)]">
      {/* Sessions (desktop) */}
      <aside className="hidden md:flex w-60 shrink-0 flex-col border-r pr-3">{sessionList}</aside>

      <div className="flex-1 min-w-0 flex flex-col relative">
        {/* Header */}
        <div className="mb-4">
          <div className="flex items-center justify-between gap-2">
            <h1 className="text-2xl font-bold flex items-center gap-2">
              <MessageCircle className="w-6 h-6" />
              ETF 챗봇
            </h1>
            <div className="flex gap-1 md:hidden">
              <Button variant="ghost" size="sm" onClick={() => setShowSessions((v) => !v)} disabled={isLoading}>
                <History className="w-4 h-4 mr-1" />
                대화 목록
              </Button>
              <Button variant="ghost" size="sm" onClick={startNewChat} disabled={isLoading}>
                <Plus className="w-4 h-4" />
              </Button>
            </div>
          </div>
        </div>

        {/* Sessions (mobile) */}
        {showSessions && (
          <div className="md:hidden absolute inset-x-0 top-12 z-10 max-h-[60%] flex flex-col rounded-md border bg-background p-2 shadow-lg">
            {sessionList}
          </div>
        )}

        {/* Messages */}
        <div className="flex-1 overflow-y-auto space-y-4 mb-4">
          {isLoadingSession && (
            <div className="flex justify-center py-8 text-muted-foreground">
              <Loader2 className="w-5 h-5 animate-spin" />
            </div>
          )}

          {messages.length === 0 && !isLoading && !isLoadingSession && (
            <div className="flex flex-col items-center justify-center h-full gap-6">
              <p className="text-muted-foreground text-sm">예시 질문을 클릭하거나 직접 입력하세요</p>
              <div className="flex flex-wrap justify-center gap-2">
                {EXAMPLE_QUESTIONS.map((q) => (
                  <button
                    key={q}
                    onClick={() => sendMessage(q)}
                    className="px-3 py-2 text-sm rounded-full border border-border bg-background hover:bg-muted transition-colors"
                  >
                    {q}
                  </button>
                ))}
              </div>
            </div>
          )}

          {!isLoadingSession && messages.map((msg, i) => (
            <div key={i} className={`flex ${msg.role === 'user' ? 'justify-end' : 'justify-start'}`}>
              <div className="max-w-[80%]">
                <Card
                  className={
                    msg.role === 'user' ? 'bg-primary text-primary-foreground' : 'bg-muted'
                  }
                >
                  <CardContent className="p-3 text-sm">
                    {msg.role === 'user' ? (
                      <span className="whitespace-pre-wrap">{msg.content}</span>
                    ) : (
                      <div className="prose prose-sm dark:prose-invert max-w-none prose-table:text-sm prose-td:px-2 prose-td:py-1 prose-th:px-2 prose-th:py-1 prose-th:text-left">
                        <ReactMarkdown remarkPlugins={[remarkGfm]}>
                          {msg.content}
                        </ReactMarkdown>
                      </div>
                    )}
                  </CardContent>
                </Card>
                {msg.refinedQuestion && (
                  <div
                    className="mt-1 text-xs text-muted-foreground flex items-start justify-end gap-1"
                    title="이전 대화를 반영해 다시 쓴 질문"
                  >
                    <CornerDownRight className="w-3 h-3 mt-0.5 shrink-0" />
                    <span>{msg.refinedQuestion}</span>
                  </div>
                )}
                {msg.matchedExamples && msg.matchedExamples.length > 0 && (
                  <MatchedExamplesView examples={msg.matchedExamples} />
                )}
                {msg.steps && msg.steps.length > 0 && <StepsView steps={msg.steps} />}
              </div>
            </div>
          ))}

          {/* Streaming state */}
          {isLoading && (
            <div className="flex justify-start">
              <div className="max-w-[80%]">
                <Card className="bg-muted">
                  <CardContent className="p-3 flex items-center gap-2 text-sm text-muted-foreground">
                    <Loader2 className="w-4 h-4 animate-spin" />
                    {streamingSteps.length > 0
                      ? `Step ${streamingSteps.length} 실행 중...`
                      : '생각 중...'}
                  </CardContent>
                </Card>
                {streamingExamples.length > 0 && (
                  <MatchedExamplesView examples={streamingExamples} />
                )}
                {streamingSteps.length > 0 && <StepsView steps={streamingSteps} defaultOpen />}
              </div>
            </div>
          )}

          <div ref={messagesEndRef} />
        </div>

        {/* Input */}
        <div className="flex gap-2 items-end">
          <Textarea
            ref={textareaRef}
            value={input}
            onChange={(e) => setInput(e.target.value)}
            onKeyDown={handleKeyDown}
            placeholder="ETF에 대해 질문하세요... (Enter로 전송, Shift+Enter로 줄바꿈)"
            disabled={isLoading || isLoadingSession}
            rows={1}
            className="resize-none min-h-[44px] max-h-[120px]"
          />
          <Button
            onClick={() => sendMessage(input)}
            disabled={isLoading || isLoadingSession || !input.trim()}
            size="icon"
            className="shrink-0 h-[44px] w-[44px]"
          >
            <Send className="w-4 h-4" />
          </Button>
        </div>
      </div>

      <Dialog open={deleteTarget !== null} onOpenChange={(open) => { if (!open) setDeleteTarget(null) }}>
        <DialogContent className="max-w-sm">
          <DialogHeader>
            <DialogTitle>대화 삭제</DialogTitle>
            <DialogDescription>
              '{deleteTarget?.title}' 대화를 삭제하시겠습니까? 이 작업은 되돌릴 수 없습니다.
            </DialogDescription>
          </DialogHeader>
          <DialogFooter className="gap-2 sm:gap-0">
            <Button variant="outline" onClick={() => setDeleteTarget(null)}>
              취소
            </Button>
            <Button variant="destructive" onClick={confirmDelete}>
              삭제
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  )
}

function SessionList({
  sessions, activeId, disabled, onNew, onOpen, onRename, onDelete,
}: {
  sessions: ChatSessionSummary[]
  activeId: number | null
  disabled: boolean
  onNew: () => void
  onOpen: (id: number) => void
  onRename: (id: number, title: string) => Promise<void>
  onDelete: (session: ChatSessionSummary) => void
}) {
  const [editingId, setEditingId] = useState<number | null>(null)
  const [editTitle, setEditTitle] = useState('')

  const submitRename = async () => {
    const title = editTitle.trim()
    if (editingId !== null && title) await onRename(editingId, title)
    setEditingId(null)
  }

  return (
    <>
      <Button variant="outline" size="sm" className="w-full mb-2" onClick={onNew} disabled={disabled}>
        <Plus className="w-4 h-4 mr-1" />
        새 대화
      </Button>
      <div className="flex-1 overflow-y-auto space-y-0.5">
        {sessions.length === 0 && (
          <p className="text-xs text-muted-foreground text-center py-4">대화 기록이 없습니다</p>
        )}
        {sessions.map((s) =>
          editingId === s.id ? (
            <div key={s.id} className="flex items-center gap-1 px-1 py-0.5">
              <Input
                value={editTitle}
                onChange={(e) => setEditTitle(e.target.value)}
                onKeyDown={(e) => {
                  if (e.key === 'Enter' && !e.nativeEvent.isComposing) submitRename()
                  if (e.key === 'Escape') setEditingId(null)
                }}
                maxLength={200}
                autoFocus
                className="h-7 text-sm"
              />
              <button onClick={submitRename} className="p-1 text-muted-foreground hover:text-foreground" aria-label="저장">
                <Check className="w-3.5 h-3.5" />
              </button>
              <button onClick={() => setEditingId(null)} className="p-1 text-muted-foreground hover:text-foreground" aria-label="취소">
                <X className="w-3.5 h-3.5" />
              </button>
            </div>
          ) : (
            <div
              key={s.id}
              className={`group flex items-center gap-1 rounded-md px-2 py-1.5 text-sm ${
                s.id === activeId ? 'bg-muted font-medium' : 'hover:bg-muted/60'
              }`}
            >
              <button
                onClick={() => onOpen(s.id)}
                disabled={disabled}
                className="flex-1 min-w-0 text-left truncate disabled:cursor-not-allowed"
                title={s.title}
              >
                {s.title}
              </button>
              <button
                onClick={() => { setEditingId(s.id); setEditTitle(s.title) }}
                disabled={disabled}
                className="p-1 text-muted-foreground hover:text-foreground opacity-100 md:opacity-0 md:group-hover:opacity-100"
                aria-label="이름 바꾸기"
              >
                <Pencil className="w-3 h-3" />
              </button>
              <button
                onClick={() => onDelete(s)}
                disabled={disabled}
                className="p-1 text-muted-foreground hover:text-destructive opacity-100 md:opacity-0 md:group-hover:opacity-100"
                aria-label="삭제"
              >
                <Trash2 className="w-3 h-3" />
              </button>
            </div>
          ),
        )}
      </div>
    </>
  )
}

function MatchedExamplesView({ examples }: { examples: MatchedCodeExample[] }) {
  return (
    <details className="mt-1">
      <summary className="text-xs text-muted-foreground cursor-pointer hover:text-foreground flex items-center gap-1 select-none">
        <BookOpen className="w-3 h-3" />
        참고 코드 예제 ({examples.length}건)
      </summary>
      <div className="mt-1 space-y-1">
        {examples.map((ex, i) => (
          <div key={i} className="text-xs border rounded p-2 bg-background space-y-0.5">
            <div className="flex items-center gap-2">
              <span className="font-medium">{ex.question}</span>
              <span className="text-muted-foreground shrink-0">
                유사도 {Math.round((1 - ex.distance) * 100)}%
              </span>
            </div>
            {ex.question_generalized && ex.question_generalized !== ex.question && (
              <div className="text-muted-foreground">
                일반화: {ex.question_generalized}
              </div>
            )}
            {ex.description && (
              <div className="text-muted-foreground">{ex.description}</div>
            )}
          </div>
        ))}
      </div>
    </details>
  )
}

function StepsView({ steps, defaultOpen = false }: { steps: ChatStep[]; defaultOpen?: boolean }) {
  return (
    <details className="mt-1" open={defaultOpen}>
      <summary className="text-xs text-muted-foreground cursor-pointer hover:text-foreground flex items-center gap-1 select-none">
        <ChevronRight className="w-3 h-3" />
        실행 과정 ({steps.length}단계)
      </summary>
      <div className="mt-1 space-y-1">
        {steps.map((step) => (
          <div key={step.step_number} className="text-xs border rounded p-2 bg-background space-y-1">
            <div className="font-medium text-muted-foreground">
              Step {step.step_number}
              {step.tool_calls.length > 0 && (
                <span className="ml-1 text-primary">
                  [{step.tool_calls.map((tc) => tc.name).join(', ')}]
                </span>
              )}
              {step.error && <span className="ml-1 text-destructive">Error</span>}
            </div>
            {step.code && (
              <pre className="bg-muted rounded p-1.5 overflow-x-auto text-[11px] leading-relaxed">
                {step.code}
              </pre>
            )}
            {step.observations && (
              <pre className="bg-muted rounded p-1.5 overflow-x-auto text-[11px] leading-relaxed max-h-40 overflow-y-auto">
                {step.observations}
              </pre>
            )}
          </div>
        ))}
      </div>
    </details>
  )
}
