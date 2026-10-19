import type { components } from '@pingo/contracts/src/types/api'

import { isPlaced, type Pin } from '@/features/map/model'

export type ShortlistItemDto = components['schemas']['ShortlistItem']
export type RouteDto = components['schemas']['Route']

/** 동선 순서 표시는 확정 리스트 순서(visit_order)를 따른다. 정하지 않은 항목은 뒤로. */
export function sortItems(items: ShortlistItemDto[]): ShortlistItemDto[] {
  return [...items].sort((a, b) => (a.visit_order ?? Infinity) - (b.visit_order ?? Infinity))
}

/** 배열에서 from 번째를 to 자리로 옮긴다(끌어서 순서 바꾸기). */
export function move<T>(list: T[], from: number, to: number): T[] {
  const next = [...list]
  const [item] = next.splice(from, 1)
  next.splice(to, 0, item)
  return next
}

/** "대천 동선 · 3곳 · 총 약 14분 (직선거리 기준)" — 지역이 여럿이면 지역마다. 시간 배정은 하지 않는다(범위 밖). */
export function routeSummary(routes: RouteDto[]): string {
  return routes
    .map((r) => {
      const minutes = r.legs.reduce((sum, l) => sum + l.approx_minutes, 0)
      return `${r.region_label} 동선 · ${r.ordered_pin_ids.length}곳 · 총 약 ${minutes}분`
    })
    .join(' / ')
}

export type RouteDrawing = {
  stops: { n: number; lat: number; lng: number }[]
  legs: { from: { lat: number; lng: number }; to: { lat: number; lng: number }; label: string }[]
}

/** 지도에 그릴 동선 — 경로선(직선), 순서 번호, 구간 "약 N분". 좌표는 핀에서 찾는다. 좌표가 없는 핀(실시간 핀)은 서버 동선에도 없지만 여기서도 걸러 둔다. */
export function toRouteDrawings(routes: RouteDto[], pins: Pin[]): RouteDrawing[] {
  const at = (id: string) => pins.find((p) => p.id === id)
  return routes.map((r) => ({
    stops: r.ordered_pin_ids.flatMap((id, i) => {
      const p = at(id)
      return p && isPlaced(p) ? [{ n: i + 1, lat: p.lat, lng: p.lng }] : []
    }),
    legs: r.legs.flatMap((l) => {
      const a = at(l.from_pin_id)
      const b = at(l.to_pin_id)
      return a && b && isPlaced(a) && isPlaced(b) ? [{ from: a, to: b, label: `약 ${l.approx_minutes}분` }] : []
    }),
  }))
}

/** 카카오맵 길찾기는 출발·도착 + 경유지 5곳까지 받는다(카카오맵 URL 규칙). */
export const KAKAO_ROUTE_MAX = 7

/**
 * 동선 순서대로 카카오맵 길찾기(도보)를 여는 링크 — 지역마다 하나(트리플 「거리 → 길찾기」).
 * 좌표·이름은 우리 핀 것이라 카카오 응답을 저장하는 게 아니다(#53). 앞 7곳만 담고, 2곳이 안 되면 없다.
 * 이름의 , / 는 링크 구분자라 띄어쓰기로 바꾼다. 이동 수단은 카카오맵에서 바꿀 수 있다.
 */
export function kakaoDirectionsUrl(route: RouteDto, pins: Pin[]): string | null {
  const stops = route.ordered_pin_ids.flatMap((id) => {
    const p = pins.find((pin) => pin.id === id)
    return p && isPlaced(p) ? [p] : []
  })
  if (stops.length < 2) return null
  const path = stops
    .slice(0, KAKAO_ROUTE_MAX)
    .map((p) => `${encodeURIComponent((p.place_name ?? '장소').replace(/[,/]/g, ' '))},${p.lat},${p.lng}`)
    .join('/')
  return `https://map.kakao.com/link/by/walk/${path}`
}
