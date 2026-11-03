import { api, apiFile } from '@/api'

import type { ExportFormat, ScheduleDto, ScheduleUpdateDto, ShortlistItemDto } from './model'

export const fetchShortlist = (mapId: string) => api<ShortlistItemDto[]>(`/maps/${mapId}/shortlist`)

export const addToShortlist = (mapId: string, pinId: string) =>
  api<ShortlistItemDto>(`/maps/${mapId}/shortlist`, { method: 'POST', body: JSON.stringify({ pin_id: pinId }) })

export const removeFromShortlist = (itemId: string) => api<void>(`/shortlist/${itemId}`, { method: 'DELETE' })

/** 확정 리스트 내보내기(#471) — 확정 순서대로 한 줄씩. 파일로 온다. */
export const exportShortlist = (mapId: string, format: ExportFormat) => apiFile(`/maps/${mapId}/shortlist/export?format=${format}`)

/** 날짜별 일정(#1172) — 여행 기간, 변경 감지 version, 확정 항목(날짜 순, 미배정은 마지막). 구성원 누구나 읽는다. */
export const fetchSchedule = (mapId: string) => api<ScheduleDto>(`/maps/${mapId}/shortlist/schedule`)

/** 날짜 배정과 날짜별 순서 저장 — 모든 확정 항목을 한 번씩 보내고, 조회한 version이 지금과 다르면 409 SHORTLIST_STALE. */
export const putSchedule = (mapId: string, body: ScheduleUpdateDto) =>
  api<ScheduleDto>(`/maps/${mapId}/shortlist/schedule`, { method: 'PUT', body: JSON.stringify(body) })
