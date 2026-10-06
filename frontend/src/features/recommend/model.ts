import type { components } from '@pingo/contracts/src/types/api'

import { ApiError } from '@/api'

export type RecommendCategory = components['schemas']['RecommendCategory']
export type ReadinessDto = components['schemas']['Readiness']
export type RecommendRunDto = components['schemas']['RecommendRun']
export type EvidenceLineDto = components['schemas']['EvidenceLine']
export type EvidencePatchRequest = components['schemas']['EvidencePatchRequest']
export type RegionDto = components['schemas']['Region']
export type RecommendResultDto = components['schemas']['RecommendResult']
export type CandidateDto = components['schemas']['Candidate']

/** AI 추천 대상 카테고리(#145 — 숙소는 추천 대상이 아니다). 순서는 화면 순서. */
export const RECOMMEND_CATEGORIES: RecommendCategory[] = ['음식점', '카페', '관광지']

export type ReadinessCard = { category: RecommendCategory; ready: boolean; answered: number; required: number }

export function toReadinessCards(map: Partial<Record<RecommendCategory, ReadinessDto>>): ReadinessCard[] {
  return RECOMMEND_CATEGORIES.map((category) => {
    const r = map[category]
    return { category, ready: r?.ready ?? false, answered: r?.answered_count ?? 0, required: r?.required_count ?? 0 }
  })
}

/**
 * 근거 줄 하나를 화면 말로. 서버가 사유를 해석한 방향(wants)을 같이 보여 줘야 틀렸을 때 사람이 뺄 수 있다(#228).
 * fact_label 이 없으면(해석 못 한 사유) 원문을 그대로 쓴다.
 */
export function evidenceLabel(line: EvidenceLineDto): string {
  if (!line.fact_label) return line.text
  if (line.wants === false) return `${line.fact_label} 제외`
  if (line.wants === true) return `${line.fact_label} 선호`
  return line.fact_label
}

/** 근거 확인 화면의 세 구역(최종기획안 5-5). 꼭 = 구성원별 줄, 선호 = 해시태그로 합침, 참고 = 원문 인용. */
export function groupEvidence(lines: EvidenceLineDto[]) {
  const active = lines.filter((l) => l.is_active)
  return {
    required: active.filter((l) => l.badge === 'required'),
    preferred: active.filter((l) => l.badge === 'preferred'),
    reference: active.filter((l) => l.badge === 'reference'),
  }
}

/** docs/errors.md — run 시작·실행 실패 문구. */
export function runErrorMessage(err: unknown): string {
  if (err instanceof ApiError) {
    if (err.code === 'NOT_READY') return '아직 의견이 모자라요. 핀에 의견이 더 모이면 다시 눌러 주세요'
    if (err.code === 'RETRY_LIMIT') return '5번까지만 찾습니다'
    if (err.code === 'WIDEN_LIMIT') return '더 넓히면 여행지를 벗어나요. 근거를 고치거나 직접 찍어 보세요'
    if (err.code === 'RECOMMEND_FAILED') return '추천을 찾지 못했어요. 조건이 까다로워서가 아니에요 — 남긴 것은 그대로 있어요'
  }
  return '추천을 시작하지 못했어요'
}

export type FunnelRow = RecommendResultDto['funnel'][number]

/** 결과가 0곳일 때(404 NO_RESULTS) 서버가 detail 에 깔때기를 실어 보낸다 — "무엇을 시도했는지 화면에 남긴다"(가드레일 10). */
export function noResultsFunnel(err: unknown): FunnelRow[] | null {
  if (!(err instanceof ApiError) || err.code !== 'NO_RESULTS') return null
  return (err.detail?.funnel as FunnelRow[] | undefined) ?? []
}

export const RETRY_MAX = 5

export type CheckView = { label: string; tone: 'pass' | 'check' | 'fail' }

/** 조건별 충족 체크(가드레일 5). 모름(needs_check)은 통과가 아니라 "확인 필요"로 따로 보인다. */
export function toChecks(c: CandidateDto): CheckView[] {
  return c.checks.map((k) => ({ label: k.label, tone: !k.passed ? 'fail' : k.needs_check ? 'check' : 'pass' }))
}

/**
 * 구성원 충족 한 줄(Figma 구성원 의견 표시 원칙) — "조건을 건 A·B 모두 통과 · C·D는 건 조건 없음".
 * by_member 에 없는 구성원은 조건을 걸지 않은 사람이다.
 */
export function fulfillmentLine(c: CandidateDto, members: { userId: string; name: string; isMe: boolean }[]): string {
  const by = c.member_fulfillment.by_member ?? []
  const nameOf = (id: string, fallback?: string) => {
    const m = members.find((x) => x.userId === id)
    return m ? `${m.name}${m.isMe ? ' (나)' : ''}` : (fallback ?? '구성원')
  }
  const ok = by.filter((b) => b.satisfied).map((b) => nameOf(b.user_id, b.display_name))
  const no = by.filter((b) => !b.satisfied).map((b) => nameOf(b.user_id, b.display_name))
  const none = members.filter((m) => !by.some((b) => b.user_id === m.userId)).map((m) => nameOf(m.userId))
  return [
    ok.length && (no.length ? `${ok.join('·')} 통과` : `조건을 건 ${ok.join('·')} 모두 통과`),
    no.length && `${no.join('·')} 미충족`,
    none.length && `${none.join('·')}은(는) 건 조건 없음`,
  ]
    .filter(Boolean)
    .join(' · ')
}
