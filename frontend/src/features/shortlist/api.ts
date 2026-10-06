import { api } from '@/api'

import type { RouteDto, ShortlistItemDto } from './model'

export const fetchShortlist = (mapId: string) => api<ShortlistItemDto[]>(`/maps/${mapId}/shortlist`)

export const addToShortlist = (mapId: string, pinId: string) =>
  api<ShortlistItemDto>(`/maps/${mapId}/shortlist`, { method: 'POST', body: JSON.stringify({ pin_id: pinId }) })

export const removeFromShortlist = (itemId: string) => api<void>(`/shortlist/${itemId}`, { method: 'DELETE' })

export const reorderShortlist = (mapId: string, itemIds: string[]) =>
  api<ShortlistItemDto[]>(`/maps/${mapId}/shortlist/order`, { method: 'PUT', body: JSON.stringify({ item_ids: itemIds }) })

/** 「동선 보기」 — 현재 확정 리스트로 다시 계산한다(순수 계산, 모델 미사용). */
export const calculateRoute = (mapId: string) => api<RouteDto[]>(`/maps/${mapId}/route`, { method: 'POST' })

/** 마지막으로 계산된 동선. 한 번도 계산하지 않았으면 빈 배열. */
export const fetchRoute = (mapId: string) => api<RouteDto[]>(`/maps/${mapId}/route`)
