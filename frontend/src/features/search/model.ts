import type { components } from '@pingo/contracts/src/types/api'

import { ApiError } from '@/api'
import { FILTER_CATEGORIES, isPlaced, type Pin } from '@/features/map/model'

export type PlaceSearchResultDto = components['schemas']['PlaceSearchResult']
export type LinkParseResultDto = components['schemas']['LinkParseResult']

/**
 * 검색창에 붙여넣은 값이 링크인가(#487). 링크면 이름 검색 대신 서버가 링크를 해석한다.
 * 구글맵·카카오맵인지는 서버가 정한다(LINK_NOT_SUPPORTED) — 화면은 http(s)인지만 본다.
 */
export const isLinkInput = (text: string) => /^https?:\/\/\S+$/i.test(text)

/** 출처마다 받은 장소. 링크면 링크에서 읽은 단서(`link`)도 같이 둔다. */
export type SourcePlaces = { places: PlaceSearchResultDto[]; link?: LinkParseResultDto }
export type LatLng = { lat: number; lng: number }

/** 두 좌표 사이 직선거리(m). 하버사인 — 검색 결과의 "350m" 표시용이라 이 정도면 충분하다. */
export function distanceM(a: LatLng, b: LatLng): number {
  const R = 6371000
  const rad = (d: number) => (d * Math.PI) / 180
  const dLat = rad(b.lat - a.lat)
  const dLng = rad(b.lng - a.lng)
  const h = Math.sin(dLat / 2) ** 2 + Math.cos(rad(a.lat)) * Math.cos(rad(b.lat)) * Math.sin(dLng / 2) ** 2
  return 2 * R * Math.asin(Math.sqrt(h))
}

export function formatDistance(m: number): string {
  return m < 1000 ? `${Math.round(m / 10) * 10}m` : `${(m / 1000).toFixed(1)}km`
}

export type SearchResultView = {
  id: string
  name: string
  meta: string
  address?: string
  url?: string
  /** 자체 DB에 짝이 없어 장소 정보가 있는 핀은 될 수 없다(#191). */
  unsupported: boolean
  /** 그래도 실시간 핀으로 남길 수 있다(#382) — 자체 DB에 없는 음식점·카페·관광지. 숙소·기타나 분류를 모르는 곳은 안 된다. */
  canLeaveLive: boolean
  /** 이미 지도에 있는 장소로 보인다. 서버도 PIN_DUPLICATE 로 막는다. */
  alreadyPinned: boolean
  /** 검색한 지도 가운데에서 멀다 — 이름이 같은 다른 지역 가게일 수 있어 알려 준다. */
  far: boolean
  dto: PlaceSearchResultDto
}

/** 이보다 멀면 「지금 보는 곳에서 멀어요」를 붙인다. 시·도 하나를 넘는 정도. */
const FAR_M = 30_000

/** 같은 이름이 이만큼 안에 있으면 이미 찍힌 장소로 본다. */
const SAME_PLACE_M = 50

export function toSearchResult(r: PlaceSearchResultDto, center: LatLng | null, pins: Pin[]): SearchResultView {
  // 실시간 핀은 카카오 장소 ID로 정확히 맞춘다. 자체 DB 핀은 응답에 장소 id가 없어 이름 + 50m 로 짐작한다(서버가 PIN_DUPLICATE 로 막는다).
  const alreadyPinned = pins.some(
    (p) => p.kakao_place_id === r.place_id || (isPlaced(p) && p.place_name === r.place_name && distanceM(p, r) < SAME_PLACE_M),
  )
  const unsupported = r.pinnable === false || !r.category
  return {
    id: r.place_id,
    name: r.place_name,
    meta: [r.category, r.address, center && formatDistance(distanceM(center, r))].filter(Boolean).join(' · '),
    address: r.address,
    url: r.place_source?.url,
    // 분류를 모르면 핀을 만들 요청 자체를 못 채운다(category 필수).
    unsupported,
    canLeaveLive: unsupported && !!r.category && FILTER_CATEGORIES.includes(r.category),
    alreadyPinned,
    far: center !== null && distanceM(center, r) > FAR_M,
    dto: r,
  }
}

/** docs/errors.md — 핀 만들기 실패. */
export function pinErrorMessage(err: unknown): string {
  if (err instanceof ApiError && err.code === 'PIN_DUPLICATE') return '이미 지도에 있는 장소예요'
  if (err instanceof ApiError && err.code === 'PLACE_NOT_SUPPORTED') return '아직 지원하지 않는 장소예요'
  return '핀을 찍지 못했어요'
}
