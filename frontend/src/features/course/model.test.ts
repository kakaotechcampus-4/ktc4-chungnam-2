import { describe, expect, it } from 'vitest'

import { ApiError } from '@/api'
import type { Pin } from '@/features/map/model'

import { kakaoTrafficUrl } from '@/features/shortlist/model'

import { createErrorMessage, daySummary, dayStops, dayTitle, goalState, inProgressRunId, isFinished, legLabel, pinNames, pinPoints, requestBody, transitLink, understandBody, walkLinks } from './model'

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
          { from_pin_id: 'a', to_pin_id: 'b', mode: 'walk', approx_minutes: 7 },
          { from_pin_id: 'b', to_pin_id: 'z', mode: 'transit', approx_minutes: 3 },
        ],
      },
      names,
    )
    expect(stops.map((s) => [s.name, s.leg, s.needsCheck])).toEqual([
      ['가', { mode: 'walk', minutes: 7 }, true],
      ['나', { mode: 'transit', minutes: 3 }, false],
      ['이 장소', null, true],
    ])
  })

  const pin = (id: string, name: string, lat?: number, lng?: number) => ({ id, place_name: name, lat, lng }) as Pin
  const day = (ids: string[], modes: ('walk' | 'transit')[]) => ({
    date: '2026-10-03',
    slots: ids.map((pin_id, i) => ({ pin_id, order: i + 1, needs_check: false })),
    legs: modes.map((mode, i) => ({ from_pin_id: ids[i], to_pin_id: ids[i + 1], mode, approx_minutes: 10 })),
  })

  it('구간 문구와 하루 합계 — 0인 쪽은 뺀다', () => {
    expect(legLabel({ mode: 'walk', minutes: 7 })).toBe('도보 7분')
    expect(legLabel({ mode: 'transit', minutes: 25 })).toBe('대중교통 약 25분')
    expect(daySummary([{ mode: 'walk', minutes: 7 }, { mode: 'transit', minutes: 25 }, { mode: 'walk', minutes: 3 }])).toBe('도보 10분 · 대중교통 약 25분')
    expect(daySummary([{ mode: 'transit', minutes: 25 }])).toBe('대중교통 약 25분')
    expect(daySummary([])).toBe('')
  })

  it('도보 길찾기는 이어지는 도보 구간을 한 경로로 묶고, 대중교통에서 끊는다', () => {
    const pins = [pin('a', '가', 37.1, 127.1), pin('b', '나', 37.2, 127.2), pin('c', '다', 37.3, 127.3), pin('d', '라', 37.4, 127.4), pin('e', '마', 37.5, 127.5)]
    const stops = dayStops(day(['a', 'b', 'c', 'd', 'e'], ['walk', 'walk', 'transit', 'walk']), pinNames(pins), pinPoints(pins))
    const links = walkLinks(stops)
    expect(links.map((l) => l.url)).toEqual([
      `https://map.kakao.com/link/by/walk/${encodeURIComponent('가')},37.1,127.1/${encodeURIComponent('나')},37.2,127.2/${encodeURIComponent('다')},37.3,127.3`,
      `https://map.kakao.com/link/by/walk/${encodeURIComponent('라')},37.4,127.4/${encodeURIComponent('마')},37.5,127.5`,
    ])
    expect(links.map((l) => l.label)).toEqual(['도보 길찾기 1', '도보 길찾기 2'])
    // 경로가 하나면 이름은 「카카오맵에서 길찾기」
    expect(walkLinks(dayStops(day(['a', 'b'], ['walk']), pinNames(pins), pinPoints(pins))).map((l) => l.label)).toEqual(['카카오맵에서 길찾기'])
  })

  it('좌표를 모르는 장소나 대중교통뿐인 날엔 도보 링크가 없고, 7곳을 넘으면 앞 7곳만', () => {
    const pins = [pin('a', '가', 37.1, 127.1), pin('b', '나'), pin('c', '다', 37.3, 127.3)]
    expect(walkLinks(dayStops(day(['a', 'b', 'c'], ['walk', 'walk']), pinNames(pins), pinPoints(pins)))).toEqual([])
    expect(walkLinks(dayStops(day(['a', 'c'], ['transit']), pinNames(pins), pinPoints(pins)))).toEqual([])
    const ids = 'abcdefghi'.split('')
    const many = ids.map((id, i) => pin(id, id, 37 + i / 100, 127))
    const [link] = walkLinks(dayStops(day(ids, Array(8).fill('walk')), pinNames(many), pinPoints(many)))
    expect(link.cut).toBe(true)
    expect(link.url.split('/by/walk/')[1].split('/')).toHaveLength(7)
  })

  it('대중교통 링크는 출발 → 도착만, 이름의 , / 는 띄어쓰기로 바꾼다', () => {
    const pins = [pin('a', '가,나/다', 37.1, 127.1), pin('b', '라', 37.2, 127.2), pin('c', '마')]
    const stops = dayStops(day(['a', 'b', 'c'], ['transit', 'transit']), pinNames(pins), pinPoints(pins))
    const url = transitLink(stops[0], stops[1])
    expect(url).toBe(`https://map.kakao.com/link/by/traffic/${encodeURIComponent('가 나 다')},37.1,127.1/${encodeURIComponent('라')},37.2,127.2`)
    expect(url).toBe(kakaoTrafficUrl({ name: '가,나/다', lat: 37.1, lng: 127.1 }, { name: '라', lat: 37.2, lng: 127.2 }))
    expect(transitLink(stops[1], stops[2])).toBeNull() // 도착 좌표 모름
  })
})
