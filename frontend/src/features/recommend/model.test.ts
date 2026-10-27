import { describe, expect, it } from 'vitest'

import { ApiError } from '@/api'

import { noResultsExternalSearch, toReadinessCards } from './model'

const search = { query: '춘천 한식', url: 'https://map.kakao.com/link/search/춘천 한식' }
const err = (code: string, detail?: Record<string, unknown>) => new ApiError(404, { code, message: code, detail })

describe('카카오맵에서 더 찾아보기(#798)', () => {
  it('결과 0곳이면 detail 의 링크를 꺼내고, 다른 오류나 구버전 서버는 없다', () => {
    expect(noResultsExternalSearch(err('NO_RESULTS', { funnel: [], external_search: search }))).toEqual(search)
    expect(noResultsExternalSearch(err('NO_RESULTS', { funnel: [] }))).toBeUndefined()
    expect(noResultsExternalSearch(err('RECOMMEND_FAILED', { external_search: search }))).toBeUndefined()
    expect(noResultsExternalSearch(new Error('x'))).toBeUndefined()
  })

  it('추천 준비는 서버가 준 링크를 카테고리 카드에 그대로 싣는다', () => {
    const cards = toReadinessCards({
      음식점: { ready: true, answered_count: 1, required_count: 1, curated_nearby: 0, external_search: search },
      카페: { ready: true, answered_count: 1, required_count: 1, curated_nearby: 5 },
    })
    expect(cards.find((c) => c.category === '음식점')?.externalSearch).toEqual(search)
    expect(cards.find((c) => c.category === '카페')?.externalSearch).toBeUndefined()
    expect(cards.find((c) => c.category === '관광지')?.externalSearch).toBeUndefined()
  })
})
