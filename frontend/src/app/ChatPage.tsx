import { useState, useRef, useEffect, useCallback, KeyboardEvent } from 'react'
import {
  Send, Square, Loader2, MessageCircle, ChevronLeft, ChevronRight, Trash2, BookOpen, Plus, Pencil, Check, X, History, CornerDownRight,
} from 'lucide-react'
import { Card, CardContent } from '@/components/ui/card'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Textarea } from '@/components/ui/textarea'
import {
  Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle,
} from '@/components/ui/dialog'
import { chatApi, type ChatStage } from '@/lib/api'
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
  sentAt?: Date
  refinedQuestion?: string | null
  steps?: ChatStep[]
  matchedExamples?: MatchedCodeExample[]
}

interface ChatStream {
  key: number  // 화면에서만 쓰는 식별자 (새 대화는 첫 이벤트가 올 때까지 세션 id가 없다)
  sessionId: number | null
  messages: DisplayMessage[]
  steps: ChatStep[]
  stage: ChatStage | null
  examples: MatchedCodeExample[]
  isStopping: boolean
  done: boolean  // 답변은 받았고 서버 저장을 기다리는 중
}

function toDisplayMessages(detail: ChatSessionDetail): DisplayMessage[] {
  return detail.messages.flatMap((m): DisplayMessage[] => [
    // created_at은 타임존 없는 UTC라 'Z'를 붙여 읽는다
    { role: 'user', content: m.question, refinedQuestion: m.refined_question, sentAt: new Date(m.created_at + 'Z') },
    { role: 'assistant', content: m.answer, steps: m.steps },
  ])
}

// 2026-09-28 오전 10:47
function formatSentAt(d: Date): string {
  const pad = (n: number) => String(n).padStart(2, '0')
  const time = d.toLocaleTimeString('ko-KR', { hour: 'numeric', minute: '2-digit' })
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())} ${time}`
}

export default function ChatPage() {
  const [sessions, setSessions] = useState<ChatSessionSummary[]>([])
  const [sessionId, setSessionId] = useState<number | null>(null)
  const [messages, setMessages] = useState<DisplayMessage[]>([])
  // 답변을 만드는 중인 대화들 — 세션마다 따로 돌고, 다른 세션을 보는 동안에도 이어진다 (서버는 답변이 끝나야 저장한다)
  const [streams, setStreams] = useState<ChatStream[]>([])
  const [input, setInput] = useState('')
  const [isLoadingSession, setIsLoadingSession] = useState(false)
  const [showSessions, setShowSessions] = useState(false)
  const [sessionsCollapsed, setSessionsCollapsed] = useState(false)
  const [deleteTarget, setDeleteTarget] = useState<ChatSessionSummary | null>(null)
  const messagesEndRef = useRef<HTMLDivElement>(null)
  const textareaRef = useRef<HTMLTextAreaElement>(null)
  const nextStreamKey = useRef(0)
  // 스트림 콜백에서 지금 보고 있는 세션을 읽기 위한 ref
  const sessionIdRef = useRef<number | null>(null)
  sessionIdRef.current = sessionId

  const viewedStream = streams.find((s) => s.sessionId === sessionId)
  const isAnswering = viewedStream !== undefined && !viewedStream.done
  const shownMessages = viewedStream ? viewedStream.messages : messages
  const runningIds = new Set(streams.filter((s) => !s.done && s.sessionId !== null).map((s) => s.sessionId as number))

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
  }, [shownMessages, viewedStream])

  const startNewChat = () => {
    setSessionId(null)
    setMessages([])
    setIsLoadingSession(false)
    setShowSessions(false)
    textareaRef.current?.focus()
  }

  const openSession = async (id: number) => {
    setShowSessions(false)
    if (id === sessionId) return
    setSessionId(id)
    if (streams.some((s) => s.sessionId === id)) {
      setIsLoadingSession(false)  // 진행 중인 대화는 화면에 들고 있는 걸 보여준다
      return
    }
    setMessages([])
    setIsLoadingSession(true)
    try {
      const detail = await chatApi.getSession(id)
      if (sessionIdRef.current !== id) return  // 기다리는 사이 다른 세션으로 옮겼다
      setMessages(toDisplayMessages(detail))
      setIsLoadingSession(false)
    } catch {
      if (sessionIdRef.current === id) {
        setSessionId(null)
        setIsLoadingSession(false)
      }
      refreshSessions()  // 다른 탭에서 지워졌을 수 있다
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
    if (!trimmed || isAnswering || isLoadingSession) return

    const key = nextStreamKey.current++
    let streamSessionId = sessionId
    const isViewing = () => sessionIdRef.current === streamSessionId
    const updateStream = (patch: Partial<ChatStream>) =>
      setStreams((prev) => prev.map((s) => (s.key === key ? { ...s, ...patch } : s)))

    const userMessage: DisplayMessage = { role: 'user', content: trimmed, sentAt: new Date() }
    let newMessages = [...shownMessages, userMessage]
    setStreams((prev) => [
      // 같은 세션에서 저장을 기다리던 지난 스트림은 이번 것으로 대신한다
      ...prev.filter((s) => s.sessionId !== sessionId),
      { key, sessionId, messages: newMessages, steps: [], stage: null, examples: [], isStopping: false, done: false },
    ])
    setInput('')

    let collectedSteps: ChatStep[] = []
    // 같은 step_number가 있으면 결과로 바꾸고, 없으면 뒤에 붙인다
    const upsertStep = (step: ChatStep) => {
      const exists = collectedSteps.some((s) => s.step_number === step.step_number)
      collectedSteps = exists
        ? collectedSteps.map((s) => (s.step_number === step.step_number ? step : s))
        : [...collectedSteps, step]
      updateStream({ steps: collectedSteps })
    }
    let collectedExamples: MatchedCodeExample[] = []

    const finish = (content: string) => {
      newMessages = [
        ...newMessages,
        {
          role: 'assistant', content, matchedExamples: collectedExamples,
          steps: collectedSteps.filter((s) => !s.running),  // 결과 없이 끝난 단계는 남기지 않는다
        },
      ]
      // 서버 저장이 끝날 때까지는 스트림이 들고 있는 대화를 보여준다
      updateStream({ messages: newMessages, steps: [], examples: [], isStopping: false, done: true })
      if (isViewing()) textareaRef.current?.focus()
    }

    chatApi.streamMessage(trimmed, sessionId, {
      onSession: ({ session_id }) => {
        if (isViewing()) setSessionId(session_id)
        streamSessionId = session_id
        updateStream({ sessionId: session_id })
        refreshSessions()  // 새 대화도 바로 목록에 올려 다른 세션에 갔다 돌아올 수 있게 한다
      },
      onStatus: (stage) => updateStream({ stage }),
      onRefinedQuestion: (question) => {
        newMessages = [...newMessages.slice(0, -1), { ...userMessage, refinedQuestion: question }]
        updateStream({ messages: newMessages })
      },
      onStepStart: (step) => upsertStep({ ...step, observations: '', error: null, running: true }),
      onStep: (step) => upsertStep(step),
      onAnswer: (answer) => finish(answer),
      onError: (error) => finish(`죄송합니다. 오류가 발생했습니다: ${error}`),
      onMatchedExamples: (examples) => {
        collectedExamples = examples
        updateStream({ examples })
      },
      onDone: () => {
        if (isViewing()) setMessages(newMessages)
        setStreams((prev) => prev.filter((s) => s.key !== key))
        refreshSessions()  // 새 세션 추가·최근 활동 순서를 반영
      },
    })
  }

  const stopMessage = async () => {
    const stream = viewedStream
    if (!stream || stream.sessionId === null || stream.isStopping) return
    setStreams((prev) => prev.map((s) => (s.key === stream.key ? { ...s, isStopping: true } : s)))
    try {
      await chatApi.stopMessage(stream.sessionId)
    } catch { /* 이미 끝났으면 404 — 스트림이 곧 마무리된다 */ }
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
      runningIds={runningIds}
      onNew={startNewChat}
      onOpen={openSession}
      onRename={renameSession}
      onDelete={setDeleteTarget}
    />
  )

  return (
    <div className="flex gap-4 h-[calc(100dvh-6.5rem)] lg:h-[calc(100dvh-4rem)]">
      {/* Sessions (desktop) */}
      <div className="hidden md:flex shrink-0">
        {!sessionsCollapsed && <aside className="w-60 flex flex-col border-r pr-3">{sessionList}</aside>}
        <button
          type="button"
          onClick={() => setSessionsCollapsed((v) => !v)}
          className="self-center ml-1 h-20 w-6 flex items-center justify-center rounded-md border bg-background text-muted-foreground hover:text-foreground hover:bg-muted"
          aria-label={sessionsCollapsed ? '대화 목록 펼치기' : '대화 목록 접기'}
          title={sessionsCollapsed ? '대화 목록 펼치기' : '대화 목록 접기'}
        >
          {sessionsCollapsed ? <ChevronRight className="w-5 h-5" /> : <ChevronLeft className="w-5 h-5" />}
        </button>
      </div>

      <div className="flex-1 min-w-0 flex flex-col relative">
        {/* Header */}
        <div className="mb-4">
          <div className="flex items-center justify-between gap-2">
            <h1 className="text-2xl font-bold flex items-center gap-2">
              <MessageCircle className="w-6 h-6" />
              ETF 챗봇
            </h1>
            <div className="flex gap-1 md:hidden">
              <Button variant="ghost" size="sm" onClick={() => setShowSessions((v) => !v)}>
                <History className="w-4 h-4 mr-1" />
                대화 목록
              </Button>
              <Button variant="ghost" size="sm" onClick={startNewChat}>
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

          {shownMessages.length === 0 && !viewedStream && !isLoadingSession && (
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

          {!isLoadingSession && shownMessages.map((msg, i) => (
            <div key={i} className={`flex ${msg.role === 'user' ? 'justify-end' : 'justify-start'}`}>
              <div className="max-w-[80%]">
                {msg.sentAt && (
                  <div className="mb-1 text-right text-xs text-muted-foreground">{formatSentAt(msg.sentAt)}</div>
                )}
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
          {viewedStream && !viewedStream.done && (
            <div className="flex justify-start">
              <div className="max-w-[80%]">
                <Card className="bg-muted">
                  <CardContent className="p-3 flex items-center gap-2 text-sm text-muted-foreground">
                    <Loader2 className="w-4 h-4 animate-spin" />
                    <span className="truncate">
                      {streamingStatus(viewedStream.steps, viewedStream.stage, viewedStream.isStopping)}
                    </span>
                  </CardContent>
                </Card>
                {viewedStream.examples.length > 0 && (
                  <MatchedExamplesView examples={viewedStream.examples} />
                )}
                {viewedStream.steps.length > 0 && <StepsView steps={viewedStream.steps} defaultOpen />}
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
            placeholder="ETF에 대해 질문하세요. 포트폴리오는 /portfolio 키 (Enter로 전송, Shift+Enter로 줄바꿈)"
            disabled={isAnswering || isLoadingSession}
            rows={1}
            className="resize-none min-h-[44px] max-h-[120px]"
          />
          {isAnswering ? (
            <Button
              onClick={stopMessage}
              disabled={viewedStream.sessionId === null || viewedStream.isStopping}
              size="icon"
              variant="outline"
              title="중지 (실행 중인 단계는 끝까지 기다립니다)"
              className="shrink-0 h-[44px] w-[44px]"
            >
              {viewedStream.isStopping ? <Loader2 className="w-4 h-4 animate-spin" /> : <Square className="w-4 h-4 fill-current" />}
            </Button>
          ) : (
            <Button
              onClick={() => sendMessage(input)}
              disabled={isLoadingSession || !input.trim()}
              size="icon"
              className="shrink-0 h-[44px] w-[44px]"
            >
              <Send className="w-4 h-4" />
            </Button>
          )}
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
  sessions, activeId, runningIds, onNew, onOpen, onRename, onDelete,
}: {
  sessions: ChatSessionSummary[]
  activeId: number | null
  runningIds: Set<number>
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
      <Button variant="outline" size="sm" className="w-full mb-2" onClick={onNew}>
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
                className="flex-1 min-w-0 text-left truncate"
                title={s.title}
              >
                {s.title}
              </button>
              {runningIds.has(s.id) && (
                <Loader2 className="w-3 h-3 shrink-0 animate-spin text-muted-foreground" aria-label="답변 생성 중" />
              )}
              <button
                onClick={() => { setEditingId(s.id); setEditTitle(s.title) }}
                className="p-1 text-muted-foreground hover:text-foreground opacity-100 md:opacity-0 md:group-hover:opacity-100"
                aria-label="이름 바꾸기"
              >
                <Pencil className="w-3 h-3" />
              </button>
              <button
                onClick={() => onDelete(s)}
                disabled={runningIds.has(s.id)}  // 답변이 끝나야 저장되므로 진행 중에는 지우지 않는다
                className="p-1 text-muted-foreground hover:text-destructive opacity-100 md:opacity-0 md:group-hover:opacity-100 disabled:hidden"
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

const STAGE_LABELS: Record<ChatStage, string> = {
  refining: '질문 이해 중...',
  searching_examples: '예시 찾는 중...',
  thinking: '생각 중...',
}

function streamingStatus(steps: ChatStep[], stage: ChatStage | null, isStopping: boolean) {
  const running = steps.filter((s) => s.running)
  if (isStopping) return running.length > 0 ? '중지 요청됨 — 실행 중인 단계가 끝나면 멈춰요...' : '중지하는 중...'
  if (running.length > 0) {
    const names = running.flatMap((s) => s.tool_calls.map((tc) => tc.name)).join(', ')
    return `Step ${running[0].step_number} 실행 중... [${names}]`
  }
  if (steps.length > 0 || !stage) return '생각 중...'  // 다음 도구를 고르거나 답변을 쓰는 중
  return STAGE_LABELS[stage]
}

function StepsView({ steps, defaultOpen = false }: { steps: ChatStep[]; defaultOpen?: boolean }) {
  return (
    <details className="mt-1 group" open={defaultOpen}>
      <summary className="text-xs text-muted-foreground cursor-pointer hover:text-foreground flex items-center gap-1 select-none">
        <ChevronRight className="w-3 h-3 transition-transform group-open:rotate-90" />
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
              {step.running && <Loader2 className="ml-1 inline w-3 h-3 animate-spin" />}
            </div>
            {step.code && (
              <pre className="bg-muted rounded p-1.5 overflow-x-auto text-[11px] leading-relaxed">
                {step.code}
              </pre>
            )}
            {step.running && <div className="text-muted-foreground">결과를 기다리는 중...</div>}
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
