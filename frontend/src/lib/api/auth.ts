import api from './client'
import type { User, RegisterPayload } from '@/types/api'

export const authApi = {
  getSetupStatus: async () => {
    const { data } = await api.get<{ setup_required: boolean }>('/auth/setup-status')
    return data
  },
  setup: async (payload: RegisterPayload) => {
    const { data } = await api.post<User>('/auth/setup', payload)
    return data
  },
  getInvitationStatus: async (inviteToken: string) => {
    const { data } = await api.get<{ valid: boolean }>(`/auth/invitations/${encodeURIComponent(inviteToken)}`)
    return data
  },
  register: async (payload: RegisterPayload, inviteToken: string) => {
    const { data } = await api.post<User>('/auth/register', {
      ...payload,
      invite_token: inviteToken,
    })
    return data
  },
  getPasswordResetStatus: async (resetToken: string) => {
    const { data } = await api.get<{ valid: boolean; username: string | null }>(
      `/auth/password-resets/${encodeURIComponent(resetToken)}`,
    )
    return data
  },
  resetPassword: async (resetToken: string, password: string) => {
    await api.post('/auth/password-reset', { token: resetToken, password })
  },
  login: async (username: string, password: string) => {
    const { data } = await api.post<User>('/auth/login', { username, password })
    return data
  },
  logout: async () => {
    await api.post('/auth/logout')
  },
  getMe: async () => {
    const { data } = await api.get<User>('/auth/me')
    return data
  },
  updateProfile: async (name: string) => {
    const { data } = await api.patch<User>('/auth/me', { name })
    return data
  },
  changePassword: async (currentPassword: string, password: string) => {
    await api.post('/auth/password', { current_password: currentPassword, password })
  },
}
