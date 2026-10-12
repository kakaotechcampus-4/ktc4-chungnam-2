import { api } from '@/api'

import type { LatLng, PlaceSearchResultDto } from './model'

/** 결과는 화면에 보여 주기만 한다 — 저장·캐시하지 않는다(카카오 약관, #53). */
export function searchPlaces(q: string, near: LatLng | null) {
  const params = new URLSearchParams({ q })
  if (near) {
    params.set('lat', String(near.lat))
    params.set('lng', String(near.lng))
  }
  return api<PlaceSearchResultDto[]>(`/places/search?${params}`)
}
