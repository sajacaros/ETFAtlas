import api, { streamSSE } from './client'
import type {
  ChatSessionPage,
  ChatSessionDetail,
  ChatStep,
  ChatSlotResponse,
  LayoutNode,
  SlotStatus,
  MatchedCodeExample,
  ChatLogResult,
} from '@/types/api'

// Chat
// 준비 단계: 질문 재작성(맥락이 있을 때만) → 화면 설계 → (agent 영역) 참고 예시 검색 → 에이전트 실행
// replanning: 실행 결과를 보고 비어 있는 영역을 다시 설계하는 중, filling: 다시 설계한 영역을 채우는 중
export type ChatStage = 'refining' | 'planning' | 'searching_examples' | 'thinking' | 'replanning' | 'filling'

// 채팅 스트림이 보내는 이벤트
export type ChatStreamEvent =
  | { type: 'session'; data: { session_id: number; title: string } }
  | { type: 'refined_question'; data: { question: string } }
  | { type: 'status'; data: { stage: ChatStage } }
  | { type: 'step_start'; data: Pick<ChatStep, 'step_number' | 'code' | 'tool_calls'> }
  | { type: 'step'; data: ChatStep }
  | { type: 'answer'; data: { answer: string; result: ChatLogResult } }
  | { type: 'error'; data: { message: string } }
  | { type: 'matched_examples'; data: { examples: MatchedCodeExample[] } }
  | { type: 'layout'; data: { chat_log_id: number; layout: LayoutNode } }
  | { type: 'slot'; data: { id: string; status: SlotStatus; message?: string } }
  | { type: 'slot_delta'; data: { id: string; text: string } }

export interface ChatStreamHandlers {
  onSession?: (session: { session_id: number; title: string }) => void
  onRefinedQuestion?: (question: string) => void
  onStatus?: (stage: ChatStage) => void
  onStepStart?: (step: Pick<ChatStep, 'step_number' | 'code' | 'tool_calls'>) => void
  onStep: (step: ChatStep) => void
  onAnswer: (answer: string, result: ChatLogResult) => void
  onError: (error: string) => void
  onMatchedExamples?: (examples: MatchedCodeExample[]) => void
  onLayout?: (data: { chat_log_id: number; layout: LayoutNode }) => void
  onSlot?: (data: { id: string; status: SlotStatus; message?: string }) => void
  onSlotDelta?: (data: { id: string; text: string }) => void
  onDone?: () => void
}

function dispatchChatEvent(event: ChatStreamEvent, handlers: ChatStreamHandlers) {
  switch (event.type) {
    case 'session': handlers.onSession?.(event.data); break
    case 'refined_question': handlers.onRefinedQuestion?.(event.data.question); break
    case 'status': handlers.onStatus?.(event.data.stage); break
    case 'step_start': handlers.onStepStart?.(event.data); break
    case 'step': handlers.onStep(event.data); break
    case 'answer': handlers.onAnswer(event.data.answer, event.data.result); break
    case 'error': handlers.onError(event.data.message); break
    case 'matched_examples': handlers.onMatchedExamples?.(event.data.examples); break
    case 'layout': handlers.onLayout?.(event.data); break
    case 'slot': handlers.onSlot?.(event.data); break
    case 'slot_delta': handlers.onSlotDelta?.(event.data); break
  }
}

export const chatApi = {
  // 최근 활동 순, 커서 페이징 — cursor는 이전 응답의 next_cursor
  listSessions: async (cursor?: string | null) => {
    const { data } = await api.get<ChatSessionPage>('/chat/sessions', { params: cursor ? { cursor } : {} })
    return data
  },
  getSession: async (id: number) => {
    const { data } = await api.get<ChatSessionDetail>(`/chat/sessions/${id}`)
    return data
  },
  renameSession: async (id: number, title: string) => {
    const { data } = await api.patch<{ id: number; title: string }>(`/chat/sessions/${id}`, { title })
    return data
  },
  deleteSession: async (id: number) => {
    await api.delete(`/chat/sessions/${id}`)
  },
  // 답변 화면 한 영역의 내용 (완료 알림을 받았거나 지난 대화를 열 때)
  getSlot: async (chatLogId: number, slotId: string) => {
    const { data } = await api.get<ChatSlotResponse>(`/chat/logs/${chatLogId}/slots/${slotId}`)
    return data
  },
  // 실행 중인 도구는 결과까지 기다리고 다음 단계부터 멈춘다 (결과는 열려 있는 스트림으로 온다)
  stopMessage: async (sessionId: number) => {
    await api.post(`/chat/sessions/${sessionId}/stop`)
  },
  // sessionId가 null이면 서버가 새 세션을 만들고 onSession으로 알려준다
  // refine=false면 대화 맥락으로 질문을 재작성하지 않고 원문 그대로 묻는다
  streamMessage: (message: string, sessionId: number | null, handlers: ChatStreamHandlers, refine = true) =>
    streamSSE<ChatStreamEvent>('/chat/message/stream', { message, session_id: sessionId, refine }, {
      onEvent: (event) => dispatchChatEvent(event, handlers),
      onError: handlers.onError,
      onDone: handlers.onDone,
    }),
}

// Notification
export const notificationApi = {
  getStatus: async () => {
    const { data } = await api.get<{ has_new: boolean; latest_collected_at: string | null }>(
      '/notifications/status'
    )
    return data
  },
  check: async () => {
    const { data } = await api.post<{ checked_at: string }>('/notifications/check')
    return data
  },
}
