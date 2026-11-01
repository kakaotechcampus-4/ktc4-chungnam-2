import { api } from '@/api'

import type { AgentActionDto, AgentSettingsDto, AgentStateDto, RunAdviceDto } from './model'

export const fetchAgent = (mapId: string) => api<AgentStateDto>(`/maps/${mapId}/agent`)

export const putAgentSettings = (mapId: string, enabled: boolean) =>
  api<AgentSettingsDto>(`/maps/${mapId}/agent/settings`, { method: 'PUT', body: JSON.stringify({ enabled }) })

/** 열람 기록. 이미 처리된 제안도 204다. */
export const viewSuggestion = (id: string) => api<void>(`/agent/suggestions/${id}/view`, { method: 'POST' })

/** 서버는 동작을 대신 실행하지 않는다 — 돌려준 action 을 화면이 손으로 할 때와 같은 API로 실행한다(agent-v2 16.3). */
export const acceptSuggestion = (id: string, actionIndex: number) =>
  api<{ action: AgentActionDto }>(`/agent/suggestions/${id}/accept`, { method: 'POST', body: JSON.stringify({ action_index: actionIndex }) })

export const dismissSuggestion = (id: string) => api<void>(`/agent/suggestions/${id}/dismiss`, { method: 'POST' })

/** 대상이 아니거나 낼 조언이 없으면 204 라서 null — react-query 는 undefined 를 data 로 받지 않는다. */
export const fetchRunAdvice = async (runId: string) => (await api<RunAdviceDto | undefined>(`/runs/${runId}/advice`)) ?? null
