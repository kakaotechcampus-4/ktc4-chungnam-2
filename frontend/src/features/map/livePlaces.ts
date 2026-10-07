import { useCallback, useEffect } from 'react'
import { create } from 'zustand'

import { loadKakaoMaps } from './kakaoMap'
import type { Pin } from './model'

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

/** 같은 검색어는 이 화면이 열려 있는 동안 한 번만 부른다. 새로고침하면 사라지는 메모리 캐시다. */
const searches = new Map<string, Promise<kakao.maps.services.PlaceResult[]>>()
const inflight = new Set<string>()

function searchAll(query: string, center: Center): Promise<kakao.maps.services.PlaceResult[]> {
  const key = `${query}|${center.lat.toFixed(1)},${center.lng.toFixed(1)}`
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
          { location: new maps.LatLng(center.lat, center.lng), radius: RADIUS_M, page },
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
 * 아직 위치를 모르는 실시간 핀을 찾는다. 지도 화면(MapLayout)에서 한 번만 쓴다.
 * 검색이 실패(키 없음·네트워크)하면 'missing'으로 박지 않고 둔다 — 다음에 핀 목록이 바뀔 때 다시 찾는다.
 */
export function useLivePinResolver(pins: Pin[], center: Center | null | undefined) {
  const places = useLivePlaceStore((s) => s.places)
  const set = useLivePlaceStore((s) => s.set)

  useEffect(() => {
    const todo = pins.filter((p) => isLive(p) && p.search_query && p.kakao_place_id && !(p.id in places) && !inflight.has(p.id))
    if (todo.length === 0) return

    const byQuery = new Map<string, Pin[]>()
    for (const p of todo) {
      inflight.add(p.id)
      byQuery.set(p.search_query!, [...(byQuery.get(p.search_query!) ?? []), p])
    }

    for (const [query, group] of byQuery) {
      searchAll(query, center ?? FALLBACK_CENTER)
        .then((results) => {
          for (const pin of group) {
            const wanted = pin.kakao_place_id!.replace(/^kakao:/, '')
            const hit = results.find((r) => r.id === wanted)
            set(pin.id, hit ? { name: hit.place_name, lat: Number(hit.y), lng: Number(hit.x) } : 'missing')
          }
        })
        .catch(() => undefined)
        .finally(() => group.forEach((p) => inflight.delete(p.id)))
    }
  }, [pins, places, center, set])
}
