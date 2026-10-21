import type { components } from '@pingo/contracts/src/types/api'

import { ApiError } from '@/api'
import type { Pin } from '@/features/map/model'

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

/** 작업 기록의 「누가」 칩 — 색(tag-*)과 글자를 함께 쓴다. AI 파랑 · 코드 회색 · 사람 주황. */
export const BY: Record<CourseStepDto['by'], { label: string; tag: string }> = {
  ai: { label: 'AI', tag: 'tag-ai' },
  code: { label: '코드', tag: 'tag-neutral' },
  human: { label: '사람', tag: 'tag-warn' },
}

/** 첫 줄 「이해」는 카드의 제목이 "이렇게 이해했어요"라서, 문장 앞에 같은 말이 오면 한 번만 보이게 뗀다. */
export function understandBody(text: string): string {
  return text.replace(/^이렇게 이해했어요\s*[:：]?\s*/, '')
}

export const GOAL_STATE = {
  met: { label: '지킴', tag: 'tag-good' },
  missed: { label: '못 지킴', tag: 'tag-bad' },
  unknown: { label: '판단 못 함', tag: 'tag-neutral' },
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

export function failureText(code: CourseRunDto['failure_code']): string {
  return code === 'INTERRUPTED' ? '서버가 다시 켜지면서 코스 짜기가 끊겼어요' : '코스를 짜는 중에 오류가 났어요'
}

/** 코스 요청이 실패했을 때의 안내. 코드가 아닌 HTTP 만으로 갈리지 않는다(docs/errors.md). 모르는 코드는 null 이라 호출부가 ErrorText 로 보인다. */
export function createErrorMessage(error: unknown): string | null {
  if (!(error instanceof ApiError)) return null
  switch (error.code) {
    case 'COURSE_LIMIT':
      return '오늘은 다 썼어요. 내일 다시 짤 수 있어요'
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

const ORDINALS = ['첫째', '둘째', '셋째', '넷째', '다섯째', '여섯째', '일곱째']

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

/** 한 날의 장소를 방문 순서대로, 각 장소 뒤에 다음 곳까지의 도보 분을 붙인다(마지막은 null). */
export function dayStops(day: CourseDayDto, names: Map<string, string>) {
  return [...day.slots]
    .sort((a, b) => a.order - b.order)
    .map((slot, i, all) => {
      const next = all[i + 1]
      const leg = next && day.legs.find((l) => l.from_pin_id === slot.pin_id && l.to_pin_id === next.pin_id)
      return {
        pinId: slot.pin_id,
        name: names.get(slot.pin_id) ?? '이 장소',
        needsCheck: slot.needs_check,
        walkMinutes: leg ? leg.approx_minutes : null,
      }
    })
}
