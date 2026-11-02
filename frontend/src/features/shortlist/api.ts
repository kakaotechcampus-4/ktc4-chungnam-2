import { api, apiFile } from '@/api'

import type { ExportFormat, ShortlistItemDto } from './model'

export const fetchShortlist = (mapId: string) => api<ShortlistItemDto[]>(`/maps/${mapId}/shortlist`)

export const addToShortlist = (mapId: string, pinId: string) =>
  api<ShortlistItemDto>(`/maps/${mapId}/shortlist`, { method: 'POST', body: JSON.stringify({ pin_id: pinId }) })

export const removeFromShortlist = (itemId: string) => api<void>(`/shortlist/${itemId}`, { method: 'DELETE' })

/** 확정 리스트 내보내기(#471) — 확정 순서대로 한 줄씩. 파일로 온다. */
export const exportShortlist = (mapId: string, format: ExportFormat) => apiFile(`/maps/${mapId}/shortlist/export?format=${format}`)
