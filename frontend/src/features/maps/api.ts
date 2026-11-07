import { api } from '@/api'

import type { InviteDto, InviteSummaryDto, MapCreateRequest, MapDto, MapListDto, MapUpdateRequest, MemberDto, OwnerTransferRequest, TrashedMapListDto } from './model'

/** 내 지도 목록과 상한(#623). 2026-10-19 전에는 Map 배열이었다. */
export const fetchMaps = () => api<MapListDto>('/maps')

export const createMap = (body: MapCreateRequest) =>
  api<MapDto>('/maps', { method: 'POST', body: JSON.stringify(body) })

export const acceptInvite = (token: string) =>
  api<MapDto>(`/invites/${encodeURIComponent(token)}/accept`, { method: 'POST' })

export const fetchMap = (mapId: string) => api<MapDto>(`/maps/${mapId}`)

/** 지도 제목·날짜·지역 수정(방장만, #465). 바뀐 칸만 보낸다. */
export const updateMap = (mapId: string, body: MapUpdateRequest) =>
  api<MapDto>(`/maps/${mapId}`, { method: 'PATCH', body: JSON.stringify(body) })

/** 지도 삭제(방장만, #369). 모든 구성원에게서 사라진다. */
export const deleteMap = (mapId: string) => api<void>(`/maps/${mapId}`, { method: 'DELETE' })

/** 지도 복사(방장만, #1446). 날짜·지역·이미지·색·핀을 가져가고 의견·구성원·확정 리스트는 두고 온다. 새 지도가 온다. */
export const copyMap = (mapId: string) => api<MapDto>(`/maps/${mapId}/copy`, { method: 'POST' })

/** 대표 이미지 올리기(방장만, #1445). 본문은 이미지 그대로다. 응답은 cover_url 이 바뀐 지도다. */
export const putCover = (mapId: string, image: Blob) =>
  api<MapDto>(`/maps/${mapId}/cover`, { method: 'PUT', body: image, headers: { 'Content-Type': image.type } })

/** 대표 이미지 지우기 — 지역 기본 그림으로 돌아간다(방장만, #1445). */
export const deleteCover = (mapId: string) => api<MapDto>(`/maps/${mapId}/cover`, { method: 'DELETE' })

/** 내가 방장인 삭제한 지도(#464). 복구할 수 있는 것만, 최근 삭제순. */
export const fetchTrash = () => api<TrashedMapListDto>('/maps/trash')

/** 삭제한 지도 복구(방장만, #464). 이미 복구했으면 그 지도가 그대로 온다. */
export const restoreMap = (mapId: string) => api<MapDto>(`/maps/${mapId}/restore`, { method: 'POST' })

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
