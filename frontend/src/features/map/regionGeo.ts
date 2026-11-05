import { useQuery } from '@tanstack/react-query'

import { REGION_CODES } from '@/features/maps/regions'

/**
 * 여행 지역(지도 만들 때 고른 시·도)의 경계와 그 계산. AI 추천 탭이 경계를 그리고, 추천 원이 지역 밖인지 본다.
 * 경계 파일과 출처는 `regionBoundaries/README.md`.
 */

/** [위도, 경도] */
export type LatLngTuple = [number, number]
export type Ring = LatLngTuple[]
/** 외곽 고리 하나와 구멍들. 외곽은 반시계, 구멍은 시계 방향이다. */
export type RegionPolygon = Ring[]
/** 시·도 하나 — 섬이 있으면 다각형이 여럿이다. */
export type RegionBoundary = RegionPolygon[]
type Point = { lat: number; lng: number }

// 지도 지역 파일 하나만 필요할 때 불러온다 — 첫 화면 번들에 넣지 않는다.
const files = import.meta.glob<RegionBoundary>('./regionBoundaries/*.json', { import: 'default' })

/** 그 지역 경계. 지역이 없거나 경계 파일이 없으면 null, 불러오는 중에도 null이다. */
export function useRegionBoundary(regionLabel: string | undefined): RegionBoundary | null {
  const code = regionLabel ? REGION_CODES[regionLabel] : undefined
  const load = code ? files[`./regionBoundaries/${code}.json`] : undefined
  const query = useQuery({
    queryKey: ['region-boundary', code],
    queryFn: async () => {
      try {
        return await load!()
      } catch (err) {
        // 경계가 없으면 지역 밖 안내 없이 원만 그린다. 조용히 넘기지 않게 콘솔에 남긴다.
        console.error('[map] 지역 경계를 불러오지 못했어요', code, err)
        throw err
      }
    },
    enabled: Boolean(load),
    staleTime: Infinity,
    gcTime: Infinity,
    retry: false,
  })
  return query.data ?? null
}

/** 점이 지역 안에 있다(짝홀 규칙 — 구멍 안은 밖이다). */
export function pointInRegion(p: Point, boundary: RegionBoundary): boolean {
  let inside = false
  for (const polygon of boundary) {
    for (const ring of polygon) {
      for (let i = 0, j = ring.length - 1; i < ring.length; j = i++) {
        const [yi, xi] = ring[i]
        const [yj, xj] = ring[j]
        if (yi > p.lat !== yj > p.lat && p.lng < ((xj - xi) * (p.lat - yi)) / (yj - yi) + xi) inside = !inside
      }
    }
  }
  return inside
}

const EARTH_M = 6_371_000
const rad = (d: number) => (d * Math.PI) / 180

/** 점에서 경계선까지 가장 가까운 거리(m). 시·도 크기에서는 점 둘레를 평면으로 펴서 재도 충분하다. */
export function distanceToBoundaryM(p: Point, boundary: RegionBoundary): number {
  const kx = Math.cos(rad(p.lat)) * EARTH_M
  const xy = ([lat, lng]: LatLngTuple) => [rad(lng - p.lng) * kx, rad(lat - p.lat) * EARTH_M] as const
  let best = Infinity
  for (const polygon of boundary) {
    for (const ring of polygon) {
      for (let i = 0, j = ring.length - 1; i < ring.length; j = i++) {
        const [ax, ay] = xy(ring[j])
        const [bx, by] = xy(ring[i])
        const dx = bx - ax
        const dy = by - ay
        const len = dx * dx + dy * dy
        const t = len === 0 ? 0 : Math.max(0, Math.min(1, -(ax * dx + ay * dy) / len))
        best = Math.min(best, Math.hypot(ax + t * dx, ay + t * dy))
      }
    }
  }
  return best
}

/** 원 전체가 지역 밖이다 — 가운데가 밖이고 경계선까지 반경보다 멀다. 걸치기만 해도 밖이 아니다. */
export function circleOutsideRegion(center: Point, radiusM: number, boundary: RegionBoundary): boolean {
  return !pointInRegion(center, boundary) && distanceToBoundaryM(center, boundary) > radiusM
}

/** 경계를 감싸는 상자의 남서·북동 모서리. 「여행 지역으로 가기」가 이 두 점이 보이게 맞춘다. */
export function boundaryCorners(boundary: RegionBoundary): [Point, Point] {
  let south = Infinity
  let west = Infinity
  let north = -Infinity
  let east = -Infinity
  for (const polygon of boundary) {
    for (const [lat, lng] of polygon[0]) {
      south = Math.min(south, lat)
      north = Math.max(north, lat)
      west = Math.min(west, lng)
      east = Math.max(east, lng)
    }
  }
  return [
    { lat: south, lng: west },
    { lat: north, lng: east },
  ]
}

/** 점 p에서 북·남·동·서로 m미터 떨어진 네 점 — 원이 화면에 들어오는지 잴 때 쓴다. */
export function circleExtremes(p: Point, m: number): Point[] {
  const dLat = (m / EARTH_M) * (180 / Math.PI)
  const dLng = dLat / Math.cos(rad(p.lat))
  return [
    { lat: p.lat + dLat, lng: p.lng },
    { lat: p.lat - dLat, lng: p.lng },
    { lat: p.lat, lng: p.lng + dLng },
    { lat: p.lat, lng: p.lng - dLng },
  ]
}
