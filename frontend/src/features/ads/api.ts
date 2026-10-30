import type { components } from '@pingo/contracts/src/types/api'

import { api } from '@/api'
import type { RecommendCategory } from '@/features/recommend/model'

export type AdDto = components['schemas']['Ad']
type AdListDto = components['schemas']['AdList']

export function fetchAds(mapId: string, category: RecommendCategory | null, center: { lat: number; lng: number }) {
  const q = new URLSearchParams({ lat: String(center.lat), lng: String(center.lng), ...(category ? { category } : {}) })
  return api<AdListDto>(`/maps/${mapId}/ads?${q}`)
}

export const recordAdClick = (adId: string, mapId: string) =>
  api<void>(`/ads/${adId}/clicks`, { method: 'POST', body: JSON.stringify({ map_id: mapId }) })
