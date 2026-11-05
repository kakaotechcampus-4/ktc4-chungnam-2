import { api } from '@/api'

import type { PinCategory, PinCreateRequest, PinDto, PinResolveRequest, PinTrash, PinUpdateRequest, ReactionDto, ReactionRequest, ReasonChip, FilterCounts } from './model'

export const fetchPins = (mapId: string) => api<PinDto[]>(`/maps/${mapId}/pins`)

export const fetchReactions = (pinId: string) => api<ReactionDto[]>(`/pins/${pinId}/reactions`)

export const putReaction = (pinId: string, body: ReactionRequest) =>
  api<ReactionDto>(`/pins/${pinId}/reaction`, { method: 'PUT', body: JSON.stringify(body) })

export const deleteReaction = (pinId: string) => api<void>(`/pins/${pinId}/reaction`, { method: 'DELETE' })

export const createPin = (mapId: string, body: PinCreateRequest) =>
  api<PinDto>(`/maps/${mapId}/pins`, { method: 'POST', body: JSON.stringify(body) })

/** 핀 삭제 — 찍은 사람과 방장만(`permissions.can_delete`). 30일 동안 휴지통에 남는다(#864). */
export const deletePin = (pinId: string) => api<void>(`/pins/${pinId}`, { method: 'DELETE' })

/** 핀 휴지통 — 내가 되살릴 수 있는 지운 핀만 온다(일반 구성원은 내가 찍은 것, 방장은 전부). */
export const fetchPinTrash = (mapId: string) => api<PinTrash>(`/maps/${mapId}/trash`)

/** 지운 핀 되살리기. 휴지통에 있는 동안 같은 장소로 새 핀이 생겼으면 409 PIN_DUPLICATE. */
export const restorePin = (pinId: string) => api<PinDto>(`/pins/${pinId}/restore`, { method: 'POST' })

/** 핀 메모·분류 수정(찍은 사람만, #466). 분류는 반응이 없는 실시간 핀만 바꿀 수 있다. */
export const updatePin = (pinId: string, body: PinUpdateRequest) =>
  api<PinDto>(`/pins/${pinId}`, { method: 'PATCH', body: JSON.stringify(body) })

/** 실시간 핀 승격(#501). 짝이 없으면 핀이 그대로(source=live) 온다. */
export const resolvePin = (pinId: string, body: PinResolveRequest) =>
  api<PinDto>(`/pins/${pinId}/resolve`, { method: 'POST', body: JSON.stringify(body) })

export const fetchReasonChips = (category: PinCategory) =>
  api<ReasonChip[]>(`/categories/${encodeURIComponent(category)}/reason-chips`)

export const fetchCounts = (mapId: string) => api<FilterCounts>(`/maps/${mapId}/counts`)
