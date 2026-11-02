import type { components } from '@pingo/contracts/src/types/api'

import { isPlaced, type Pin } from '@/features/map/model'

export type ShortlistItemDto = components['schemas']['ShortlistItem']
/** 내보내기 형식(#471). 기본 이름에도 쓴다. */
export type ExportFormat = 'txt' | 'csv'

/** 동선 순서 표시는 확정 리스트 순서(visit_order)를 따른다. 정하지 않은 항목은 뒤로. */
export function sortItems(items: ShortlistItemDto[]): ShortlistItemDto[] {
  return [...items].sort((a, b) => (a.visit_order ?? Infinity) - (b.visit_order ?? Infinity))
}

/**
 * 위치를 아는 확정 장소 수 — 「동선 보기」와 「AI 코스」가 2곳부터라 이 수로 판단한다(#1127 리뷰: 두 화면이 따로 세던 것을 한 곳으로).
 * 실시간 핀(#382)은 좌표를 저장하지 않아 서버가 동선·코스에서 뺀다. 서버 `MIN_PLACES`·`intake.build_trip`과 같은 규칙의 복사본이다 —
 * 서버가 값을 내리면(루트 검수 #1127 ② 4번) 그 값으로 바꾼다.
 */
export const routableCount = (items: Pick<ShortlistItemDto, 'pin'>[]) => items.filter((i) => i.pin.source !== 'live').length

export type RouteDrawing = {
  stops: { n: number; lat: number; lng: number }[]
  legs: { from: { lat: number; lng: number }; to: { lat: number; lng: number }; label: string }[]
  /** 선 색 토큰 이름(예: '--course-day-2')과 카카오 선 모양. 없으면 「동선 보기」 모양(brand-600 실선, 골드 번호). AI 코스가 날짜를 가른다. */
  color?: string
  style?: string
}

/**
 * 지도에 그릴 그날 동선 — 일정 순서대로 직선 경로선과 순서 번호(2026-11-03, 일정이 순서를 정한다). 좌표는 핀에서 찾는다.
 * 번호는 일정 순서 그대로라 확정 탭 줄 번호와 같다. 좌표가 없는 핀(실시간 핀)은 그리지 않는다(그 번호는 비고 선은 건너 잇는다).
 * 구간 「약 N분」은 서버 규칙이라 여기서 계산하지 않는다 — 시간은 카카오맵 길찾기가 보여 준다.
 */
export function scheduleDrawing(ids: string[], pins: Pin[]): RouteDrawing {
  return {
    stops: ids.flatMap((id, i) => {
      const p = pins.find((pin) => pin.id === id)
      return p && isPlaced(p) ? [{ n: i + 1, lat: p.lat, lng: p.lng }] : []
    }),
    legs: [],
  }
}

/** 카카오맵 길찾기는 출발·도착 + 경유지 5곳까지 받는다(카카오맵 URL 규칙). */
export const KAKAO_ROUTE_MAX = 7

export type KakaoPoint = { name: string; lat: number; lng: number }

/** 카카오 링크 경로 한 칸 — 이름의 , / 는 구분자라 띄어쓰기로 바꾸고, 우리 핀의 이름·좌표만 담는다(#53). */
const kakaoPoint = (p: KakaoPoint) => `${encodeURIComponent((p.name || '장소').replace(/[,/]/g, ' '))},${p.lat},${p.lng}`

/** 이 순서대로 도보 길찾기를 여는 링크. 앞 KAKAO_ROUTE_MAX 곳만 담고, 2곳이 안 되면 없다. */
export function kakaoWalkUrl(stops: KakaoPoint[]): string | null {
  if (stops.length < 2) return null
  return `https://map.kakao.com/link/by/walk/${stops.slice(0, KAKAO_ROUTE_MAX).map(kakaoPoint).join('/')}`
}

/** 출발 → 도착 대중교통 길찾기 링크(경유지 없음). */
export function kakaoTrafficUrl(from: KakaoPoint, to: KakaoPoint): string {
  return `https://map.kakao.com/link/by/traffic/${kakaoPoint(from)}/${kakaoPoint(to)}`
}
