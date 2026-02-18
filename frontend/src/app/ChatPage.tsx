import { useState, useRef, useEffect, KeyboardEvent } from 'react'
import { Send, Loader2, MessageCircle, ChevronRight, Trash2 } from 'lucide-react'
import { Card, CardContent } from '@/components/ui/card'
import { Button } from '@/components/ui/button'
import { Textarea } from '@/components/ui/textarea'
import { chatApi } from '@/lib/api'
import type { ChatMessage, ChatStep } from '@/types/api'
import ReactMarkdown from 'react-markdown'
import remarkGfm from 'remark-gfm'

const EXAMPLE_QUESTIONS = [
  '삼성전자를 가장 많이 보유한 ETF는?',
  '반도체 관련 ETF 목록 보여줘',
  'SK하이닉스를 보유한 ETF 중 배당 태그가 있는 건?',
  'KODEX 200과 비슷한 ETF는?',
]

interface DisplayMessage extends ChatMessage {
  steps?: ChatStep[]
}

export default function ChatPage() {
  const [messages, setMessages] = useState<DisplayMessage[]>([])
  const [input, setInput] = useState('')
  const [isLoading, setIsLoading] = useState(false)
  const [streamingSteps, setStreamingSteps] = useState<ChatStep[]>([])
  const messagesEndRef = useRef<HTMLDivElement>(null)
  const textareaRef = useRef<HTMLTextAreaElement>(null)

  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' })
  }, [messages, isLoading, streamingSteps])

  const sendMessage = async (text: string) => {
    const trimmed = text.trim()
    if (!trimmed || isLoading) return

    const userMessage: DisplayMessage = { role: 'user', content: trimmed }
    const newMessages = [...messages, userMessage]
    setMessages(newMessages)
    setInput('')
    setIsLoading(true)
    setStreamingSteps([])

    const history = messages.map((m) => ({ role: m.role, content: m.content }))
    const collectedSteps: ChatStep[] = []

    chatApi.streamMessage(
      trimmed,
      history,
      (step) => {
        collectedSteps.push(step)
        setStreamingSteps([...collectedSteps])
      },
      (answer) => {
        setMessages([
          ...newMessages,
          { role: 'assistant', content: answer, steps: collectedSteps },
        ])
        setStreamingSteps([])
        setIsLoading(false)
        textareaRef.current?.focus()
      },
      (error) => {
        setMessages([
          ...newMessages,
          {
            role: 'assistant',
            content: `죄송합니다. 오류가 발생했습니다: ${error}`,
            steps: collectedSteps,
          },
        ])
        setStreamingSteps([])
        setIsLoading(false)
        textareaRef.current?.focus()
      },
    )
  }

  const handleKeyDown = (e: KeyboardEvent<HTMLTextAreaElement>) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault()
      sendMessage(input)
    }
  }

  return (
    <div className="max-w-3xl mx-auto flex flex-col" style={{ height: 'calc(100vh - 7rem)' }}>
      {/* Header */}
      <div className="mb-4">
        <div className="flex items-center justify-between">
          <h1 className="text-2xl font-bold flex items-center gap-2">
            <MessageCircle className="w-6 h-6" />
            ETF 챗봇
          </h1>
          {messages.length > 0 && (
            <Button
              variant="ghost"
              size="sm"
              onClick={() => { setMessages([]); setStreamingSteps([]) }}
              disabled={isLoading}
              className="text-muted-foreground hover:text-destructive"
            >
              <Trash2 className="w-4 h-4 mr-1" />
              대화 초기화
            </Button>
          )}
        </div>
        <p className="text-muted-foreground">
          ETF에 대해 자유롭게 질문하세요. 그래프 DB에서 데이터를 조회하여 답변합니다.
        </p>
      </div>

      {/* Messages */}
      <div className="flex-1 overflow-y-auto space-y-4 mb-4">
        {messages.length === 0 && !isLoading && (
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

        {messages.map((msg, i) => (
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
          disabled={isLoading}
          rows={1}
          className="resize-none min-h-[44px] max-h-[120px]"
        />
        <Button
          onClick={() => sendMessage(input)}
          disabled={isLoading || !input.trim()}
          size="icon"
          className="shrink-0 h-[44px] w-[44px]"
        >
          <Send className="w-4 h-4" />
        </Button>
      </div>
    </div>
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
