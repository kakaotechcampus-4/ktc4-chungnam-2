import { afterEach, describe, expect, it, vi } from 'vitest'

import { mergeRows, type ImportRow } from './model'
import type { Share } from './share'
import { clearImport, loadImport, saveImport } from './storage'

const share = (url: string, extra: Partial<Share> = {}): Share => ({ url, provider: 'naver', ...extra })
const place = { place_id: 'kakao:9', place_name: '우슬', lat: 36.32, lng: 127.42, category: '음식점' as const, address: '대전 중구 중앙로138번길 48', pinnable: false }

afterEach(() => {
  window.sessionStorage.clear()
  vi.restoreAllMocks()
})

describe('카톡 가져오기 목록 저장·복원(#1045)', () => {
  const rows: ImportRow[] = [
    { share: { ...share('https://naver.me/a', { name: '유소바 안국역점', address: '서울 종로구 창덕궁1길 32 1층' }), context: ['여기 어때'] }, picked: true, outcome: 'created' },
    {
      share: share('https://kko.to/b', { provider: 'kakao', name: '우슬' }),
      picked: true,
      choice: place,
      item: { index: 1, status: 'ok', result: { provider: 'kakao', matches: [], needs_search_query: true } },
    },
  ]

  it('되살리면 링크·공유 이름·주소·체크·고른 장소 id·찍음 결과가 같다', () => {
    saveImport('map_1', rows)
    const back = loadImport('map_1')
    expect(back).toEqual([
      { share: { url: 'https://naver.me/a', provider: 'naver', name: '유소바 안국역점', address: '서울 종로구 창덕궁1길 32 1층' }, picked: true, outcome: 'created' },
      { share: { url: 'https://kko.to/b', provider: 'kakao', name: '우슬' }, picked: true, choiceId: 'kakao:9' },
    ])
  })

  it('같이 온 말과 서버·카카오 응답(장소 이름·좌표·주소)은 저장하지 않는다', () => {
    saveImport('map_1', rows)
    const raw = window.sessionStorage.getItem('pingo.kakaoImport.v1.map_1') ?? ''
    for (const absent of ['여기 어때', '대전 중구 중앙로138번길 48', '36.32', 'needs_search_query', 'place_name']) expect(raw).not.toContain(absent)
  })

  it('지도마다 따로다 — 다른 지도의 목록이 섞이지 않고, 비우면 지운다', () => {
    saveImport('map_1', rows)
    saveImport('map_2', [rows[1]])
    expect(loadImport('map_2')).toHaveLength(1)
    clearImport('map_2')
    expect(loadImport('map_2')).toEqual([])
    expect(loadImport('map_1')).toHaveLength(2)
    clearImport()
    expect(loadImport('map_1')).toEqual([])
  })

  it('저장소가 막혀 있어도(예외) 저장 없이 동작한다', () => {
    vi.spyOn(Storage.prototype, 'setItem').mockImplementation(() => {
      throw new Error('QuotaExceeded')
    })
    vi.spyOn(Storage.prototype, 'getItem').mockImplementation(() => {
      throw new Error('SecurityError')
    })
    expect(() => saveImport('map_1', rows)).not.toThrow()
    expect(loadImport('map_1')).toEqual([])
  })
})

describe('대화 더하기(mergeRows)', () => {
  const base: ImportRow[] = [{ share: share('https://naver.me/a'), picked: false }, { share: share('https://naver.me/b'), picked: true, outcome: 'created' }]

  it('새 링크만 더하고, 같은 링크는 한 줄이다', () => {
    const r = mergeRows(base, [share('https://naver.me/b'), share('https://naver.me/c')])
    expect(r.rows.map((x) => x.share.url)).toEqual(['https://naver.me/a', 'https://naver.me/b', 'https://naver.me/c'])
    expect(r.added).toBe(1)
    expect(r.truncated).toBe(false)
  })

  it('앞서 이름을 못 읽은 링크를 이번에 읽었으면 그 힌트로 다시 확인한다(찍은 줄은 그대로)', () => {
    const r = mergeRows(base, [share('https://naver.me/a', { name: '왕비집', address: '서울 중구 명동8가길 26' }), share('https://naver.me/b', { name: '다른 이름', address: '서울 종로구 1길 1' })])
    expect(r.rows[0]).toEqual({ share: share('https://naver.me/a', { name: '왕비집', address: '서울 중구 명동8가길 26' }), picked: false })
    expect(r.rows[1]).toBe(base[1])
    expect(r.added).toBe(1)
  })

  it('상한은 누적 합계 기준이다 — 넘친 링크는 버리고 알린다', () => {
    const r = mergeRows(base, [share('https://naver.me/c'), share('https://naver.me/d')], 3)
    expect(r.rows).toHaveLength(3)
    expect(r.truncated).toBe(true)
  })
})
