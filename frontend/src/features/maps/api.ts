import { api } from '@/api'

import type { InviteDto, InviteSummaryDto, MapCreateRequest, MapDto, MapListDto, MemberDto, OwnerTransferRequest } from './model'

/** 내 지도 목록과 상한(#623). 2026-10-19 전에는 Map 배열이었다. */
export const fetchMaps = () => api<MapListDto>('/maps')

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

/** 지도의 켜진 초대 링크(방장만, #467). 끈 링크와 만료된 링크는 빠진다. */
export const fetchInvites = (mapId: string) => api<InviteDto[]>(`/maps/${mapId}/invites`)

/** 초대 링크 끄기(방장만, #467). 이미 참여한 사람은 그대로 남는다. */
export const revokeInvite = (token: string) => api<void>(`/invites/${encodeURIComponent(token)}`, { method: 'DELETE' })

/** 방장 넘기기(방장만, #468). 나는 구성원으로 남는다. */
export const transferOwner = (mapId: string, body: OwnerTransferRequest) =>
  api<MapDto>(`/maps/${mapId}/owner`, { method: 'POST', body: JSON.stringify(body) })
