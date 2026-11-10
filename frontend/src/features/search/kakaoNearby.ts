import { loadKakaoMaps } from '@/features/map/kakaoMap'

import { distanceM, type LatLng, type PlaceSearchResultDto } from './model'

/** 카카오 분류 코드 → 우리 분류. 실시간 핀(#382)으로 남길 수 있는 셋만 찾는다. */
const CODES = { FD6: '음식점', CE7: '카페', AT4: '관광지' } as const

/** 누른 곳에서 이만큼(m) 안. 자체 DB 근처 찾기(`GET /places/nearest`)와 같은 거리다. */
const RADIUS_M = 100
/** 많아도 이만큼만 보인다 — 가까운 순. */
const MAX = 10
/** 자체 DB 결과와 이름이 같고 이만큼(m) 안이면 같은 가게로 보고 뺀다. */
const SAME_M = 50

/**
 * 카카오 장소 한 건을 검색 결과 모양으로 바꾼다. 자체 DB에 짝이 없으니 `pinnable: false` — 실시간 핀으로만 남긴다.
 * 이 값은 화면에 보이기만 하고 서버에는 장소 ID·검색어(이름)·분류·메모만 간다(livePinRequest, #53).
 */
export function fromKakao(p: kakao.maps.services.PlaceResult): PlaceSearchResultDto | null {
  const category = CODES[p.category_group_code as keyof typeof CODES]
  if (!category) return null
  return {
    place_id: `kakao:${p.id}`,
    place_name: p.place_name.slice(0, 100),
    lat: Number(p.y),
    lng: Number(p.x),
    category,
    address: (p.road_address_name || p.address_name).slice(0, 200) || undefined,
    pinnable: false,
  }
}

/** 가까운 순으로 MAX곳. 자체 DB 결과에 이미 있는 가게(이름이 같고 가까움)는 뺀다. */
export function pickNearby(found: PlaceSearchResultDto[], at: LatLng, own: PlaceSearchResultDto[]): PlaceSearchResultDto[] {
  const seen = new Set<string>()
  return found
    .filter((r) => !seen.has(r.place_id) && seen.add(r.place_id))
    .filter((r) => !own.some((o) => o.place_name === r.place_name && distanceM(o, r) < SAME_M))
    .sort((a, b) => distanceM(at, a) - distanceM(at, b))
    .slice(0, MAX)
}

/**
 * 누른 곳 근처의 음식점·카페·관광지를 브라우저의 카카오 SDK로 찾는다(#1549). 자체 DB 근처 찾기와 따로 간다 —
 * 결과는 메모리에서만 쓰고 저장하지 않는다(#53). SDK를 못 띄우거나 찾지 못하면 빈 목록이다(자체 DB 결과는 그대로 보인다).
 */
export async function nearbyKakaoPlaces(at: LatLng, own: PlaceSearchResultDto[]): Promise<PlaceSearchResultDto[]> {
  const maps = await loadKakaoMaps()
  const places = new maps.services.Places()
  const location = new maps.LatLng(at.lat, at.lng)
  const lists = await Promise.all(
    Object.keys(CODES).map(
      (code) =>
        new Promise<kakao.maps.services.PlaceResult[]>((resolve) =>
          places.categorySearch(code, (data, status) => resolve(status === 'OK' ? data : []), {
            location,
            radius: RADIUS_M,
            sort: maps.services.SortBy.DISTANCE,
          }),
        ),
    ),
  )
  return pickNearby(lists.flat().flatMap((p) => fromKakao(p) ?? []), at, own)
}
