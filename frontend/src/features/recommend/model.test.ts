import { describe, expect, it } from 'vitest'

import { ApiError } from '@/api'

import {
  evidenceLabel,
  kmInputToM,
  evidenceLimitMessage,
  fulfillmentLine,
  groupEvidence,
  hasExcluded,
  memberConditions,
  noResultsExternalSearch,
  notEnforcedNote,
  radiusOptions,
  tagAuthor,
  readinessRadiusM,
  recommendAreaNote,
  rerunErrorMessage,
  runErrorMessage,
  summaryToRun,
  widenAtLimit,
  widenLine,
  toReadinessCards,
  type CandidateDto,
  visibleConditionCount,
  runHistoryLine,
  type EvidenceLineDto,
  type RecommendRunDto,
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

  it('후보를 빼지 않는 꼭 줄(filters_candidates=false)은 「꼭」이 아니다 — 피함은 순위를 낮춤, 원함은 선호 태그(#1260)', () => {
    const g = groupEvidence([
      line('붐빔', 'required', { enforced: true, filters_candidates: true, wants: false, fact_label: '붐비는 대형' }),
      line('매운맛', 'required', { enforced: true, filters_candidates: false, wants: false, fact_label: '매운맛 전문' }),
      line('넓은 곳', 'required', { enforced: true, filters_candidates: false, wants: true, fact_label: '넓은 곳' }),
      line('구버전', 'required', { wants: false, fact_label: '한식' }),
    ])
    expect(g.required.map((l) => l.id)).toEqual(['붐빔', '구버전'])
    expect(g.lowered.map((l) => l.id)).toEqual(['매운맛'])
    expect(g.preferred.map((l) => l.id)).toEqual(['넓은 곳'])
    expect(evidenceLabel(g.lowered[0])).toBe('매운맛 전문 피하기')
    expect(evidenceLabel(g.required[0])).toBe('붐비는 대형 제외')
    expect(evidenceLabel(g.required[1])).toBe('한식 제외') // 필드가 없으면(구버전 서버) 지금처럼
    expect(visibleConditionCount([g.required, g.lowered, g.preferred].flat())).toBe(4)
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

describe('추천 실패 문구(#1385, #1386 리뷰)', () => {
  const IN_PROGRESS = '아직 추천을 찾고 있어요. 잠시 뒤 다시 눌러 주세요'

  it('「추천받기」 시작: 처리 중만 따로, 그 밖은 「추천 장소를 찾지 못했어요」', () => {
    expect(runErrorMessage(err('REQUEST_IN_PROGRESS'))).toBe(IN_PROGRESS)
    expect(runErrorMessage(err('VALIDATION_ERROR'))).toBe('추천 장소를 찾지 못했어요')
    expect(runErrorMessage(new Error('network'))).toBe('추천 장소를 찾지 못했어요')
  })

  it('다시 추천·넓히기: 결과가 남아 있어 예전 문구, 넓히기 상한과 처리 중은 따로', () => {
    expect(rerunErrorMessage(err('WIDEN_LIMIT'))).toBe('더 넓히면 여행지를 벗어나요. 조건을 고치거나 직접 찍어 보세요')
    expect(rerunErrorMessage(err('REQUEST_IN_PROGRESS'))).toBe(IN_PROGRESS)
    expect(rerunErrorMessage(err('INTERNAL'))).toBe('추천을 끝내지 못했어요. 잠시 뒤 다시 눌러 주세요')
  })
})

describe('추천 반경은 서버 m 값만 쓴다(#1468)', () => {
  // 입력 값은 임의다 — 화면이 서버 값을 그대로 옮기는지만 본다(정책 값은 docs/constraints.md).
  const run = (over: Partial<RecommendRunDto>): RecommendRunDto => ({ id: 'r', map_id: 'm', category: '음식점', status: 'done', attempt_no: 1, ...over })

  it('넓히기 확인 창: 지금 → 넓힌 뒤 반경을 km로, 모르는 쪽 숫자는 빼고, 도보 분·「핀 주변」은 없다', () => {
    expect(widenLine(run({ default_radius_m: 2500, next_default_radius_m: 3500 }))).toBe('추천받은 지도 가운데 반경 2.5km에서 3.5km로')
    expect(widenLine(run({ next_default_radius_m: 3500 }))).toBe('추천받은 지도 가운데 반경을 3.5km로')
    expect(widenLine(run({}))).toBe('추천받은 지도 가운데 기본 반경을 한 단계 더')
  })

  it('상한은 서버가 next 를 null 로 내렸을 때만이다. 칸이 없으면(구버전 서버) 누를 수 있다', () => {
    expect(widenAtLimit(run({ default_radius_m: 4200, next_default_radius_m: null }))).toBe(true)
    expect(widenAtLimit(run({ default_radius_m: 4200, next_default_radius_m: 5200 }))).toBe(false)
    expect(widenAtLimit(run({}))).toBe(false)
  })

  it('「지난 추천」에서 연 run 도 반경 두 칸을 그대로 갖는다', () => {
    const summary: RunSummaryDto = { id: 'r', map_id: 'm', category: '카페', status: 'done', attempt_no: 2, created_at: '2026-11-01T00:00:00Z', candidate_count: 3, published_count: 0, default_radius_m: 4200, next_default_radius_m: null }
    expect(summaryToRun(summary)).toMatchObject({ default_radius_m: 4200, next_default_radius_m: null })
    expect(widenAtLimit(summaryToRun(summary))).toBe(true)
  })

  it('찾는 범위는 고른 카테고리의 readiness radius_m 이다. 없으면 null 이고 문구에 숫자가 없다', () => {
    const map = { 음식점: { radius_m: 2500 }, 카페: {} }
    expect(readinessRadiusM(map, '음식점')).toBe(2500)
    expect(readinessRadiusM(map, '카페')).toBeNull()
    expect(readinessRadiusM(map, null)).toBeNull()
    expect(readinessRadiusM(undefined, '음식점')).toBeNull()
    expect(recommendAreaNote(2500)).toBe('지도 가운데 반경 2.5km 안에서 찾아요')
    expect(recommendAreaNote(null)).not.toMatch(/\d/)
  })
})

describe('「찾는 범위」 반경 고르기(#1416)', () => {
  // 입력 값은 임의다 — 하한·상한·기본은 서버 값을 그대로 옮기는지만 본다.
  const r = { ready: true, answered_count: 1, required_count: 1, radius_m: 2500, radius_min_m: 1500, radius_max_m: 4200 }

  it('하한부터 상한까지 1km 간격에 기본값과 상한을 넣는다. 하한·상한이 없으면 빈 목록', () => {
    expect(radiusOptions(r)).toEqual([1500, 2500, 3500, 4200])
    expect(radiusOptions({ ...r, radius_min_m: undefined })).toEqual([])
    expect(radiusOptions(undefined)).toEqual([])
  })

  it('고른 값이 하한·상한 안이면 그 값, 밖이거나 안 골랐으면 기본값', () => {
    expect(readinessRadiusM({ 음식점: r }, '음식점', 3500)).toBe(3500)
    expect(readinessRadiusM({ 음식점: r }, '음식점', 9000)).toBe(2500)
    expect(readinessRadiusM({ 음식점: r }, '음식점')).toBe(2500)
  })
})

describe('「찾는 범위」 km 칸(#1416)', () => {
  it('km를 m로, 100m 단위로 반올림. 쉼표도 소수점. 범위 밖·숫자 아님은 null', () => {
    expect(kmInputToM('3.5', 2000, 5000, 100)).toBe(3500)
    expect(kmInputToM('3,25', 2000, 5000, 100)).toBe(3300)
    expect(kmInputToM('2', 2000, 5000, 100)).toBe(2000)
    expect(kmInputToM('5.1', 2000, 5000, 100)).toBeNull()
    expect(kmInputToM('', 2000, 5000, 100)).toBeNull()
    expect(kmInputToM('삼', 2000, 5000, 100)).toBeNull()
  })
})

describe('합친 태그 칩의 쓴 사람 — 첫 줄 이름만 쓰면 남의 이름 옆에 내 × 가 붙는다', () => {
  const by = (name: string, mine = false) =>
    line(name, 'preferred', { author_display_name: name, author_id: mine ? 'me' : name, permissions: { can_disable: mine } as EvidenceLineDto['permissions'] })
  it('내 줄만이면 내 이름과 id(「(나)」가 붙는다)', () => {
    expect(tagAuthor([by('준영', true)])).toEqual({ author_display_name: '준영', author_id: 'me' })
  })
  it('남 한 사람이면 그 이름, (나) 없음', () => {
    expect(tagAuthor([by('민재')])).toEqual({ author_display_name: '민재', author_id: '' })
  })
  it('여럿이면 나를 앞에 두고 나머지는 수로', () => {
    expect(tagAuthor([by('민재'), by('준영', true), by('강준')]).author_display_name).toBe('나 외 2명')
    expect(tagAuthor([by('민재'), by('강준'), by('민재')]).author_display_name).toBe('민재 외 1명')
  })
})
