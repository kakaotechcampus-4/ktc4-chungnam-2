import { api } from '@/api'

import type { InviteDto, InviteSummaryDto, MapCreateRequest, MapDto, MapListDto, MemberDto, TrashedMapListDto } from './model'

/** 내 지도 목록과 상한(#623). 2026-10-19 전에는 Map 배열이었다. */
export const fetchMaps = () => api<MapListDto>('/maps')

export const createMap = (body: MapCreateRequest) =>
  api<MapDto>('/maps', { method: 'POST', body: JSON.stringify(body) })

export const acceptInvite = (token: string) =>
  api<MapDto>(`/invites/${encodeURIComponent(token)}/accept`, { method: 'POST' })

export const fetchMap = (mapId: string) => api<MapDto>(`/maps/${mapId}`)

/** 지도 삭제(방장만, #369). 모든 구성원에게서 사라진다. */
export const deleteMap = (mapId: string) => api<void>(`/maps/${mapId}`, { method: 'DELETE' })

/** 내가 방장인 삭제한 지도(#464). 복구할 수 있는 것만, 최근 삭제순. */
export const fetchTrash = () => api<TrashedMapListDto>('/maps/trash')

/** 삭제한 지도 되살리기(방장만, #464). 이미 되살렸으면 그 지도가 그대로 온다. */
export const restoreMap = (mapId: string) => api<MapDto>(`/maps/${mapId}/restore`, { method: 'POST' })

/** 지도 나가기(구성원 누구나, #369). 내 의견은 지워지고 핀은 남는다. 방장이면 먼저 들어온 사람에게 방장이 넘어간다. */
export const leaveMap = (mapId: string) => api<void>(`/maps/${mapId}/members/me`, { method: 'DELETE' })

export const fetchMembers = (mapId: string) => api<MemberDto[]>(`/maps/${mapId}/members`)

export const createInvite = (mapId: string) => api<InviteDto>(`/maps/${mapId}/invite`, { method: 'POST' })

export const fetchInviteSummary = (token: string) => api<InviteSummaryDto>(`/invites/${encodeURIComponent(token)}`)
