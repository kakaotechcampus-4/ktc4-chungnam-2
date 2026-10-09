import { api } from '@/api'

import type { InviteDto, InviteSummaryDto, MapCreateRequest, MapDto, MemberDto } from './model'

export const fetchMaps = () => api<MapDto[]>('/maps')

export const createMap = (body: MapCreateRequest) =>
  api<MapDto>('/maps', { method: 'POST', body: JSON.stringify(body) })

export const acceptInvite = (token: string) =>
  api<MapDto>(`/invites/${encodeURIComponent(token)}/accept`, { method: 'POST' })

export const fetchMap = (mapId: string) => api<MapDto>(`/maps/${mapId}`)

/** 지도 삭제(방장만, #369). 모든 구성원에게서 사라진다. */
export const deleteMap = (mapId: string) => api<void>(`/maps/${mapId}`, { method: 'DELETE' })

/** 지도 나가기(구성원 누구나, #369). 내 의견은 지워지고 핀은 남는다. 방장이면 먼저 들어온 사람에게 방장이 넘어간다. */
export const leaveMap = (mapId: string) => api<void>(`/maps/${mapId}/members/me`, { method: 'DELETE' })

export const fetchMembers = (mapId: string) => api<MemberDto[]>(`/maps/${mapId}/members`)

export const createInvite = (mapId: string) => api<InviteDto>(`/maps/${mapId}/invite`, { method: 'POST' })

export const fetchInviteSummary = (token: string) => api<InviteSummaryDto>(`/invites/${encodeURIComponent(token)}`)
