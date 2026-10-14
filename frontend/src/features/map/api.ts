import { api } from '@/api'

import type { PinCategory, PinCreateRequest, PinDto, ReactionDto, ReactionRequest, ReasonChip, FilterCounts } from './model'

export const fetchPins = (mapId: string) => api<PinDto[]>(`/maps/${mapId}/pins`)

export const fetchReactions = (pinId: string) => api<ReactionDto[]>(`/pins/${pinId}/reactions`)

export const putReaction = (pinId: string, body: ReactionRequest) =>
  api<ReactionDto>(`/pins/${pinId}/reaction`, { method: 'PUT', body: JSON.stringify(body) })

export const deleteReaction = (pinId: string) => api<void>(`/pins/${pinId}/reaction`, { method: 'DELETE' })

export const createPin = (mapId: string, body: PinCreateRequest) =>
  api<PinDto>(`/maps/${mapId}/pins`, { method: 'POST', body: JSON.stringify(body) })

/** 핀 삭제 — 구성원 누구나 남의 핀도 지울 수 있다(기획안 #25). */
export const deletePin = (pinId: string) => api<void>(`/pins/${pinId}`, { method: 'DELETE' })

export const fetchReasonChips = (category: PinCategory) =>
  api<ReasonChip[]>(`/categories/${encodeURIComponent(category)}/reason-chips`)

export const fetchCounts = (mapId: string) => api<FilterCounts>(`/maps/${mapId}/counts`)
