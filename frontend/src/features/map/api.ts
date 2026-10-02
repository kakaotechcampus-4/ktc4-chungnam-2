import { api } from '@/api'

import type { PinDto, ReactionDto, ReactionRequest } from './model'

export const fetchPins = (mapId: string) => api<PinDto[]>(`/maps/${mapId}/pins`)

export const fetchReactions = (pinId: string) => api<ReactionDto[]>(`/pins/${pinId}/reactions`)

export const putReaction = (pinId: string, body: ReactionRequest) =>
  api<ReactionDto>(`/pins/${pinId}/reaction`, { method: 'PUT', body: JSON.stringify(body) })

export const deleteReaction = (pinId: string) => api<void>(`/pins/${pinId}/reaction`, { method: 'DELETE' })
