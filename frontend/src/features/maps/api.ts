import { api } from '@/api'

import type { MapCreateRequest, MapDto } from './model'

export const fetchMaps = () => api<MapDto[]>('/maps')

export const createMap = (body: MapCreateRequest) =>
  api<MapDto>('/maps', { method: 'POST', body: JSON.stringify(body) })

export const acceptInvite = (token: string) =>
  api<MapDto>(`/invites/${encodeURIComponent(token)}/accept`, { method: 'POST' })
