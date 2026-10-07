import { useCallback, useEffect } from 'react'
import { create } from 'zustand'

import { loadKakaoMaps } from './kakaoMap'
import { isPlaced, type Pin } from './model'

/**
 * 실시간 핀(#382)의 위치.
 *
 * 서버는 실시간 핀의 카카오 장소 ID·검색어·메모만 저장한다 — 이름·좌표는 카카오 약관상 저장할 수 없다(#53).
 * 그래서 지도를 열 때마다 카카오 키워드 검색으로 저장된 검색어를 다시 찾고, 결과 중 장소 ID가 같은 것의
 * 이름·좌표로 마커를 그린다. 이 값은 이 모듈의 메모리에만 있다 — 서버·localStorage·캐시 어디에도 보내지 않는다.
 */
export type LivePlace = { name: string; lat: number; lng: number }

/** 'missing' = 검색은 됐는데 그 장소가 없다(폐업·이름 변경). 아직 안 찾았으면 키가 없다. */
type LivePlaceState = LivePlace | 'missing'

type Store = {
  places: Record<string, LivePlaceState>
  set: (pinId: string, place: LivePlaceState) => void
}

export const useLivePlaceStore = create<Store>((set) => ({
  places: {},
  set: (pinId, place) => set((s) => ({ places: { ...s.places, [pinId]: place } })),
}))

export type LocationState = 'found' | 'missing' | 'loading'

export const kakaoPlaceUrl = (kakaoPlaceId: string | undefined) =>
  kakaoPlaceId ? `https://place.map.kakao.com/${kakaoPlaceId.replace(/^kakao:/, '')}` : undefined

export const isLive = (pin: Pin) => pin.source === 'live'

/** 실시간 핀에 찾은 이름·좌표를 얹는다. 못 찾았거나 찾는 중이면 이름은 검색어, 좌표는 없는 채로 둔다. */
export function withLivePlace(pin: Pin, places: Record<string, LivePlaceState>): Pin {
  if (!isLive(pin)) return pin
  const found = places[pin.id]
  const base = { ...pin, place_url: kakaoPlaceUrl(pin.kakao_place_id) }
  if (found && found !== 'missing') return { ...base, place_name: found.name, lat: found.lat, lng: found.lng }
  return { ...base, place_name: pin.search_query }
}

export function locationState(pin: Pin, places: Record<string, LivePlaceState>): LocationState {
  const found = places[pin.id]
  if (!found) return 'loading'
  return found === 'missing' ? 'missing' : 'found'
}

/** 확정 리스트 항목처럼 핀 목록 밖에서 온 핀에도 같은 이름·좌표를 얹을 때 쓴다. */
export function useEnrichPin() {
  const places = useLivePlaceStore((s) => s.places)
  return useCallback((pin: Pin) => withLivePlace(pin, places), [places])
}

/** 카카오 키워드 검색은 한 번에 15건, 최대 3쪽(45건)까지 준다. */
const MAX_PAGES = 3
/** 카카오 키워드 검색 반경 상한(20km) — 지도 지역(시·도)을 넉넉히 덮는다. */
const RADIUS_M = 20_000

type Center = { lat: number; lng: number }

/** 분류 → 카카오 카테고리 그룹 코드. 같은 이름 검색이어도 분류로 좁히면 45건 안에 들 가능성이 커진다. */
const GROUP_CODE: Partial<Record<Pin['category'], string>> = { 음식점: 'FD6', 카페: 'CE7', 관광지: 'AT4' }

/**
 * 같은 검색은 이 화면이 열려 있는 동안 한 번만 부른다. 새로고침하면 사라지는 메모리 캐시다.
 * 키의 중심은 0.02도(약 2km)로 뭉쳐서, 핀이 하나 늘 때마다 새로 찾지 않게 한다.
 */
const searches = new Map<string, Promise<kakao.maps.services.PlaceResult[]>>()
const inflight = new Set<string>()

type SearchOptions = { center: Center | null; category: Pin['category'] }

function searchAll(query: string, { center, category }: SearchOptions): Promise<kakao.maps.services.PlaceResult[]> {
  const key = [query, category, center ? `${center.lat.toFixed(2)},${center.lng.toFixed(2)}` : 'none'].join('|')
  const cached = searches.get(key)
  if (cached) return cached

  const run = loadKakaoMaps().then(async (maps) => {
    const places = new maps.services.Places()
    const all: kakao.maps.services.PlaceResult[] = []
    for (let page = 1; page <= MAX_PAGES; page++) {
      const { data, hasNext } = await new Promise<{ data: kakao.maps.services.PlaceResult[]; hasNext: boolean }>((resolve, reject) => {
        places.keywordSearch(
          query,
          (data, status, pagination) => {
            if (status === 'OK') resolve({ data, hasNext: pagination.current < pagination.last })
            else if (status === 'ZERO_RESULT') resolve({ data: [], hasNext: false })
            else reject(new Error('카카오 장소 검색에 실패했어요'))
          },
          {
            page,
            category_group_code: GROUP_CODE[category],
            // 기준이 있으면 그 근처부터 거리순으로 — 기준이 없으면 카카오의 정확도순.
            ...(center ? { location: new maps.LatLng(center.lat, center.lng), radius: RADIUS_M, sort: maps.services.SortBy.DISTANCE } : {}),
          },
        )
      })
      all.push(...data)
      if (!hasNext) break
    }
    return all
  })
  searches.set(key, run)
  // 실패를 캐시하면 새로고침 전까지 다시 못 찾는다.
  run.catch(() => searches.delete(key))
  return run
}

const FALLBACK_CENTER: Center = { lat: 37.5665, lng: 126.978 }

/**
 * 이 지도의 위치 기준. 실시간 핀은 같은 동네에 모이는 경우가 많아서, 이미 지도에 있는 자체 DB 핀들의 중심
 * (우리 데이터)을 기준으로 가까운 곳부터 찾는다. 없으면 지도를 만들 때 고른 지역, 그것도 없으면 서울 한가운데.
 */
export function livePlaceAnchor(pins: Pin[], regionCenter: Center | null | undefined): Center {
  const own = pins.filter((p) => !isLive(p) && isPlaced(p))
  if (own.length === 0) return regionCenter ?? FALLBACK_CENTER
  const sum = own.reduce((s, p) => ({ lat: s.lat + p.lat!, lng: s.lng + p.lng! }), { lat: 0, lng: 0 })
  return { lat: sum.lat / own.length, lng: sum.lng / own.length }
}

/** 기준 근처 거리순으로 먼저, 못 찾으면 기준 없이 정확도순으로 한 번 더. */
async function findLivePlace(pin: Pin, anchor: Center): Promise<kakao.maps.services.PlaceResult | undefined> {
  const wanted = pin.kakao_place_id!.replace(/^kakao:/, '')
  for (const center of [anchor, null]) {
    const results = await searchAll(pin.search_query!, { center, category: pin.category })
    const hit = results.find((r) => r.id === wanted)
    if (hit) return hit
  }
  return undefined
}

/**
 * 아직 위치를 모르는 실시간 핀을 찾는다. 지도 화면(MapLayout)에서 한 번만 쓴다.
 * 검색이 실패(키 없음·네트워크)하면 'missing'으로 박지 않고 둔다 — 다음에 핀 목록이 바뀔 때 다시 찾는다.
 */
export function useLivePinResolver(pins: Pin[], regionCenter: Center | null | undefined) {
  const places = useLivePlaceStore((s) => s.places)
  const set = useLivePlaceStore((s) => s.set)

  useEffect(() => {
    const todo = pins.filter((p) => isLive(p) && p.search_query && p.kakao_place_id && !(p.id in places) && !inflight.has(p.id))
    if (todo.length === 0) return

    const anchor = livePlaceAnchor(pins, regionCenter)
    for (const pin of todo) {
      inflight.add(pin.id)
      findLivePlace(pin, anchor)
        .then((hit) => set(pin.id, hit ? { name: hit.place_name, lat: Number(hit.y), lng: Number(hit.x) } : 'missing'))
        .catch(() => undefined)
        .finally(() => inflight.delete(pin.id))
    }
  }, [pins, places, regionCenter, set])
}
