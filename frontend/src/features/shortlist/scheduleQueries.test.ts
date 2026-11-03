import { describe, expect, it } from 'vitest'

import type { ScheduleDto } from './model'
import { groupsFor, scheduleFromDto } from './scheduleQueries'

type Item = ScheduleDto['items'][number]
const item = (id: string, pin: string, date: string | null, order: number | null) =>
  ({ id, pin: { id: pin }, scheduled_date: date, visit_order: order }) as unknown as Item
const dto = (items: Item[]): ScheduleDto => ({ start_date: '2026-11-01', end_date: '2026-11-03', version: 'v1', items })

describe('서버 일정 ↔ 화면 일정 (#1172)', () => {
  it('날짜별로 묶고 그날 순서(visit_order)대로 핀 id를 담는다 — 미배정은 담지 않는다', () => {
    const d = dto([item('i3', 'c', '2026-11-02', 1), item('i1', 'a', '2026-11-02', 0), item('i2', 'b', null, 0), item('i4', 'd', '2026-11-01', 0)])
    expect(scheduleFromDto(d).days).toEqual({ '2026-11-01': ['d'], '2026-11-02': ['a', 'c'] })
    expect(scheduleFromDto(undefined).days).toEqual({})
  })

  it('저장 요청은 모든 확정 항목을 정확히 한 번 — 일정에 없는 항목은 미배정 그룹에 지금 순서대로 모은다', () => {
    const d = dto([item('i1', 'a', null, 0), item('i2', 'b', null, 1), item('i3', 'c', '2026-11-02', 0)])
    const { groups, items } = groupsFor(d, { days: { '2026-11-02': ['b', 'c'] } })
    expect(groups).toEqual([
      { date: '2026-11-02', item_ids: ['i2', 'i3'] },
      { date: null, item_ids: ['i1'] },
    ])
    expect(groups.flatMap((g) => g.item_ids).sort()).toEqual(['i1', 'i2', 'i3'])
    // 화면에 바로 보일 새 서버 일정: 날짜 항목이 날짜 순서대로, 미배정이 마지막
    expect(items.map((i) => [i.id, i.scheduled_date, i.visit_order])).toEqual([
      ['i2', '2026-11-02', 0],
      ['i3', '2026-11-02', 1],
      ['i1', null, 0],
    ])
  })

  it('서버에 없는 핀 id는 건너뛰고, 같은 핀이 두 날에 있어도 한 번만 보낸다', () => {
    const d = dto([item('i1', 'a', null, 0)])
    const { groups } = groupsFor(d, { days: { '2026-11-01': ['ghost', 'a'], '2026-11-02': ['a'] } })
    expect(groups).toEqual([
      { date: '2026-11-01', item_ids: ['i1'] },
      { date: null, item_ids: [] },
    ])
  })
})
