import { describe, expect, it } from 'vitest'

import { chunk, foundLabel, hintOf, placeKey, roadKey, rowState, rowTitle, sameRoadAddress, toPinRequest, type ImportRow } from './model'
import type { Share } from './share'

describe('chunk', () => {
  it('요청 크기만큼 나눈다', () => {
    expect(chunk([1, 2, 3, 4, 5], 2)).toEqual([[1, 2], [3, 4], [5]])
  })
})

const own = { place_id: 'own:1', place_name: '유소바 안국역점', lat: 37.57, lng: 126.98, category: '음식점' as const, address: '서울 종로구 창덕궁1길 32', pinnable: true }
const kakaoOnly = { place_id: 'kakao:9', place_name: '우슬', lat: 36.32, lng: 127.42, category: '음식점' as const, address: '대전 중구 중앙로138번길 48', pinnable: false }
const naver: Share = { url: 'https://naver.me/a', provider: 'naver', name: '유소바 안국역점', address: '서울 종로구 창덕궁1길 32 1층' }
const row = (share: Share, item?: ImportRow['item'], extra: Partial<ImportRow> = {}): ImportRow => ({ share, item, picked: false, ...extra })
const ok = (result: NonNullable<ImportRow['item']>['result']): ImportRow['item'] => ({ index: 0, status: 'ok', result })

describe('상태 — 4단 해결 순서(#1046)', () => {
  it('서버가 찾으면 found, 같은 주소 후보면 confirm, 이름만 알면 search, 번호뿐이면 needsName', () => {
    expect(rowState(row(naver, ok({ provider: 'naver', external_id: 'naver:1', matches: [own], matched_by: 'hint', needs_search_query: false })))).toBe('found')
    expect(rowState(row(naver, ok({ provider: 'naver', matches: [], address_candidates: [own], needs_search_query: true })))).toBe('confirm')
    expect(rowState(row(naver, ok({ provider: 'naver', matches: [], needs_search_query: true })))).toBe('search')
    expect(rowState(row({ url: 'https://naver.me/b', provider: 'naver' }, ok({ provider: 'naver', matches: [], needs_search_query: true })))).toBe('needsName')
  })
  it('구글은 서버가 준 링크 속 이름으로도 찾고, 링크를 못 읽어도 이름을 알면 숨기지 않는다', () => {
    const google: Share = { url: 'https://maps.app.goo.gl/x', provider: 'google' }
    expect(rowState(row(google, ok({ provider: 'google', name_hint: '강남면옥 정동점', matches: [], needs_search_query: false })))).toBe('search')
    expect(rowState(row({ ...google, name: '우슬' }, { index: 0, status: 'error', error_code: 'LINK_UNRESOLVED' }))).toBe('search')
    expect(rowState(row(google, { index: 0, status: 'error', error_code: 'LINK_UNRESOLVED' }))).toBe('failed')
  })
  it('이미 지도에 있으면 already, 응답 전이면 checking', () => {
    expect(rowState(row(naver, { index: 0, status: 'ok', already_pinned_pin_id: 'p', result: { provider: 'naver', matches: [own], needs_search_query: false } }))).toBe('already')
    expect(rowState(row(naver))).toBe('checking')
  })
})

describe('줄 제목 — 링크 주소를 제목으로 쓰지 않는다(#1046)', () => {
  it('고른 장소 → 공유 글 이름 → 링크 속 이름 → 「이름 확인 필요」', () => {
    expect(rowTitle(row(naver, ok({ provider: 'naver', matches: [own], needs_search_query: false })))).toBe('유소바 안국역점')
    expect(rowTitle(row({ ...naver, name: '우슬 대전점' }, undefined, { choice: kakaoOnly }))).toBe('우슬')
    expect(rowTitle(row(naver))).toBe('유소바 안국역점')
    expect(rowTitle(row({ url: 'u', provider: 'google' }, ok({ provider: 'google', name_hint: '강남면옥 정동점', matches: [], needs_search_query: false })))).toBe('강남면옥 정동점')
    expect(rowTitle(row({ url: 'https://kko.to/x', provider: 'kakao' }))).toBe('이름 확인 필요')
  })
  it('찾은 방법을 사람 말로 붙인다', () => {
    expect(foundLabel(row(naver, ok({ provider: 'naver', matches: [own], matched_by: 'hint', needs_search_query: false })))).toBe('이름·주소가 같아서 찾았어요')
    expect(foundLabel(row(naver, ok({ provider: 'naver', matches: [own], matched_by: 'external_id', needs_search_query: false })))).toBe('이미 확인된 장소예요')
    expect(foundLabel(row(naver, undefined, { auto: true, choice: own }))).toBe('주소가 같아요')
  })
})

describe('힌트·주소 비교', () => {
  it('네이버·카카오 공유 글은 이름과 주소가 다 있을 때만 힌트를 보낸다 — 구글은 보내지 않는다', () => {
    expect(hintOf(naver)).toEqual({ name: '유소바 안국역점', address: '서울 종로구 창덕궁1길 32 1층' })
    expect(hintOf({ ...naver, address: undefined })).toBeNull()
    expect(hintOf({ url: 'u', provider: 'google', name: '우슬', address: '대전 중구 중앙로138번길 48' })).toBeNull()
  })
  it('도로명 + 건물번호까지 비교한다 — 층·상호 꼬리·괄호 동 이름·정식 시·도 이름은 같다', () => {
    expect(roadKey('서울 종로구 창덕궁1길 32 1층')).toBe('서울종로구창덕궁1길32')
    expect(sameRoadAddress('서울특별시 종로구 창덕궁1길 32 1층 예시상호', '서울 종로구 창덕궁1길 32')).toBe(true)
    expect(sameRoadAddress('대전 중구 중앙로138번길 48 (대흥동)', '대전 중구 중앙로138번길 48')).toBe(true)
    expect(sameRoadAddress('서울 종로구 북촌로 12-3', '서울 종로구 북촌로 12-5')).toBe(false)
    // 건물번호가 없으면(동 이름뿐) 같다고 하지 않는다
    expect(sameRoadAddress('부산 해운대구 우동', '부산 해운대구 우동')).toBe(false)
  })
})

describe('핀 만들기 요청', () => {
  it('자체 DB 장소는 search 핀이고, 카카오·네이버 링크에서 왔으면 번호를 link_ref 로 돌려 보낸다', () => {
    const r = row(naver, ok({ provider: 'naver', external_id: 'naver:1412566798', matches: [own], matched_by: 'hint', needs_search_query: false }))
    expect(toPinRequest(r)).toEqual({
      source: 'search',
      place_id: 'own:1',
      place_name: '유소바 안국역점',
      lat: 37.57,
      lng: 126.98,
      category: '음식점',
      link_ref: { provider: 'naver', external_id: 'naver:1412566798' },
    })
  })
  it('자체 DB에 없는 카카오 장소는 공유 글 이름을 검색어로 실시간 핀이다', () => {
    const r = row({ url: 'https://kko.to/x', provider: 'kakao', name: '우슬', address: '대전 중구 중앙로138번길 48' }, undefined, { choice: kakaoOnly, picked: true })
    expect(toPinRequest(r)).toEqual({ source: 'live', category: '음식점', kakao_place_id: 'kakao:9', search_query: '우슬' })
  })
  it('고른 장소가 같으면 다른 링크라도 같은 곳이다', () => {
    const a = row(naver, ok({ provider: 'naver', matches: [own], needs_search_query: false }))
    const b = row({ url: 'https://maps.app.goo.gl/y', provider: 'google' }, undefined, { choice: own, picked: true })
    expect(placeKey(a)).toBe(placeKey(b))
    expect(placeKey(row(naver))).toBeUndefined()
  })
})
