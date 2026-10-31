import { describe, expect, it } from 'vitest'

import { chunk, extractMapLinks, LINK_MAX, rowState, toPinRequest, type ImportRow } from './model'

const CHAT = `2026. 10. 1. 오후 3:01, 지우 : 여기 어때 https://place.map.kakao.com/12345
2026. 10. 1. 오후 3:02, 민수 : 구글로 찾음 https://www.google.com/maps/place/광안리+해변/@35.1532,129.1186,17z).
2026. 10. 1. 오후 3:03, 지우 : 블로그 https://blog.naver.com/a/1 인스타 https://instagram.com/p/x
2026. 10. 1. 오후 3:04, 민수 : 또 https://place.map.kakao.com/12345 단축 https://kko.to/AbC, https://maps.app.goo.gl/xyz`

describe('extractMapLinks (#578 대화에서 지도 링크만)', () => {
  it('구글맵·카카오맵만, 중복 없이, 나온 순서대로, 뒤 문장부호는 뗀다', () => {
    expect(extractMapLinks(CHAT)).toEqual({
      urls: [
        'https://place.map.kakao.com/12345',
        'https://www.google.com/maps/place/광안리+해변/@35.1532,129.1186,17z',
        'https://kko.to/AbC',
        'https://maps.app.goo.gl/xyz',
      ],
      found: 4,
    })
  })
  it('링크가 없으면 빈 목록', () => {
    expect(extractMapLinks('내일 몇 시에 만나?')).toEqual({ urls: [], found: 0 })
  })
  it('상한을 넘으면 앞에서부터 자르고 찾은 수는 그대로 센다', () => {
    const many = Array.from({ length: LINK_MAX + 5 }, (_, i) => `https://kko.to/p${i}`).join(' ')
    const { urls, found } = extractMapLinks(many)
    expect(urls).toHaveLength(LINK_MAX)
    expect(found).toBe(LINK_MAX + 5)
  })
})

describe('chunk', () => {
  it('요청 크기만큼 나눈다', () => {
    expect(chunk([1, 2, 3, 4, 5], 2)).toEqual([[1, 2], [3, 4], [5]])
  })
})

const place = { place_id: 'own:1', place_name: '광안리 해변', lat: 35.15, lng: 129.11, category: '관광지' as const }
const row = (item?: ImportRow['item']): ImportRow => ({ url: 'u', item, picked: false })

describe('rowState·toPinRequest', () => {
  it('짝이 있으면 찍을 수 있고, 첫 장소를 search 핀으로 보낸다', () => {
    const r = row({ index: 0, status: 'ok', result: { provider: 'google', matches: [place], needs_search_query: false } })
    expect(rowState(r)).toBe('found')
    expect(toPinRequest(r)).toEqual({ source: 'search', ...place })
  })
  it('이미 있으면 already, 짝이 없으면 oneByOne, 오류면 failed, 응답 전이면 checking', () => {
    expect(rowState(row({ index: 0, status: 'ok', already_pinned_pin_id: 'p', result: { provider: 'kakao', matches: [place], needs_search_query: false } }))).toBe('already')
    expect(rowState(row({ index: 0, status: 'ok', result: { provider: 'kakao', kakao_place_id: 'kakao:1', matches: [], needs_search_query: true } }))).toBe('oneByOne')
    expect(rowState(row({ index: 0, status: 'error', error_code: 'LINK_UNRESOLVED' }))).toBe('failed')
    expect(rowState(row())).toBe('checking')
  })
})
