import { useQuery } from '@tanstack/react-query'

import { ApiError } from '@/api'

import { parseLink, searchPlaces } from './api'
import type { LatLng, SourcePlaces } from './model'
import type { SearchSource } from './searchStore'

async function fetchSource(source: SearchSource, near: LatLng | null): Promise<SourcePlaces> {
  if (source.kind === 'name') return { places: await searchPlaces(source.query, near) }
  const link = await parseLink(source.url)
  return { places: link.matches, link }
}

/**
 * 결과 시트의 장소 — 이름 검색이든 링크(#487)든 같은 모양으로 받는다.
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

/** docs/errors.md 문구. */
export function searchErrorMessage(err: unknown): string {
  if (err instanceof ApiError && err.code === 'RATE_LIMITED') return '너무 빨리 검색하고 있어요. 잠시 뒤 다시 시도해 주세요'
  if (err instanceof ApiError && err.code === 'PLACES_UNAVAILABLE') return '지금은 장소를 검색할 수 없어요. 잠시 뒤 다시 시도해 주세요'
  if (err instanceof ApiError && err.code === 'LINK_NOT_SUPPORTED') return '구글맵·카카오맵 링크만 붙일 수 있어요'
  if (err instanceof ApiError && err.code === 'LINK_UNRESOLVED') return '링크에서 장소를 찾지 못했어요. 검색으로 남겨 주세요'
  return '검색하지 못했어요'
}
