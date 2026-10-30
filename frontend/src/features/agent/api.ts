import { api } from '@/api'

import type { AgentActionDto, AgentSettingsDto, AgentStateDto } from './model'

export const fetchAgent = (mapId: string) => api<AgentStateDto>(`/maps/${mapId}/agent`)

export const putAgentSettings = (mapId: string, enabled: boolean) =>
  api<AgentSettingsDto>(`/maps/${mapId}/agent/settings`, { method: 'PUT', body: JSON.stringify({ enabled }) })

/** 열람 기록. 이미 처리된 제안도 204다. */
export const viewSuggestion = (id: string) => api<void>(`/agent/suggestions/${id}/view`, { method: 'POST' })

/** 서버는 동작을 대신 실행하지 않는다 — 돌려준 action 을 화면이 손으로 할 때와 같은 API로 실행한다(agent-v2 16.3). */
export const acceptSuggestion = (id: string, actionIndex: number) =>
  api<{ action: AgentActionDto }>(`/agent/suggestions/${id}/accept`, { method: 'POST', body: JSON.stringify({ action_index: actionIndex }) })

export const dismissSuggestion = (id: string) => api<void>(`/agent/suggestions/${id}/dismiss`, { method: 'POST' })
