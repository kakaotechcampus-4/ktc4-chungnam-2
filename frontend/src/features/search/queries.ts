import { useQuery } from '@tanstack/react-query'

import { ApiError } from '@/api'

import { searchPlaces } from './api'
import type { LatLng } from './model'

/**
 * 장소 검색. 같은 검색어를 다시 열 때 다시 부르지 않게 잠깐만 기억한다(화면 메모리 안, 서버 저장 아님).
 * 호출 상한(429)·검색 장애(503)는 다시 물어도 같아서 재시도하지 않는다.
 */
export function usePlaceSearchQuery(query: string | null, near: LatLng | null) {
  return useQuery({
    queryKey: ['places', 'search', query, near?.lat, near?.lng],
    queryFn: () => searchPlaces(query!, near),
    enabled: Boolean(query),
    staleTime: 60_000,
    gcTime: 5 * 60_000,
    retry: (count, err) => !(err instanceof ApiError && [422, 429, 503].includes(err.status)) && count < 1,
  })
}

/** docs/errors.md 문구. */
export function searchErrorMessage(err: unknown): string {
  if (err instanceof ApiError && err.code === 'RATE_LIMITED') return '너무 빨리 검색하고 있어요. 잠시 뒤 다시 시도해 주세요'
  if (err instanceof ApiError && err.code === 'PLACES_UNAVAILABLE') return '지금은 장소를 검색할 수 없어요. 잠시 뒤 다시 시도해 주세요'
  return '검색하지 못했어요'
}
