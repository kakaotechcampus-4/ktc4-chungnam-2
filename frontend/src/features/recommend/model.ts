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

/**
 * AI가 고른 장소의 근거(가드레일 5) — 후보(Candidate)와 그 후보를 지도에 올린 핀(Pin)이 같은 값을 갖는다.
 * 후보 카드와 핀 상세가 같은 함수·부품(Evidence.tsx)으로 그린다(#1032). 핀에서는 AI 핀이 아니면 없다.
 */
export type AiEvidence = {
  reason?: string
  checks?: components['schemas']['Check'][]
  member_fulfillment?: components['schemas']['MemberFulfillment']
  place_source?: components['schemas']['PlaceSource']
}

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

/** 준비 화면이 보고 있는 카테고리 — 고른 것이 준비됐으면 그것, 아니면 첫 준비 카테고리. 광고 영역도 이 값을 쓴다. */
export function chosenCategory(cards: ReadinessCard[], picked: RecommendCategory | undefined): RecommendCategory | null {
  if (picked && cards.find((c) => c.category === picked)?.ready) return picked
  return cards.find((c) => c.ready)?.category ?? null
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

/** 같은 태그는 하나로 합친다. all = 그 태그의 줄 전부, mine = 그중 내 줄(뺄 수 있는 줄). */
export function mergeTags(lines: EvidenceLineDto[]) {
  const tags = new Map<string, { all: EvidenceLineDto[]; mine: EvidenceLineDto[] }>()
  for (const line of lines) {
    const tag = evidenceLabel(line)
    const entry = tags.get(tag) ?? { all: [], mine: [] }
    entry.all.push(line)
    if (line.permissions.can_disable) entry.mine.push(line)
    tags.set(tag, entry)
  }
  return [...tags].map(([tag, v]) => ({ tag, ...v }))
}

/** 화면에 보이는 조건 수 — 꼭은 줄마다, 선호는 같은 태그끼리 합쳐 센다(EvidenceGroups와 같은 묶음, #1143). */
export function visibleConditionCount(lines: EvidenceLineDto[]): number {
  const g = groupEvidence(lines)
  return g.required.length + mergeTags(g.preferred).length
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

/** 반경(m)을 화면 글자로. 화면은 표시용 km 변환만 하고 반경 숫자는 서버 값만 쓴다(#733, #1468). */
export const radiusKm = (m: number) => `${m / 1000}km`

/**
 * AI 추천이 찾는 범위(m) — 사람이 「찾는 범위」에서 고른 반경, 안 골랐으면 고른 카테고리의 기본 반경(`Readiness.radius_m`, #1385).
 * 고른 값이 서버가 준 하한·상한 밖이면 기본으로 돌아간다. 지도 원·크레딧 확인 창·run 생성이 같은 값을 쓴다(#1416).
 * 값이 없으면(구버전 서버, 카테고리를 아직 못 고름) null — 원을 그리지 않고 숫자 없이 알린다. 숫자를 지어내지 않는다(#1468).
 */
export function readinessRadiusM(
  map: Partial<Record<RecommendCategory, ReadinessDto>> | undefined,
  category: RecommendCategory | null,
  picked?: number,
): number | null {
  const r = category ? map?.[category] : undefined
  if (picked && r?.radius_min_m && r.radius_max_m && picked >= r.radius_min_m && picked <= r.radius_max_m) return picked
  return r?.radius_m || null
}

/** 「찾는 범위」 칩 간격(m). 화면이 고르는 단위일 뿐이고 하한·상한·기본값은 서버 값이다(#1416). */
const RADIUS_PICK_STEP_M = 1000

/** 「찾는 범위」에서 고를 수 있는 반경들 — 서버가 준 하한부터 상한까지 1km 간격, 기본값은 늘 들어간다. 하한·상한이 없으면(구버전 서버) 빈 목록이다. */
export function radiusOptions(r: ReadinessDto | undefined): number[] {
  if (!r?.radius_min_m || !r.radius_max_m) return []
  const out = new Set<number>()
  for (let m = r.radius_min_m; m <= r.radius_max_m; m += RADIUS_PICK_STEP_M) out.add(m)
  out.add(r.radius_max_m)
  if (r.radius_m) out.add(r.radius_m)
  return [...out].sort((a, b) => a - b)
}

/** 확인 창에 보이는 범위 한 줄. */
export const recommendAreaNote = (radiusM: number | null) =>
  radiusM ? `지도 가운데 반경 ${radiusKm(radiusM)} 안에서 찾아요` : '보이는 지도 가운데 주변에서 찾아요'

/** 넓히기 상한 안내 — 409 `WIDEN_LIMIT` 토스트와, 서버가 상한이라고 미리 알려 준 「반경 넓히기」 옆 이유가 같은 말이다. */
export const WIDEN_LIMIT_MESSAGE = '더 넓히면 여행지를 벗어나요. 조건을 고치거나 직접 찍어 보세요'

/** 이미 상한이라 넓힐 수 없다 — 서버가 `next_default_radius_m: null`을 내렸을 때만(#1370). 칸이 없으면(구버전 서버) 누른 뒤 409로 안다. */
export const widenAtLimit = (run: RecommendRunDto) => run.next_default_radius_m === null

/**
 * 「반경 넓히기」 확인 창의 「넓혀요」 한 줄 — 지금 반경과 넓힌 뒤 반경은 서버 값이다(#1370, #1468).
 * 다시 추천·넓히기는 추천받을 때의 지도 가운데에서 찾는다(지금 보이는 가운데가 아니다). 모르는 쪽 숫자는 빼고 말한다.
 */
export function widenLine(run: RecommendRunDto): string {
  const now = run.default_radius_m
  const next = run.next_default_radius_m
  if (now != null && next != null) return `추천받은 지도 가운데 반경 ${radiusKm(now)}에서 ${radiusKm(next)}로`
  if (next != null) return `추천받은 지도 가운데 반경을 ${radiusKm(next)}로`
  return '추천받은 지도 가운데 기본 반경을 한 단계 더'
}

/**
 * 서버가 같은 요청을 아직 처리 중이다(409 `REQUEST_IN_PROGRESS`) — 기다려도 안 끝나 멈췄을 때. 실패가 아니다:
 * 서버가 그 뒤에 추천을 끝내고 크레딧을 쓸 수 있다(#1386 리뷰).
 */
const IN_PROGRESS_MESSAGE = '아직 추천을 찾고 있어요. 잠시 뒤 다시 눌러 주세요'
const inProgress = (err: unknown) => err instanceof ApiError && err.code === 'REQUEST_IN_PROGRESS'

/**
 * docs/errors.md — 「○○ 추천받기」(run 시작) 실패 문구. 사용자 결정(2026-11-04, #1385)으로 실패는 한 줄이다.
 * 처리 중만 따로 말한다.
 */
export function runErrorMessage(err: unknown): string {
  return inProgress(err) ? IN_PROGRESS_MESSAGE : '추천 장소를 찾지 못했어요'
}

/**
 * 다시 추천·반경 넓히기·다시 시도 실패 문구(토스트). 이전 결과가 화면에 남아 있어 「찾지 못했어요」가 결과 옆에 서면 어색하다 —
 * 예전 문구로 남긴다(#1386 리뷰, 사용자 결정 2026-11-05). 크레딧을 쓰지 않는 실행이라 크레딧 안내는 없다.
 * 넓히기 상한(`WIDEN_LIMIT`)은 넓히기 버튼이 하는 일이라 다른 길(조건 고치기·직접 찍기)을 알린다.
 */
export function rerunErrorMessage(err: unknown): string {
  if (err instanceof ApiError && err.code === 'WIDEN_LIMIT') return WIDEN_LIMIT_MESSAGE
  return inProgress(err) ? IN_PROGRESS_MESSAGE : '추천을 끝내지 못했어요. 잠시 뒤 다시 눌러 주세요'
}

export type FunnelRow = RecommendResultDto['funnel'][number]

/** 반경 안 후보가 「이미 제안·거절됨」으로 빠졌는가. 단계는 라벨 글자가 아니라 서버 key로 찾는다(#751·#1142). key가 없으면 false. */
export const hasExcluded = (funnel: FunnelRow[]) => funnel.some((f) => f.key === 'excluded' && f.removed_count > 0)

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

const PROVIDER: Record<string, string> = { kakao: '카카오맵', naver: '네이버지도', google: '구글맵', permit: '인허가 공공데이터', tourapi: '한국관광공사' }

/**
 * 출처는 항상 붙는다(가드레일 5). 장소는 자체 DB에서만 오므로(#53) 제공처를 모르면 「확인 안 됨」 대신 그 사실을 적는다.
 * 모르는 제공처 코드가 오면 코드를 그대로 보인다 — 지어내지 않는다(#406).
 */
export function sourceLabel(e: AiEvidence): string {
  const p = e.place_source?.provider
  return (p && PROVIDER[p]) ?? p ?? '핑고 장소 정보'
}

export type CheckView = { label: string; tone: 'pass' | 'check' | 'fail' }

/** 조건별 충족 체크(가드레일 5). 모름(needs_check)은 통과가 아니라 "확인 필요"로 따로 보인다. */
export function toChecks(e: AiEvidence): CheckView[] {
  return (e.checks ?? []).map((k) => ({ label: k.label, tone: !k.passed ? 'fail' : k.needs_check ? 'check' : 'pass' }))
}

type MemberRef = { userId: string; name: string; isMe: boolean }
type ByMember = NonNullable<components['schemas']['MemberFulfillment']['by_member']>[number]

const nameIn = (members: MemberRef[]) => (id: string, fallback?: string) => {
  const m = members.find((x) => x.userId === id)
  return m ? `${m.name}${m.isMe ? ' (나)' : ''}` : (fallback ?? '구성원')
}

const TONE_ORDER = { fail: 0, check: 1, pass: 2 } as const

/**
 * 구성원별 조건 상태(#796). conditions 가 없으면(구버전 서버) 빠진다 — 그 구성원은 satisfied 만 쓴다.
 * 이름은 서버의 fact_label 이고, 없으면 키를 그대로 보인다(지어내지 않는다, #406). 못 맞춘 것 → 확인 필요 → 맞춘 것 순.
 */
export function memberConditions(e: AiEvidence, members: MemberRef[]) {
  const nameOf = nameIn(members)
  return (e.member_fulfillment?.by_member ?? [])
    .filter((b): b is ByMember & { conditions: NonNullable<ByMember['conditions']> } => !!b.conditions?.length)
    .map((b) => {
      const checks: CheckView[] = b.conditions
        .map((k) => ({
          label: k.fact_label || k.fact_key,
          tone: k.status === 'met' ? ('pass' as const) : k.status === 'unmet' ? ('fail' as const) : ('check' as const),
        }))
        .sort((x, y) => TONE_ORDER[x.tone] - TONE_ORDER[y.tone])
      return { userId: b.user_id, name: nameOf(b.user_id, b.display_name), met: checks.filter((k) => k.tone === 'pass').length, checks }
    })
}

/**
 * 구성원 충족 한 줄(Figma 구성원 의견 표시 원칙) — "조건을 건 A·B 모두 통과 · C·D는 건 조건 없음".
 * by_member 에 없는 구성원은 조건을 걸지 않은 사람이다. 조건별 상태가 오면 그 구성원은 「A 조건 2/3 충족」으로 쓴다(#796).
 */
export function fulfillmentLine(e: AiEvidence, members: MemberRef[]): string {
  const by = e.member_fulfillment?.by_member ?? []
  const nameOf = nameIn(members)
  const detailed = memberConditions(e, members)
  const plain = by.filter((b) => !detailed.some((d) => d.userId === b.user_id))
  const ok = plain.filter((b) => b.satisfied).map((b) => nameOf(b.user_id, b.display_name))
  const no = plain.filter((b) => !b.satisfied).map((b) => nameOf(b.user_id, b.display_name))
  const none = members.filter((m) => !by.some((b) => b.user_id === m.userId)).map((m) => nameOf(m.userId))
  return [
    ...detailed.map((d) => `${d.name} 조건 ${d.met}/${d.checks.length} 충족`),
    ok.length && (no.length || detailed.length ? `${ok.join('·')} 통과` : `조건을 건 ${ok.join('·')} 모두 통과`),
    no.length && `${no.join('·')} 미충족`,
    none.length && `${none.join('·')}${josa(none[none.length - 1], '은', '는')} 건 조건 없음`,
  ]
    .filter(Boolean)
    .join(' · ')
}

/**
 * 지난 추천 한 줄(#482). 결과는 마지막 시도의 후보만 남아 있다(api-spec GET /maps/{mapId}/runs).
 * 누르면 이 run 을 다시 연다 — 목록 항목이 run 의 필수 칸을 다 갖고 있어 그대로 run 으로 쓴다.
 */
export function runHistoryLine(r: RunSummaryDto): string {
  if (r.status === 'failed') return '끝내지 못했어요'
  if (r.status !== 'done') return '찾는 중'
  if (r.candidate_count === 0) return '찾은 곳 없음'
  return r.published_count > 0 ? `${r.candidate_count}곳 찾음 · 지도에 올림 ${r.published_count}곳` : `${r.candidate_count}곳 찾음`
}

export const summaryToRun = (r: RunSummaryDto): RecommendRunDto => ({
  id: r.id,
  map_id: r.map_id,
  category: r.category,
  status: r.status,
  attempt_no: r.attempt_no,
  // 「지난 추천」에서 연 run 도 반경 넓히기 확인 창이 서버 반경을 보인다(#1370).
  default_radius_m: r.default_radius_m,
  next_default_radius_m: r.next_default_radius_m,
})
