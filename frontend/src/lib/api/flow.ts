import api, { streamSSE } from './client'
import type {
  FlowCatalog,
  FlowGraphData,
  FlowNodeResult,
  FlowPerformance,
  FlowRunHandlers,
  SavedFlow,
} from '@/types/api'

// 스크리너 실행 스트림이 보내는 이벤트
export type FlowRunEvent =
  | { type: 'node_start'; data: { id: string } }
  | { type: 'node_progress'; data: { id: string; message: string } }
  | { type: 'node_done'; data: FlowNodeResult }
  | { type: 'node_error'; data: { id: string; message: string } }
  | { type: 'node_skipped'; data: { id: string; message: string } }
  | { type: 'run_done'; data: { recorded?: boolean } }
  | { type: 'error'; data: { message: string } }

function dispatchFlowEvent(event: FlowRunEvent, handlers: FlowRunHandlers) {
  switch (event.type) {
    case 'node_start': handlers.onNodeStart?.(event.data.id); break
    case 'node_progress': handlers.onNodeProgress?.(event.data.id, event.data.message); break
    case 'node_done': handlers.onNodeDone?.(event.data); break
    case 'node_error': handlers.onNodeError?.(event.data.id, event.data.message, false); break
    case 'node_skipped': handlers.onNodeError?.(event.data.id, event.data.message, true); break
    case 'run_done': if (event.data.recorded) handlers.onRecorded?.(); break
    case 'error': handlers.onError(event.data.message); break
  }
}

// 종목 스크리너 (코드에서는 flow)
export const flowApi = {
  getCatalog: async () => {
    const { data } = await api.get<FlowCatalog>('/flows/catalog')
    return data
  },
  list: async () => {
    const { data } = await api.get<SavedFlow[]>('/flows')
    return data
  },
  get: async (id: number) => {
    const { data } = await api.get<SavedFlow>(`/flows/${id}`)
    return data
  },
  create: async (name: string, graph: FlowGraphData) => {
    const { data } = await api.post<SavedFlow>('/flows', { name, graph })
    return data
  },
  update: async (id: number, name: string, graph: FlowGraphData) => {
    const { data } = await api.put<SavedFlow>(`/flows/${id}`, { name, graph })
    return data
  },
  remove: async (id: number) => {
    await api.delete(`/flows/${id}`)
  },
  setSchedule: async (id: number, scheduleEnabled: boolean, notify: boolean) => {
    const { data } = await api.put<SavedFlow>(`/flows/${id}/schedule`, { schedule_enabled: scheduleEnabled, notify })
    return data
  },
  getPerformance: async (id: number) => {
    const { data } = await api.get<FlowPerformance>(`/flows/${id}/performance`)
    return data
  },
  // 저장하지 않은 그래프도 그대로 실행한다. 중지하려면 돌려받은 AbortController를 abort한다.
  // flowId를 주면 그래프가 저장본과 같을 때 고른 종목을 기록한다
  run: (graph: FlowGraphData, handlers: FlowRunHandlers, flowId?: number | null) =>
    streamSSE<FlowRunEvent>('/flows/run', { graph, flow_id: flowId ?? null }, {
      onEvent: (event) => dispatchFlowEvent(event, handlers),
      onError: handlers.onError,
      onDone: handlers.onDone,
    }),
}
