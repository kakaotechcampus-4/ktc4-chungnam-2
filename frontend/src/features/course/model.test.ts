import { describe, expect, it } from 'vitest'

import { ApiError } from '@/api'
import type { Pin } from '@/features/map/model'

import { createErrorMessage, dayStops, dayTitle, goalState, inProgressRunId, isFinished, pinNames, requestBody, understandBody } from './model'

const err = (code: string, detail?: Record<string, unknown>) => new ApiError(409, { code, message: code, detail })

describe('course model', () => {
  it('요청 한 줄은 비면 보내지 않고, 있으면 앞뒤 공백을 뗀다', () => {
    expect(requestBody('   ')).toEqual({})
    expect(requestBody(' 둘째 날은 실내 위주로 ')).toEqual({ request_text: '둘째 날은 실내 위주로' })
  })

  it('done·failed 에서만 끝난 것으로 본다', () => {
    expect(isFinished({ status: 'running' })).toBe(false)
    expect(isFinished({ status: 'queued' })).toBe(false)
    expect(isFinished({ status: 'done' })).toBe(true)
    expect(isFinished({ status: 'failed' })).toBe(true)
    expect(isFinished(undefined)).toBe(false)
  })

  it('에러 코드별 문구와 진행 중 run id', () => {
    expect(createErrorMessage(err('COURSE_LIMIT'))).toBe('오늘은 다 썼어요. 내일 다시 짤 수 있어요')
    expect(createErrorMessage(err('COURSE_NOT_ENOUGH_PLACES'))).toContain('2곳')
    expect(createErrorMessage(err('SOMETHING_ELSE'))).toBeNull()
    expect(inProgressRunId(err('COURSE_IN_PROGRESS', { course_run_id: 'course_1' }))).toBe('course_1')
    expect(inProgressRunId(err('COURSE_IN_PROGRESS'))).toBeNull()
    expect(inProgressRunId(err('COURSE_LIMIT', { course_run_id: 'x' }))).toBeNull()
  })

  it('이해 카드는 문장 앞의 같은 제목을 한 번만 보인다', () => {
    expect(understandBody('이렇게 이해했어요: 둘째 날은 실내 위주로')).toBe('둘째 날은 실내 위주로')
    expect(understandBody('둘째 날은 실내 위주로 이해했어요')).toBe('둘째 날은 실내 위주로 이해했어요')
  })

  it('목표 상태: 지킴 / 못 지킴 / 판단 못 함', () => {
    const g = (met: boolean | null) => goalState({ id: 'a', kind: 'day_indoor', label: 'x', met }).label
    expect(g(true)).toBe('지킴')
    expect(g(false)).toBe('못 지킴')
    expect(g(null)).toBe('판단 못 함')
  })

  it('날짜 제목은 몇째 날과 요일만, 시간은 없다', () => {
    expect(dayTitle('2026-10-03', 0)).toBe('첫째 날 · 10.3 (토)')
    expect(dayTitle('2026-10-05', 2)).toBe('셋째 날 · 10.5 (월)')
  })

  it('한 날의 장소를 순서대로 놓고 구간 도보 분을 붙인다. 이름을 모르면 「이 장소」', () => {
    const names = pinNames([{ id: 'a', place_name: '가' } as Pin, { id: 'b', place_name: '나' } as Pin, { id: 'a', place_name: '중복' } as Pin])
    expect(names.get('a')).toBe('가')
    const stops = dayStops(
      {
        date: '2026-10-03',
        slots: [
          { pin_id: 'b', order: 2, needs_check: false },
          { pin_id: 'a', order: 1, needs_check: true },
          { pin_id: 'z', order: 3, needs_check: true },
        ],
        legs: [
          { from_pin_id: 'a', to_pin_id: 'b', approx_minutes: 7 },
          { from_pin_id: 'b', to_pin_id: 'z', approx_minutes: 3 },
        ],
      },
      names,
    )
    expect(stops.map((s) => [s.name, s.walkMinutes, s.needsCheck])).toEqual([
      ['가', 7, true],
      ['나', 3, false],
      ['이 장소', null, true],
    ])
  })
})
