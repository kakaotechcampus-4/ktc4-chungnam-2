import { describe, expect, it } from 'vitest'

import { ApiError } from '@/api'

import {
  evidenceLimitMessage,
  fulfillmentLine,
  groupEvidence,
  hasExcluded,
  memberConditions,
  noResultsExternalSearch,
  notEnforcedNote,
  toReadinessCards,
  type CandidateDto,
  visibleConditionCount,
  runHistoryLine,
  type EvidenceLineDto,
  type RunSummaryDto,
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

describe('「조건 N개」는 화면에 보이는 조건 수(#1143)', () => {
  const pref = (id: string) => line(id, 'preferred', { fact_label: '양식', wants: true })
  it('같은 키·방향 두 줄은 1개, 다른 키 두 줄은 2개', () => {
    expect(visibleConditionCount([pref('a'), pref('b')])).toBe(1)
    expect(visibleConditionCount([pref('a'), line('b', 'preferred', { fact_label: '국물', wants: true })])).toBe(2)
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

describe('구성원 조건별 충족(#796)', () => {
  const members = [
    { userId: 'u1', name: '지우', isMe: true },
    { userId: 'u2', name: '민재', isMe: false },
    { userId: 'u3', name: '준영', isMe: false },
  ]
  const cand = (by: NonNullable<CandidateDto['member_fulfillment']['by_member']>) =>
    ({ member_fulfillment: { satisfied: 1, total: 2, by_member: by } }) as CandidateDto

  it('조건별 상태를 못 맞춘 것 → 확인 필요 → 맞춘 것 순으로 세고, 이름이 없으면 키를 그대로 쓴다', () => {
    const c = cand([
      {
        user_id: 'u1',
        satisfied: false,
        conditions: [
          { fact_key: 'spicy_focused', fact_label: '매운맛 전문', status: 'met' },
          { fact_key: 'parking_available', fact_label: null, status: 'needs_check' },
          { fact_key: 'quiet', fact_label: '조용함', status: 'unmet' },
        ],
      },
      { user_id: 'u2', satisfied: true },
    ])
    expect(memberConditions(c, members)).toEqual([
      {
        userId: 'u1',
        name: '지우 (나)',
        met: 1,
        checks: [
          { label: '조용함', tone: 'fail' },
          { label: 'parking_available', tone: 'check' },
          { label: '매운맛 전문', tone: 'pass' },
        ],
      },
    ])
    expect(fulfillmentLine(c, members)).toBe('지우 (나) 조건 1/3 충족 · 민재 통과 · 준영은 건 조건 없음')
  })

  it('conditions 가 없으면(구버전 서버) 지금 한 줄 그대로다', () => {
    const c = cand([{ user_id: 'u1', satisfied: true }, { user_id: 'u2', satisfied: true }])
    expect(memberConditions(c, members)).toEqual([])
    expect(fulfillmentLine(c, members)).toBe('조건을 건 지우 (나)·민재 모두 통과 · 준영은 건 조건 없음')
  })
})

describe('후보를 다 보여 준 뒤의 안내(#1142)', () => {
  it('excluded 단계가 0보다 크면 참, 0이거나 key가 없으면 거짓', () => {
    expect(hasExcluded([{ key: 'excluded', label: '이미 제안·거절됨', removed_count: 13 }])).toBe(true)
    expect(hasExcluded([{ key: 'excluded', label: '이미 제안·거절됨', removed_count: 0 }])).toBe(false)
    expect(hasExcluded([{ label: '이미 제안·거절됨', removed_count: 13 }])).toBe(false)
  })
})

describe('runHistoryLine (#482 지난 추천)', () => {
  const r = (over: Partial<RunSummaryDto>): RunSummaryDto => ({ id: 'r', map_id: 'm', category: '음식점', status: 'done', attempt_no: 1, created_at: '2026-11-01T00:00:00Z', candidate_count: 3, published_count: 0, ...over })
  it('끝난 추천은 찾은 수와 올린 수, 끝나지 않았으면 상태', () => {
    expect([r({}), r({ published_count: 1 }), r({ candidate_count: 0 }), r({ status: 'failed' }), r({ status: 'executing' })].map(runHistoryLine)).toEqual([
      '3곳 찾음',
      '3곳 찾음 · 지도에 올림 1곳',
      '찾은 곳 없음',
      '끝내지 못했어요',
      '찾는 중',
    ])
  })
})
