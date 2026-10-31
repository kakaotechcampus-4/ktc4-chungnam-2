import type { components } from '@pingo/contracts/src/types/api'

import { ApiError } from '@/api'
import { josa } from '@/ui/josa'

export type RecommendCategory = components['schemas']['RecommendCategory']
export type ReadinessDto = components['schemas']['Readiness']
export type RecommendRunDto = components['schemas']['RecommendRun']
export type RunSummaryDto = components['schemas']['RunSummary']
export type EvidenceLineDto = components['schemas']['EvidenceLine']
export type EvidencePatchRequest = components['schemas']['EvidencePatchRequest']
export type RegionDto = components['schemas']['Region']
export type RecommendResultDto = components['schemas']['RecommendResult']
export type CandidateDto = components['schemas']['Candidate']
export type ExternalSearchDto = components['schemas']['ExternalSearch']

/** AI 추천 대상 카테고리(#145 — 숙소는 추천 대상이 아니다). 순서는 화면 순서. */
export const RECOMMEND_CATEGORIES: RecommendCategory[] = ['음식점', '카페', '관광지']

/** externalSearch 는 기본 지역 근처에 정예 장소가 없을 때만 서버가 준다(#798). 화면은 링크가 있는지만 본다. */
export type ReadinessCard = { category: RecommendCategory; ready: boolean; answered: number; required: number; externalSearch?: ExternalSearchDto }

export function toReadinessCards(map: Partial<Record<RecommendCategory, ReadinessDto>>): ReadinessCard[] {
  return RECOMMEND_CATEGORIES.map((category) => {
    const r = map[category]
    return {
      category,
      ready: r?.ready ?? false,
      answered: r?.answered_count ?? 0,
      required: r?.required_count ?? 0,
      externalSearch: r?.external_search,
    }
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

/**
 * 근거 확인 화면의 구역(최종기획안 5-5). 꼭 = 구성원별 줄, 선호 = 해시태그로 합침, 참고 = 원문 인용.
 * 꼭·선호 줄 중 추천이 쓰지 않는 줄(enforced=false)은 unused 로 따로 모은다 — 「꼭」으로 보이면 걸러질 거라고 믿는다(#742).
 * enforced 가 없으면 쓰이는 줄로 본다(구버전 서버).
 */
export function groupEvidence(lines: EvidenceLineDto[]) {
  const active = lines.filter((l) => l.is_active)
  const pick = (badge: EvidenceLineDto['badge'], enforced: boolean) =>
    active.filter((l) => l.badge === badge && (l.enforced !== false) === enforced)
  return {
    required: pick('required', true),
    preferred: pick('preferred', true),
    reference: active.filter((l) => l.badge === 'reference'),
    unused: [...pick('required', false), ...pick('preferred', false)],
  }
}

/** 추천이 쓰지 않는 줄의 이유 한 줄(docs/api-spec.yaml EvidenceLine.not_enforced_reason, #740). */
export function notEnforcedNote(line: EvidenceLineDto): string {
  if (line.not_enforced_reason === 'no_key') return '걸러지지 않아요. 가게에 직접 확인해 주세요' // 가드레일 8
  if (line.not_enforced_reason === 'off_season') return '이번 여행 기간에는 해당 없어요'
  return '이번 추천에 쓰이지 않아요'
}

/** 「+」 직접 추가 상한(409 EVIDENCE_LIMIT, #707). 숫자는 서버 detail.limit 만 쓴다. 다른 오류면 null. */
export function evidenceLimitMessage(err: unknown): string | null {
  if (!(err instanceof ApiError) || err.code !== 'EVIDENCE_LIMIT') return null
  const limit = err.detail?.limit
  return typeof limit === 'number' ? `직접 추가는 ${limit}개까지예요` : '직접 추가는 더 할 수 없어요'
}

/** docs/errors.md — run 시작·실행 실패 문구. */
export function runErrorMessage(err: unknown): string {
  if (err instanceof ApiError) {
    if (err.code === 'NOT_READY') return '아직 의견이 달린 핀이 없어요. 핀에 ♥나 반대 의견을 남기면 다시 눌러 주세요'
    if (err.code === 'RETRY_LIMIT') {
      const limit = typeof err.detail?.attempt_limit === 'number' ? err.detail.attempt_limit : DEFAULT_ATTEMPT_LIMIT
      return `${limit}번까지만 찾습니다`
    }
    if (err.code === 'WIDEN_LIMIT') return '더 넓히면 여행지를 벗어나요. 근거를 고치거나 직접 찍어 보세요'
    if (err.code === 'RECOMMEND_FAILED') return '추천을 끝내지 못했어요. 남긴 의견은 그대로 있고 횟수도 쓰지 않았어요. 잠시 뒤 다시 눌러 주세요'
    if (err.code === 'REQUEST_IN_PROGRESS') return '아직 추천을 찾고 있어요. 잠시 뒤 다시 눌러 주세요'
  }
  return '추천을 시작하지 못했어요'
}

export type FunnelRow = RecommendResultDto['funnel'][number]

/** 결과가 0곳일 때(404 NO_RESULTS) 서버가 detail 에 깔때기를 실어 보낸다 — "무엇을 시도했는지 화면에 남긴다"(가드레일 10). */
export function noResultsFunnel(err: unknown): FunnelRow[] | null {
  if (!(err instanceof ApiError) || err.code !== 'NO_RESULTS') return null
  return (err.detail?.funnel as FunnelRow[] | undefined) ?? []
}

/** 결과 0곳이면 detail 에 카카오맵 검색 링크도 온다(#798). 구버전 서버는 없다. */
export function noResultsExternalSearch(err: unknown): ExternalSearchDto | undefined {
  if (!(err instanceof ApiError) || err.code !== 'NO_RESULTS') return undefined
  return err.detail?.external_search as ExternalSearchDto | undefined
}

/** 0곳(404 NO_RESULTS)에도 그 결과에 쓴 조건 스냅숏이 detail 에 온다(#846). 구버전 서버는 없다. */
export function noResultsApplied(err: unknown): { lines?: EvidenceLineDto[]; none?: boolean } {
  if (!(err instanceof ApiError) || err.code !== 'NO_RESULTS') return {}
  return {
    lines: err.detail?.applied_evidence as EvidenceLineDto[] | undefined,
    none: err.detail?.no_applied_conditions as boolean | undefined,
  }
}

/** 추천 횟수 상한(#31, 지도 안 구성원 각자·카테고리 무관). 서버 값(attempt_limit)을 쓰고, 없으면(구버전 서버) 이 값. */
const DEFAULT_ATTEMPT_LIMIT = 10
export const attemptLimit = (run: RecommendRunDto) => run.attempt_limit ?? DEFAULT_ATTEMPT_LIMIT

/**
 * 이 지도에서 내가 쓴 추천 횟수(#31). 서버는 내 run 전체의 attempt_no 최댓값으로 센다(새 run 은 최댓값 + 1) —
 * 목록이 최근 요청순이라 최댓값을 직접 구한다. 상한은 서버 값(attempt_limit), 없으면 구버전 서버다.
 */
export function toAttempts(runs: RunSummaryDto[]) {
  const used = runs.reduce((max, r) => Math.max(max, r.attempt_no), 0)
  const limit = runs[0]?.attempt_limit ?? DEFAULT_ATTEMPT_LIMIT
  return { used, limit, left: Math.max(0, limit - used) }
}

/**
 * 원한 조건(wants=true 근거 줄)인데 추천한 곳 모두가 못 맞췄거나(passed=false) 모르는(needs_check) 조건의 이름.
 * 예: "곱창 먹고 싶어요"인데 반경 안에 곱창집이 없어 양식집만 나왔을 때 이유를 말해 주려고 쓴다.
 * 원하지 않는 조건·실격 조건은 보지 않는다 — 그쪽의 '확인 필요'는 "그런 곳이 없다"는 뜻이 아니다.
 */
export function missingWants(candidates: CandidateDto[], evidence: EvidenceLineDto[]): string[] {
  if (candidates.length === 0) return []
  const wanted = new Map<string, string>()
  for (const l of evidence) if (l.is_active && l.wants === true && l.fact_key) wanted.set(l.fact_key, l.fact_label ?? l.text)
  return [...wanted]
    .filter(([key]) =>
      candidates.every((c) => {
        const check = c.checks.find((k) => k.fact_key === key)
        return check && (!check.passed || check.needs_check)
      }),
    )
    .map(([, label]) => label)
}

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
    none.length && `${none.join('·')}${josa(none[none.length - 1], '은', '는')} 건 조건 없음`,
  ]
    .filter(Boolean)
    .join(' · ')
}
