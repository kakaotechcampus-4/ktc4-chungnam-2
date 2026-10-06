import { api } from '@/api'

import type { InviteDto, InviteSummaryDto, MapCreateRequest, MapDto, MemberDto } from './model'

export const fetchMaps = () => api<MapDto[]>('/maps')

export const createMap = (body: MapCreateRequest) =>
  api<MapDto>('/maps', { method: 'POST', body: JSON.stringify(body) })

export const acceptInvite = (token: string) =>
  api<MapDto>(`/invites/${encodeURIComponent(token)}/accept`, { method: 'POST' })

export const fetchMap = (mapId: string) => api<MapDto>(`/maps/${mapId}`)

export const fetchMembers = (mapId: string) => api<MemberDto[]>(`/maps/${mapId}/members`)

export const createInvite = (mapId: string) => api<InviteDto>(`/maps/${mapId}/invite`, { method: 'POST' })

export const fetchInviteSummary = (token: string) => api<InviteSummaryDto>(`/invites/${encodeURIComponent(token)}`)
