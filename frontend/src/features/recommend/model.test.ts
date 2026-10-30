import { describe, expect, it } from 'vitest'

import { ApiError } from '@/api'

import {
  evidenceLimitMessage,
  groupEvidence,
  noResultsExternalSearch,
  notEnforcedNote,
  toReadinessCards,
  type EvidenceLineDto,
} from './model'

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

const line = (id: string, badge: EvidenceLineDto['badge'], extra: Partial<EvidenceLineDto> = {}): EvidenceLineDto => ({
  id,
  author_id: 'u_1',
  text: id,
  badge,
  is_active: true,
  permissions: { can_disable: true },
  ...extra,
})

describe('추천이 쓰지 않는 근거 줄(#742)', () => {
  it('enforced=false 인 꼭·선호 줄은 꼭·선호 구역에 넣지 않고 따로 모은다. 없으면 쓰이는 줄(구버전 서버)', () => {
    const g = groupEvidence([
      line('매운맛', 'required', { enforced: true }),
      line('구버전', 'required'),
      line('땅콩 알레르기', 'required', { enforced: false, not_enforced_reason: 'no_key' }),
      line('국물', 'preferred', { enforced: false, not_enforced_reason: 'no_key' }),
      line('끈 줄', 'required', { enforced: false, is_active: false }),
    ])
    expect(g.required.map((l) => l.id)).toEqual(['매운맛', '구버전'])
    expect(g.preferred).toEqual([])
    expect(g.unused.map((l) => l.id)).toEqual(['땅콩 알레르기', '국물'])
  })

  it('이유별 안내 한 줄', () => {
    expect(notEnforcedNote(line('a', 'required', { not_enforced_reason: 'no_key' }))).toBe('걸러지지 않아요. 가게에 직접 확인해 주세요')
    expect(notEnforcedNote(line('a', 'required', { not_enforced_reason: 'off_season' }))).toBe('이번 여행 기간에는 해당 없어요')
    expect(notEnforcedNote(line('a', 'required', { not_enforced_reason: 'no_direction' }))).toBe('이번 추천에 쓰이지 않아요')
    expect(notEnforcedNote(line('a', 'required', { not_enforced_reason: 'not_for_category' }))).toBe('이번 추천에 쓰이지 않아요')
  })
})

describe('「+」 직접 추가 상한(#720)', () => {
  it('숫자는 응답 detail.limit 에서 가져오고, 다른 오류는 null', () => {
    const limitErr = (detail?: Record<string, unknown>) => new ApiError(409, { code: 'EVIDENCE_LIMIT', message: 'x', detail })
    expect(evidenceLimitMessage(limitErr({ limit: 10, used: 10 }))).toBe('직접 추가는 10개까지예요')
    expect(evidenceLimitMessage(limitErr())).toBe('직접 추가는 더 할 수 없어요')
    expect(evidenceLimitMessage(err('VALIDATION_ERROR'))).toBeNull()
  })
})
