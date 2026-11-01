import type { components } from '@pingo/contracts/src/types/api'

import { ApiError } from '@/api'
import { isPlaced, type Pin } from '@/features/map/model'
import { KAKAO_ROUTE_MAX, kakaoTrafficUrl, kakaoWalkUrl, type KakaoPoint, type RouteDrawing } from '@/features/shortlist/model'

export type CourseRunDto = components['schemas']['CourseRun']
export type CourseStepDto = components['schemas']['CourseStep']
export type CourseGoalDto = components['schemas']['CourseGoal']
export type CourseDayDto = components['schemas']['CourseDay']
export type CourseViolationDto = components['schemas']['CourseViolation']

/** 요청 한 줄의 글자 수 상한(api-spec CourseRequest.request_text). */
export const REQUEST_MAX = 100
/** 진행 중 조회 간격(ms). 이 시간마다 GET /course-runs/{id} 를 부른다. */
export const POLL_MS = 2000

export const isFinished = (run: Pick<CourseRunDto, 'status'> | undefined): boolean => run?.status === 'done' || run?.status === 'failed'

/** 요청 한 줄은 비어 있으면 보내지 않는다(선택 입력). */
export const requestBody = (text: string): { request_text?: string } => {
  const trimmed = text.trim()
  return trimmed ? { request_text: trimmed } : {}
}

/** 작업 기록의 「누가」 칩 — 색(tag-*)과 글자를 함께 쓴다. AI 파랑 · 코드 회색 · 사람 회색+사람 아이콘(주의 색은 조건 체크용이라 쓰지 않는다). */
export const BY: Record<CourseStepDto['by'], { label: string; tag: string }> = {
  ai: { label: 'AI', tag: 'tag-ai' },
  code: { label: '코드', tag: 'tag-neutral' },
  human: { label: '사람', tag: 'tag-neutral' },
}

/** 첫 줄 「이해」는 카드의 제목이 "이렇게 이해했어요"라서, 문장 앞에 같은 말이 오면 한 번만 보이게 뗀다. */
export function understandBody(text: string): string {
  return text.replace(/^이렇게 이해했어요\s*[:：]?\s*/, '')
}

export const GOAL_STATE = {
  met: { label: '지킴', tag: 'tag-good' },
  missed: { label: '못 지킴', tag: 'tag-bad' },
  unknown: { label: '확인할 수 없어요', tag: 'tag-neutral' },
} as const

export function goalState(goal: CourseGoalDto) {
  return goal.met === true ? GOAL_STATE.met : goal.met === false ? GOAL_STATE.missed : GOAL_STATE.unknown
}

export const VIOLATION_LABEL: Record<CourseViolationDto['kind'], string> = {
  closed: '쉬는 날',
  travel: '도보 상한',
  member: '구성원 조건',
}

/** 결과 한 줄. 문장은 서버가 아니라 outcome 값으로 정한다 — 시간 배정이 아니라 순서만 짠 코스다. */
export function outcomeText(outcome: NonNullable<CourseRunDto['outcome']>): string {
  switch (outcome) {
    case 'solved':
      return '코스를 짰어요'
    case 'solved_with_checks':
      return '코스를 짰어요. 영업 여부는 가게에 직접 확인해 주세요'
    case 'unresolved':
      return '코스를 짰지만 지키지 못한 조건이 남았어요'
    case 'timeout':
      return '시간이 다 돼서 지금까지 짠 코스예요'
  }
}

/** 실패 안내. 계약상 INTERRUPTED(서버 재시작·15분 초과)와 ENGINE_ERROR 는 같은 문구다. */
export const FAILURE_TEXT = '코스 짜기가 중간에 끊겼어요'

/**
 * 코스 요청이 실패했을 때의 안내. 코드가 아닌 HTTP 만으로 갈리지 않는다(docs/errors.md). 모르는 코드는 null 이라 호출부가 ErrorText 로 보인다.
 * 크레딧(402·게스트 403)은 여기서 말하지 않는다 — 버튼 자리의 CreditGate 가 보인다(#432).
 */
export function createErrorMessage(error: unknown): string | null {
  if (!(error instanceof ApiError)) return null
  switch (error.code) {
    case 'COURSE_NOT_ENOUGH_PLACES':
      return '확정 리스트에 위치를 아는 장소가 2곳 이상 있어야 코스를 짤 수 있어요'
    default:
      return null
  }
}

/** 409 COURSE_IN_PROGRESS 가 알려 주는, 이미 짜는 중인 run 의 id. */
export function inProgressRunId(error: unknown): string | null {
  if (!(error instanceof ApiError) || error.code !== 'COURSE_IN_PROGRESS') return null
  const id = error.detail?.course_run_id
  return typeof id === 'string' ? id : null
}

const ORDINALS = ['첫째', '둘째', '셋째', '넷째', '다섯째', '여섯째', '일곱째', '여덟째', '아홉째', '열째', '열한째', '열두째', '열셋째', '열넷째']

/** "첫째 날 · 10.3 (토)" — 시간은 보이지 않고 날짜와 요일만. */
export function dayTitle(date: string, index: number): string {
  const d = new Date(`${date}T00:00:00`)
  return `${ORDINALS[index] ?? `${index + 1}번째`} 날 · ${d.getMonth() + 1}.${d.getDate()} (${'일월화수목금토'[d.getDay()]})`
}

/** pin_id → 장소 이름. 이미 불러온 확정 리스트·핀 목록에서만 찾는다(새 요청 없음). 앞에 둔 것이 이긴다. */
export function pinNames(pins: Pin[]): Map<string, string> {
  const names = new Map<string, string>()
  for (const p of pins) if (p.id && p.place_name && !names.has(p.id)) names.set(p.id, p.place_name)
  return names
}

/** pin_id → 좌표. 위치를 모르는 핀(실시간 핀 등)은 넣지 않는다. 앞에 둔 것이 이긴다. */
export function pinPoints(pins: Pin[]): Map<string, { lat: number; lng: number }> {
  const points = new Map<string, { lat: number; lng: number }>()
  for (const p of pins) if (isPlaced(p) && !points.has(p.id)) points.set(p.id, { lat: p.lat, lng: p.lng })
  return points
}

export type Leg = { mode: 'walk' | 'transit'; minutes: number }

/** 구간 문구 — 도보 N분 / 대중교통 약 N분(직선거리 어림). */
export const legLabel = (leg: Leg): string => (leg.mode === 'transit' ? `대중교통 약 ${leg.minutes}분` : `도보 ${leg.minutes}분`)

/** 한 날의 합계 「도보 X분 · 대중교통 약 Y분」(0인 쪽은 뺀다). 구간이 없으면 빈 문자열. */
export function daySummary(legs: Leg[]): string {
  const sum = (mode: Leg['mode']) => legs.filter((l) => l.mode === mode).reduce((a, l) => a + l.minutes, 0)
  const walk = sum('walk')
  const transit = sum('transit')
  return [walk > 0 && `도보 ${walk}분`, transit > 0 && `대중교통 약 ${transit}분`].filter(Boolean).join(' · ')
}

/** 한 날의 장소를 방문 순서대로, 각 장소 뒤에 다음 곳까지의 구간을 붙인다(마지막은 null). 좌표를 알면 point 도 붙는다. */
export function dayStops(day: CourseDayDto, names: Map<string, string>, points: Map<string, { lat: number; lng: number }> = new Map()) {
  return [...day.slots]
    .sort((a, b) => a.order - b.order)
    .map((slot, i, all) => {
      const next = all[i + 1]
      const found = next && day.legs.find((l) => l.from_pin_id === slot.pin_id && l.to_pin_id === next.pin_id)
      const leg: Leg | null = found ? { mode: found.mode === 'transit' ? 'transit' : 'walk', minutes: found.approx_minutes } : null
      const name = names.get(slot.pin_id) ?? '이 장소'
      const at = points.get(slot.pin_id)
      return { pinId: slot.pin_id, name, needsCheck: slot.needs_check, leg, point: at ? ({ name, ...at } satisfies KakaoPoint) : null }
    })
}

export type DayStop = ReturnType<typeof dayStops>[number]

export type DayLink = { url: string; label: string; cut: boolean }

/** 하루 도보 길찾기 링크 — 이어지는 도보 구간(양 끝 좌표를 앎)을 한 경로로 묶는다. 경로가 둘 이상이면 「N 길찾기」로 가른다. */
export function walkLinks(stops: DayStop[]): DayLink[] {
  const paths: KakaoPoint[][] = []
  let cur: KakaoPoint[] = []
  stops.forEach((s, i) => {
    const next = stops[i + 1]
    const linkable = s.point && next?.point && s.leg?.mode === 'walk'
    if (!linkable) {
      if (cur.length >= 2) paths.push(cur)
      cur = []
      return
    }
    if (cur.length === 0) cur.push(s.point!)
    cur.push(next.point!)
  })
  if (cur.length >= 2) paths.push(cur)
  return paths.flatMap((path, i) => {
    const url = kakaoWalkUrl(path)
    return url ? [{ url, label: paths.length > 1 ? `도보 길찾기 ${i + 1}` : '카카오맵에서 길찾기', cut: path.length > KAKAO_ROUTE_MAX }] : []
  })
}

/** 대중교통 구간의 길찾기 링크(출발 → 도착). 좌표를 모르면 null. */
export function transitLink(from: DayStop, to: DayStop | undefined): string | null {
  return from.point && to?.point ? kakaoTrafficUrl(from.point, to.point) : null
}

/**
 * 날짜별 경로선 모양(#683). 색만으로 가르지 않게 선 모양도 같이 바꾼다 — 색 3개, 모양 4개가 서로 다른 주기로 돌아 열둘째 날까지 겹치지 않는다.
 * dash 는 범례 그림(SVG stroke-dasharray)이고 style 은 카카오 Polyline 이름이다.
 */
const DAY_COLORS = ['--course-day-1', '--course-day-2', '--course-day-3']
const DAY_STYLES = [
  { style: 'solid', dash: '' },
  { style: 'longdash', dash: '10 5' },
  { style: 'shortdash', dash: '5 4' },
  { style: 'longdashdot', dash: '10 4 2 4' },
]
export const dayLine = (index: number) => ({ color: DAY_COLORS[index % DAY_COLORS.length], ...DAY_STYLES[index % DAY_STYLES.length] })

/** 지도에 그릴 날짜별 코스. 좌표를 아는 장소만 잇고, 번호는 그날 방문 순서다. 한 곳뿐인 날은 번호 원만, 좌표를 아는 곳이 없는 날은 뺀다. */
export type CourseDrawing = RouteDrawing & { title: string; dash: string }

export function courseDrawings(run: Pick<CourseRunDto, 'days'>, points: Map<string, { lat: number; lng: number }>): CourseDrawing[] {
  return run.days.flatMap((day, i) => {
    const stops = dayStops(day, new Map(), points)
    const placed = stops.flatMap((s, n) => (s.point ? [{ n: n + 1, lat: s.point.lat, lng: s.point.lng }] : []))
    if (placed.length === 0) return []
    const legs = stops.flatMap((s, n) => {
      const to = stops[n + 1]
      return s.leg && s.point && to?.point ? [{ from: s.point, to: to.point, label: legLabel(s.leg) }] : []
    })
    return [{ title: dayTitle(day.date, i), stops: placed, legs, ...dayLine(i) }]
  })
}
