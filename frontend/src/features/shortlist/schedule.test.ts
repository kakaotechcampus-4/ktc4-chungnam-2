import { describe, expect, it } from 'vitest'

import type { Pin } from '@/features/map/model'

import { scheduleDrawing } from './model'
import { dayOf, droppedCount, EMPTY_SCHEDULE, place, prune, routeDay, scheduledIds, tripDays, type Schedule } from './schedule'

const S = (days: Schedule['days']): Schedule => ({ days })

describe('일정 — 넣기·끼우기·옮기기·빼기', () => {
  it('여행 날짜 목록은 양끝을 포함하고, 달이 바뀌어도 이어진다', () => {
    expect(tripDays('2026-10-30', '2026-11-02')).toEqual(['2026-10-30', '2026-10-31', '2026-11-01', '2026-11-02'])
    expect(tripDays('2026-11-01', '2026-11-01')).toEqual(['2026-11-01'])
    expect(tripDays('2026-11-02', '2026-11-01')).toEqual([])
    expect(tripDays(undefined, '2026-11-01')).toEqual([])
  })

  it('그날 끝에 차례로 넣고, 자리를 주면 그 자리에 끼운다 — 다른 날로 옮기면 앞 날에서 빠지고, null 이면 일정에서 뺀다', () => {
    let s = place(EMPTY_SCHEDULE, ['a', 'b'], '2026-11-01')
    expect(s.days['2026-11-01']).toEqual(['a', 'b'])
    s = place(s, ['c'], '2026-11-01', 1)
    expect(s.days['2026-11-01']).toEqual(['a', 'c', 'b'])
    s = place(s, ['a'], '2026-11-02')
    expect(s.days).toEqual({ '2026-11-01': ['c', 'b'], '2026-11-02': ['a'] })
    s = place(s, ['b'], null)
    expect(s.days).toEqual({ '2026-11-01': ['c'], '2026-11-02': ['a'] })
    expect(dayOf(s, 'b')).toBeNull()
    expect(scheduledIds(s)).toEqual(new Set(['c', 'a']))
  })

  it('같은 날 안에서 옮기면 순서 바꾸기다 — 자리는 옮기는 핀을 뺀 목록 기준이다', () => {
    const s = S({ '2026-11-01': ['a', 'b', 'c'] })
    expect(place(s, ['a'], '2026-11-01', 2).days['2026-11-01']).toEqual(['b', 'c', 'a'])
    expect(place(s, ['c'], '2026-11-01', 0).days['2026-11-01']).toEqual(['c', 'a', 'b'])
    expect(place(s, ['b'], '2026-11-01', 99).days['2026-11-01']).toEqual(['a', 'c', 'b'])
  })

  it('동선 보기의 날은 고른 날(기간 안), 아니면 장소를 넣은 첫 날, 그것도 없으면 첫 날', () => {
    const dates = tripDays('2026-11-01', '2026-11-03')
    const s = S({ '2026-11-02': ['a'] })
    expect(routeDay(s, dates, '2026-11-03')).toBe('2026-11-03')
    expect(routeDay(s, dates, '2026-10-30')).toBe('2026-11-02')
    expect(routeDay(s, dates, null)).toBe('2026-11-02')
    expect(routeDay(EMPTY_SCHEDULE, dates, null)).toBe('2026-11-01')
    expect(routeDay(s, [], null)).toBeNull()
  })
})

describe('그날 동선 그림', () => {
  const pin = (id: string, lat?: number) => ({ id, lat, lng: lat === undefined ? undefined : 127 }) as unknown as Pin

  it('일정 순서대로 번호를 달고, 위치를 모르는 핀은 그리지 않는다 — 구간 시간 글자는 없다', () => {
    const d = scheduleDrawing(['a', 'live', 'b'], [pin('a', 37.1), pin('live'), pin('b', 37.2)])
    expect(d.stops.map((s) => s.n)).toEqual([1, 3])
    expect(d.legs).toEqual([])
  })
})

describe('일정 — 여행 날짜가 바뀌면 빠진 날의 장소만 확정 리스트로 돌아간다', () => {
  const planned = S({ '2026-11-01': ['a', 'b'], '2026-11-02': ['c'], '2026-11-03': ['d'] })

  it('11/1~3 → 11/2~4: 11/1 의 장소만 빠지고, 11/2·11/3 의 장소는 그 날짜에 남는다', () => {
    const r = prune(planned, tripDays('2026-11-02', '2026-11-04'), ['a', 'b', 'c', 'd'])
    expect(r.schedule.days).toEqual({ '2026-11-02': ['c'], '2026-11-03': ['d'] })
    expect(r.moved).toBe(2)
  })

  it('일수가 줄면 끝 날의 장소만 빠진다', () => {
    const r = prune(planned, tripDays('2026-11-01', '2026-11-02'), ['a', 'b', 'c', 'd'])
    expect(r.schedule.days).toEqual({ '2026-11-01': ['a', 'b'], '2026-11-02': ['c'] })
    expect(r.moved).toBe(1)
  })

  it('일수가 늘거나 그대로면 바뀌지 않는다(같은 객체)', () => {
    const r = prune(planned, tripDays('2026-10-31', '2026-11-04'), ['a', 'b', 'c', 'd'])
    expect(r.schedule).toBe(planned)
    expect(r.moved).toBe(0)
  })

  it('확정 해제된 핀은 빼되 옮긴 수에는 세지 않는다', () => {
    const r = prune(planned, tripDays('2026-11-01', '2026-11-03'), ['a', 'c', 'd'])
    expect(r.schedule.days['2026-11-01']).toEqual(['a'])
    expect(r.moved).toBe(0)
  })

  it('날짜를 고치기 전에, 빠지는 날에 넣어 둔 장소 수를 센다', () => {
    const now = tripDays('2026-11-01', '2026-11-03')
    expect(droppedCount(planned, now, tripDays('2026-11-02', '2026-11-04'))).toBe(2)
    expect(droppedCount(planned, now, tripDays('2026-11-01', '2026-11-05'))).toBe(0)
    // 이미 기간 밖에 남아 있던 날(아직 정리 전)은 이번 수정 때문에 빠지는 게 아니라 세지 않는다.
    const stale = S({ ...planned.days, '2026-10-20': ['x'] })
    expect(droppedCount(stale, now, tripDays('2026-11-01', '2026-11-02'))).toBe(1)
  })
})
