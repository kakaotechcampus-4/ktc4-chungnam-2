import { useQuery } from '@tanstack/react-query'

import { ApiError } from '@/api'

import { externalSearch, fetchPlacePhotos, nearestPlaces, parseLink, searchPlaces } from './api'
import { nearbyKakaoPlaces } from './kakaoNearby'
import type { LatLng, SourcePlaces } from './model'
import type { SearchSource } from './searchStore'

/** 카카오 근처 장소(#1549)를 기다리는 한도(ms). */
const NEARBY_WAIT_MS = 3000

async function fetchSource(source: SearchSource, near: LatLng | null): Promise<SourcePlaces> {
  if (source.kind === 'name') return { places: await searchPlaces(source.query, near) }
  if (source.kind === 'tap') {
    const places = await nearestPlaces(source.at)
    // 카카오를 못 띄워도 자체 DB 결과는 보인다 — 근처 가게 칸만 빈다.
    // 카카오가 늦어도 자체 DB 결과를 붙잡아 두지 않게 NEARBY_WAIT_MS 까지만 기다린다.
    const nearby = await Promise.race([
      nearbyKakaoPlaces(source.at, places),
      new Promise<never>((_, reject) => setTimeout(() => reject(new Error('timeout')), NEARBY_WAIT_MS)),
    ]).catch((err: unknown) => {
      console.warn('[search] 카카오 근처 장소를 찾지 못했어요', err)
      return []
    })
    return { places, nearby }
  }
  const link = await parseLink(source.url)
  return { places: link.matches, link }
}

/**
 * 결과 시트의 장소 — 이름 검색이든 링크(#487)든 누른 자리(#486)든 같은 모양으로 받는다.
 * 같은 검색을 다시 열 때 다시 부르지 않게 잠깐만 기억한다(화면 메모리 안, 서버 저장 아님).
 * 422(링크를 못 읽음)·429(호출 상한)·503(검색 장애)은 다시 물어도 같아서 재시도하지 않는다.
 */
export function useSourcePlacesQuery(source: SearchSource | null, near: LatLng | null) {
  return useQuery({
    queryKey: ['places', source, near?.lat, near?.lng],
    queryFn: () => fetchSource(source!, near),
    enabled: source !== null,
    staleTime: 60_000,
    gcTime: 5 * 60_000,
    retry: (count, err) => !(err instanceof ApiError && [422, 429, 503].includes(err.status)) && count < 1,
  })
}

/**
 * 결과 없음 화면의 카카오맵 링크(#905). 이름 검색이 0곳일 때만 부른다. 실패하면 링크만 숨긴다 — 결과 없음 화면은 그대로다.
 * 링크는 검색어로만 정해져서 같은 검색어는 다시 부르지 않는다.
 */
/** 검색 결과 상세의 블로그 사진(#1681). 핀 사진(`usePinPhotosQuery`)처럼 열 때마다 새로 받는다(저장 금지, #53). */
export function usePlacePhotosQuery(placeId: string) {
  return useQuery({ queryKey: ['places', placeId, 'photos'], queryFn: () => fetchPlacePhotos(placeId), gcTime: 0, retry: false })
}

export function useExternalSearchQuery(query: string) {
  return useQuery({ queryKey: ['places', 'external-search', query], queryFn: () => externalSearch(query), staleTime: Infinity, retry: false })
}

/** docs/errors.md 문구. */
export function searchErrorMessage(err: unknown): string {
  if (err instanceof ApiError && err.code === 'RATE_LIMITED') return '너무 자주 검색했어요. 잠시 뒤 다시 검색해 주세요'
  if (err instanceof ApiError && err.code === 'PLACES_UNAVAILABLE') return '지금은 장소를 검색할 수 없어요. 잠시 뒤 다시 검색해 주세요'
  if (err instanceof ApiError && err.code === 'LINK_NOT_SUPPORTED') return '구글맵, 카카오맵 링크만 붙일 수 있어요'
  if (err instanceof ApiError && err.code === 'LINK_UNRESOLVED') return '링크에서 장소를 찾지 못했어요. 이름으로 검색해 주세요'
  return '검색하지 못했어요'
}
