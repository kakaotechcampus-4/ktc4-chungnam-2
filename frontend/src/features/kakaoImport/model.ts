import type { components } from '@pingo/contracts/src/types/api'

import type { PinCreateRequest } from '@/features/map/model'
import { livePinRequest, searchPinRequest } from '@/features/search/model'

import { LINK_MAX, shortSido, type Share } from './share'

export type LinkPreviewItemDto = components['schemas']['LinkPreviewItem']
export type LinkParseResultDto = components['schemas']['LinkParseResult']
export type BulkPinItemResultDto = components['schemas']['BulkPinItemResult']
export type PlaceSearchResultDto = components['schemas']['PlaceSearchResult']
/** link-preview 요청의 상호명·주소 힌트(#946). 서버가 자체 DB 짝을 찾는 데만 쓰고 저장하지 않는다. */
export type LinkHint = { name: string; address?: string }

/**
 * 요청 한 번의 크기(docs/api-spec.yaml). 미리보기는 LinkPreviewRequest.urls 10개, 일괄 생성은 BulkPinRequest.pins 30개.
 * 화면 문구에는 이 숫자를 적지 않는다 — 센 개수만 보여 준다.
 */
export const PREVIEW_CHUNK = 10
export const BULK_CHUNK = 30
/** 이름으로 찾은 후보를 몇 곳까지 보여 줄지. */
export const SEARCH_SHOWN = 3

export function chunk<T>(items: T[], size: number): T[][] {
  const out: T[][] = []
  for (let i = 0; i < items.length; i += size) out.push(items.slice(i, i + size))
  return out
}

/**
 * 링크 하나의 진행. 대화 원문은 담지 않는다 — 링크와 공유 글에서 읽은 이름·주소(`share`)와 서버 응답뿐이다.
 * - `choice`: 핀으로 만들 장소. 서버가 찾은 곳(matches)은 비워 두고 그 첫 장소를 쓴다. 주소 후보·이름 검색 후보는 사람이 고른 것(또는 주소가 같아 미리 고른 것)
 * - `auto`: 이름 검색에서 공유 글 주소와 도로명주소(건물번호까지)가 같은 곳이 하나라 미리 고른 것
 */
export type ImportRow = {
  share: Share
  item?: LinkPreviewItemDto
  search?: { status: 'loading' | 'done' | 'error'; results: PlaceSearchResultDto[] }
  choice?: PlaceSearchResultDto | null
  /** 새로고침 뒤 되살린 줄의 고른 장소 id(#1045). 주소 후보·이름 검색 응답이 오면 이 id로 `choice`를 다시 맞추고 지운다. */
  choiceId?: string
  auto?: boolean
  picked: boolean
  outcome?: BulkPinItemResultDto['status']
  /** 「하나씩 찍기」로 검색 화면에 넘겼다. */
  opened?: boolean
}

/**
 * 링크 하나의 상태 — 4단 해결(#1046 루트 코멘트) 순서다.
 * - checking: 아직 미리보기를 받지 않음
 * - already: 이미 지도에 있음(가드레일 6) — 고를 수 없다
 * - found: 서버가 자체 DB 장소를 찾음(링크·번호표·상호명+주소) — 미리 체크
 * - confirm: 같은 도로명주소에 한 곳(`address_candidates`) — 「이 장소가 맞나요?」, 미리 체크하지 않는다(가드레일 2·4)
 * - search: 이름은 아는데 짝이 없음 — 이름으로 찾은 후보에서 고른다
 * - needsName: 이름도 모름(번호만 든 링크) — 검색 화면에서 하나씩 찍는다
 * - failed: 링크를 못 읽고 이름도 모름
 */
export type RowState = 'checking' | 'already' | 'found' | 'confirm' | 'search' | 'needsName' | 'failed'

/** 공유 글 이름, 없으면 구글 링크 속 이름(서버 name_hint). */
export const rowName = (row: ImportRow): string | undefined => row.share.name ?? row.item?.result?.name_hint

export function rowState(row: ImportRow): RowState {
  const item = row.item
  if (!item) return 'checking'
  if (item.already_pinned_pin_id) return 'already'
  const result = item.status === 'ok' ? item.result : undefined
  if (result?.matches.length) return 'found'
  if (result?.address_candidates?.length) return 'confirm'
  // DB에 없는 곳도, 링크를 못 읽은 곳도 이름을 알면 숨기지 않고 이름으로 찾는다(#1046).
  if (rowName(row)) return 'search'
  return item.status === 'error' ? 'failed' : 'needsName'
}

/** 핀으로 만들 장소 — 사람이(또는 주소로 미리) 고른 곳, 없으면 서버가 찾은 첫 장소. */
export function rowPlace(row: ImportRow): PlaceSearchResultDto | undefined {
  if (row.choice) return row.choice
  // 이미 지도에 있는 곳(찍은 뒤 다시 확인한 줄 포함)도 서버가 찾은 장소로 이름·같은 곳 묶음을 맞춘다.
  const state = rowState(row)
  return state === 'found' || state === 'already' ? row.item?.result?.matches[0] : undefined
}

/** 줄 제목: 고른 장소 → 공유 글 이름 → 링크 속 이름 → 「이름 확인 필요」. 링크 주소는 제목으로 쓰지 않는다(#1046). */
export const rowTitle = (row: ImportRow): string => rowPlace(row)?.place_name ?? rowName(row) ?? '이름 확인 필요'

/** 서버가 어떻게 찾았는지 / 주소로 미리 골랐는지. 사람이 믿고 넘어가도 되는지 판단하게 보여 준다. */
export function foundLabel(row: ImportRow): string | null {
  if (row.auto) return '주소가 같아요'
  const by = row.item?.result?.matched_by
  if (rowState(row) !== 'found') return null
  if (by === 'hint') return '이름·주소가 같아서 찾았어요'
  if (by === 'external_id') return '이미 확인된 장소예요'
  return null
}

/** 공유 글의 상호명·주소 힌트. 네이버·카카오만(구글은 이름만이라 이름 검색에 쓴다). 주소가 없으면 보내지 않는다 — 서버는 주소 없이 확정하지 않는다. */
export function hintOf(share: Share): LinkHint | null {
  if (share.provider === 'google' || !share.name || !share.address) return null
  return { name: share.name.slice(0, 100), address: share.address.slice(0, 200) }
}

/**
 * 도로명 + 건물번호까지(「서울 종로구 창덕궁1길 32」). 층·호수·상호 꼬리와 괄호 속 동 이름은 버리고, 시·도는 줄임말로 맞춘다.
 * 건물번호가 없으면 null — 비교하지 않는다(동 이름만으로 같은 곳이라 하지 않는다).
 */
export function roadKey(address: string | undefined): string | null {
  if (!address) return null
  const tokens = address.replace(/\([^)]*\)/g, ' ').trim().split(/\s+/)
  tokens[0] = shortSido(tokens[0])
  const out: string[] = []
  for (const t of tokens) {
    out.push(t)
    if (out.length >= 3 && /^\d+(-\d+)?$/.test(t)) return out.join('')
  }
  return null
}

export const sameRoadAddress = (a: string | undefined, b: string | undefined) => {
  const ka = roadKey(a)
  return ka !== null && ka === roadKey(b)
}

/**
 * 고른 장소로 핀 만들기 요청. 자체 DB 장소면 `source: search`, 자체 DB에 없는 카카오 장소면 실시간 핀(`source: live`, 검색어는 공유 글 이름).
 * 카카오·네이버 링크에서 왔으면 그 번호를 `link_ref`로 돌려 보낸다(#1048) — 서버가 "이 번호 = 이 장소" 표를 쌓는다.
 */
export function toPinRequest(row: ImportRow): PinCreateRequest | null {
  const place = rowPlace(row)
  if (!place) return null
  if (place.pinnable !== false) {
    const req = searchPinRequest(place)
    const result = row.item?.result
    const provider = result?.provider
    if (req && result?.external_id && (provider === 'kakao' || provider === 'naver')) {
      return { ...req, link_ref: { provider, external_id: result.external_id } } as PinCreateRequest
    }
    return req
  }
  return livePinRequest(place, rowName(row) ?? place.place_name)
}

/** 같은 장소인지 — 고른 장소의 id. 다른 링크라도 같은 장소면 한 줄로 보이고 한 번만 찍는다. 고르지 않은 줄은 합치지 않는다. */
export const placeKey = (row: ImportRow): string | undefined => rowPlace(row)?.place_id ?? row.choiceId

/** docs/errors.md 문구. */
export function linkErrorMessage(code: string | undefined): string {
  if (code === 'LINK_NOT_SUPPORTED') return '구글맵, 카카오맵 링크만 붙일 수 있어요'
  return '링크에서 장소를 찾지 못했어요'
}

/**
 * 대화 파일을 더 넣으면 새 링크만 기존 줄에 더한다(#1045). 같은 링크는 한 줄이고, 앞서 이름·주소를 못 읽었는데 이번에 읽었으면
 * 그 힌트로 바꿔 다시 확인하게 응답을 비운다(이미 찍은 줄은 그대로). 상한은 누적 합계 기준이다 — 넘친 링크는 버리고 `truncated`.
 */
export function mergeRows(rows: ImportRow[], shares: Share[], max = LINK_MAX): { rows: ImportRow[]; added: number; truncated: boolean } {
  const out = [...rows]
  const at = new Map(out.map((r, i) => [r.share.url, i]))
  let added = 0
  let truncated = false
  for (const share of shares) {
    const i = at.get(share.url)
    if (i !== undefined) {
      const old = out[i]
      if (!old.share.name && share.name && !old.outcome) {
        out[i] = { share, picked: false }
        added += 1
      }
      continue
    }
    if (out.length >= max) {
      truncated = true
      continue
    }
    at.set(share.url, out.length)
    out.push({ share, picked: false })
    added += 1
  }
  return { rows: out, added, truncated }
}
