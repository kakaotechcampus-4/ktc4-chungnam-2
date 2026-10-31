import type { components } from '@pingo/contracts/src/types/api'

import type { PinCreateRequest } from '@/features/map/model'

export type LinkPreviewItemDto = components['schemas']['LinkPreviewItem']
export type BulkPinItemResultDto = components['schemas']['BulkPinItemResult']
export type PlaceSearchResultDto = components['schemas']['PlaceSearchResult']

/**
 * 요청 한 번의 크기(docs/api-spec.yaml). 미리보기는 LinkPreviewRequest.urls 10개, 일괄 생성은 BulkPinRequest.pins 30개,
 * 대화 하나에서 확인하는 링크는 link-preview 설명의 50개. 화면 문구에는 이 숫자를 적지 않는다 — 센 개수만 보여 준다.
 */
export const PREVIEW_CHUNK = 10
export const BULK_CHUNK = 30
export const LINK_MAX = 50

/**
 * 구글맵·카카오맵 링크(#134 결정 2026-10-13). 네이버·인스타·블로그는 잡지 않는다.
 * 구글: google.<도메인>/maps/…, maps.google.<도메인>/…, maps.app.goo.gl/…, goo.gl/maps/…
 * 카카오: place.map.kakao.com/…, map.kakao.com/…, kko.to/…
 */
const MAP_LINK =
  /https?:\/\/(?:(?:www\.)?google\.[a-z.]+\/maps\/|maps\.google\.[a-z.]+\/|maps\.app\.goo\.gl\/|goo\.gl\/maps\/|place\.map\.kakao\.com\/|map\.kakao\.com\/|kko\.to\/)[^\s<>"']*/gi

/** 대화 문장에서 링크 뒤에 붙는 문장부호는 링크가 아니다(「…/123).」). */
const TRAILING = /[).,!?…]+$/

/**
 * 붙여넣은 대화에서 지도 링크만 뽑는다(#578). 브라우저 안에서만 돌고 대화 원문은 어디에도 보내지 않는다.
 * 같은 링크는 한 번만, 나온 순서대로. `found`는 중복을 뺀 전체 개수, `urls`는 앞에서부터 LINK_MAX개.
 */
export function extractMapLinks(text: string): { urls: string[]; found: number } {
  const seen = new Set<string>()
  for (const m of text.matchAll(MAP_LINK)) seen.add(m[0].replace(TRAILING, ''))
  const all = [...seen]
  return { urls: all.slice(0, LINK_MAX), found: all.length }
}

export function chunk<T>(items: T[], size: number): T[][] {
  const out: T[][] = []
  for (let i = 0; i < items.length; i += size) out.push(items.slice(i, i + size))
  return out
}

/**
 * 링크 하나의 상태.
 * - checking: 아직 미리보기를 받지 않음
 * - found: 자체 DB 장소가 있어 한꺼번에 찍을 수 있음(가까운 첫 장소)
 * - already: 이미 지도에 있음(가드레일 6) — 고를 수 없다
 * - oneByOne: 짝이 없어 사람이 이름으로 찾거나(구글) 이름을 적어야(카카오) 한다 — 링크 하나 붙여넣기(#487)로 넘긴다
 * - failed: 링크를 못 읽음(error_code)
 */
export type RowState = 'checking' | 'found' | 'already' | 'oneByOne' | 'failed'

export type ImportRow = {
  url: string
  item?: LinkPreviewItemDto
  /** 한꺼번에 찍을지(found만). */
  picked: boolean
  /** 일괄 생성 결과(created·duplicate·rejected). */
  outcome?: BulkPinItemResultDto['status']
  /** 「하나씩 찍기」로 넘겼다. */
  opened?: boolean
}

export function rowState(row: ImportRow): RowState {
  const item = row.item
  if (!item) return 'checking'
  if (item.status === 'error' || !item.result) return 'failed'
  if (item.already_pinned_pin_id) return 'already'
  return item.result.matches.length > 0 ? 'found' : 'oneByOne'
}

/** 찍을 장소 — 링크에 가장 가까운 자체 DB 장소. */
export const rowPlace = (row: ImportRow): PlaceSearchResultDto | undefined => row.item?.result?.matches[0]

/** 고른 줄을 핀 생성 요청으로(`source: search`, 검색 결과를 매칭 힌트로 그대로). 분류를 모르면 요청을 채울 수 없어 뺀다. */
export function toPinRequest(row: ImportRow): PinCreateRequest | null {
  const p = rowPlace(row)
  if (!p?.category) return null
  return { source: 'search', place_id: p.place_id, place_name: p.place_name, lat: p.lat, lng: p.lng, category: p.category }
}

/** docs/errors.md 문구. */
export function linkErrorMessage(code: string | undefined): string {
  if (code === 'LINK_NOT_SUPPORTED') return '구글맵·카카오맵 링크만 붙일 수 있어요'
  return '링크에서 장소를 찾지 못했어요'
}
