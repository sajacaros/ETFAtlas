import api from './client'
import type {
  AdminCodeExampleList,
  AdminCodeExampleSaved,
  AdminLayoutExample,
  AdminLayoutExampleList,
  AdminExampleSearch,
  AdminChatLogList,
  AdminChatLogReviewResult,
  AdminChatLogEmbedResult,
  AdminChatLogWithdrawResult,
  AdminETFTag,
  AdminETFTagList,
  AdminDiscordSettings,
  AdminDiscordNotificationLog,
  AdminAISettings,
  AdminAISettingField,
  AdminAITestResult,
  AdminDartSettings,
  AdminDartTestResult,
  AdminInvitation,
  AdminMember,
} from '@/types/api'

// Admin
export const adminApi = {
  listCodeExamples: async (status?: string, skip = 0, limit = 50) => {
    const params: Record<string, string | number> = { skip, limit }
    if (status) params.status = status
    const { data } = await api.get<AdminCodeExampleList>('/admin/code-examples', { params })
    return data
  },
  createCodeExample: async (body: { question: string; code: string; description?: string }) => {
    const { data } = await api.post<AdminCodeExampleSaved>('/admin/code-examples', body)
    return data
  },
  updateCodeExample: async (id: number, body: { question?: string; code?: string; description?: string }) => {
    const { data } = await api.put<AdminCodeExampleSaved>(`/admin/code-examples/${id}`, body)
    return data
  },
  archiveCodeExample: async (id: number) => {
    const { data } = await api.delete<AdminCodeExampleSaved>(`/admin/code-examples/${id}`)
    return data
  },
  searchSimilarExamples: async (q: string, topK = 5, generalize = false) => {
    const { data } = await api.get<AdminExampleSearch>(
      '/admin/code-examples/search', { params: { q, top_k: topK, generalize } }
    )
    return data
  },
  listLayoutExamples: async (status?: string, skip = 0, limit = 50) => {
    const params: Record<string, string | number> = { skip, limit }
    if (status) params.status = status
    const { data } = await api.get<AdminLayoutExampleList>('/admin/layout-examples', { params })
    return data
  },
  createLayoutExample: async (body: { question: string; plan: string; description?: string }) => {
    const { data } = await api.post<AdminLayoutExample>('/admin/layout-examples', body)
    return data
  },
  updateLayoutExample: async (id: number, body: { question?: string; plan?: string; description?: string }) => {
    const { data } = await api.put<AdminLayoutExample>(`/admin/layout-examples/${id}`, body)
    return data
  },
  archiveLayoutExample: async (id: number) => {
    const { data } = await api.delete<AdminLayoutExample>(`/admin/layout-examples/${id}`)
    return data
  },
  searchSimilarLayoutExamples: async (q: string, topK = 5, generalize = false) => {
    const { data } = await api.get<AdminExampleSearch>(
      '/admin/layout-examples/search', { params: { q, top_k: topK, generalize } }
    )
    return data
  },
  listChatLogs: async (status?: string, skip = 0, limit = 50) => {
    const params: Record<string, string | number> = { skip, limit }
    if (status) params.status = status
    const { data } = await api.get<AdminChatLogList>('/admin/chat-logs', { params })
    return data
  },
  reviewChatLog: async (id: number, action: string) => {
    const { data } = await api.post<AdminChatLogReviewResult>(`/admin/chat-logs/${id}/review`, { action })
    return data
  },
  embedChatLog: async (id: number, body: { question?: string; code?: string; description?: string }) => {
    const { data } = await api.post<AdminChatLogEmbedResult>(`/admin/chat-logs/${id}/embed`, body)
    return data
  },
  withdrawChatLog: async (id: number) => {
    const { data } = await api.post<AdminChatLogWithdrawResult>(`/admin/chat-logs/${id}/withdraw`)
    return data
  },
  listETFTags: async () => {
    const { data } = await api.get<AdminETFTagList>('/admin/etf-tags')
    return data
  },
  // tags=null: 수동 지정 해제 (다음 태깅 때 자동으로 다시 계산)
  updateETFTags: async (code: string, tags: string[] | null) => {
    const { data } = await api.put<AdminETFTag>(`/admin/etf-tags/${code}`, { tags })
    return data
  },
  getDiscordSettings: async () => {
    const { data } = await api.get<AdminDiscordSettings>('/admin/settings/discord')
    return data
  },
  // webhook_url: undefined면 기존 주소 유지, ''면 삭제
  updateDiscordSettings: async (body: { enabled: boolean; threshold: number; added_threshold: number; rise_threshold: number; webhook_url?: string }) => {
    const { data } = await api.put<AdminDiscordSettings>('/admin/settings/discord', body)
    return data
  },
  getDiscordNotificationLogs: async (limit = 30, offset = 0) => {
    const { data } = await api.get<{ total: number; logs: AdminDiscordNotificationLog[] }>(
      '/admin/settings/discord/logs', { params: { limit, offset } }
    )
    return data
  },
  testDiscordWebhook: async () => {
    const { data } = await api.post<{ ok: boolean }>('/admin/settings/discord/test')
    return data
  },
  getAISettings: async () => {
    const { data } = await api.get<AdminAISettings>('/admin/settings/ai')
    return data
  },
  // 항목이 없으면 기존 값 유지, ''면 지우고 서버 환경변수로 되돌림
  updateAISettings: async (body: Partial<Record<AdminAISettingField, string>>) => {
    const { data } = await api.put<AdminAISettings>('/admin/settings/ai', body)
    return data
  },
  testAISettings: async () => {
    const { data } = await api.post<AdminAITestResult>('/admin/settings/ai/test')
    return data
  },
  getDartSettings: async () => {
    const { data } = await api.get<AdminDartSettings>('/admin/settings/dart')
    return data
  },
  // api_key: ''면 삭제
  updateDartSettings: async (body: { api_key: string }) => {
    const { data } = await api.put<AdminDartSettings>('/admin/settings/dart', body)
    return data
  },
  testDartSettings: async () => {
    const { data } = await api.post<AdminDartTestResult>('/admin/settings/dart/test')
    return data
  },
  listInvitations: async () => {
    const { data } = await api.get<AdminInvitation[]>('/admin/invitations')
    return data
  },
  createInvitation: async () => {
    const { data } = await api.post<AdminInvitation>('/admin/invitations')
    return data
  },
  deleteInvitation: async (id: number) => {
    await api.delete(`/admin/invitations/${id}`)
  },
  listMembers: async () => {
    const { data } = await api.get<AdminMember[]>('/admin/members')
    return data
  },
  updateMemberRole: async (userId: number, isAdmin: boolean) => {
    await api.put(`/admin/members/${userId}/role`, { is_admin: isAdmin })
  },
  logoutMember: async (userId: number) => {
    const { data } = await api.post<{ revoked: number }>(`/admin/members/${userId}/logout`)
    return data
  },
  deleteMember: async (userId: number) => {
    await api.delete(`/admin/members/${userId}`)
  },
  createPasswordReset: async (userId: number) => {
    const { data } = await api.post<{ token: string; expires_at: string }>(`/admin/members/${userId}/password-reset`)
    return data
  },
}
