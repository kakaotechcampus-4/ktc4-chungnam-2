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
    if (err.code === 'RECOMMEND_FAILED') return '추천을 찾지 못했어요. 조건이 까다로워서가 아니에요 — 남긴 것은 그대로 있어요'
  }
  return '추천을 시작하지 못했어요'
}
