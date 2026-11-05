import { beforeEach, describe, expect, it, vi } from 'vitest'

import { ApiError } from '@/api'

import { fetchSchedule, putSchedule } from './api'
import type { ScheduleDto } from './model'
import { groupsFor, putOnLatest, scheduleFromDto } from './scheduleQueries'

vi.mock('./api', () => ({ fetchSchedule: vi.fn(), putSchedule: vi.fn() }))

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

describe('409 다시 보내기 (#1436)', () => {
  const stale = () => new ApiError(409, { code: 'SHORTLIST_STALE', message: 'stale' })
  const want = { days: { '2026-11-01': ['a'] } }

  beforeEach(() => {
    vi.mocked(putSchedule).mockReset()
    vi.mocked(fetchSchedule).mockReset()
  })

  it('확정 리스트에 장소만 늘었으면(날짜 배치 그대로) 최신 version으로 한 번 더 보낸다', async () => {
    const base = dto([item('i1', 'a', null, 0)])
    const latest = { ...dto([item('i1', 'a', null, 0), item('i2', 'b', null, 1)]), version: 'v2' }
    vi.mocked(putSchedule).mockRejectedValueOnce(stale()).mockResolvedValueOnce(latest)
    vi.mocked(fetchSchedule).mockResolvedValueOnce(latest)

    await expect(putOnLatest('m1', base, want)).resolves.toBe(latest)
    expect(vi.mocked(putSchedule).mock.calls[1]).toEqual([
      'm1',
      { version: 'v2', groups: [{ date: '2026-11-01', item_ids: ['i1'] }, { date: null, item_ids: ['i2'] }] },
    ])
  })

  it('다른 구성원이 날짜 배치를 바꿨으면 덮지 않고 409를 그대로 던진다', async () => {
    const base = dto([item('i1', 'a', null, 0), item('i2', 'b', null, 1)])
    const latest = { ...dto([item('i1', 'a', null, 0), item('i2', 'b', '2026-11-02', 0)]), version: 'v2' }
    vi.mocked(putSchedule).mockRejectedValueOnce(stale())
    vi.mocked(fetchSchedule).mockResolvedValueOnce(latest)

    await expect(putOnLatest('m1', base, want)).rejects.toMatchObject({ code: 'SHORTLIST_STALE' })
    expect(putSchedule).toHaveBeenCalledTimes(1)
  })

  it('409가 아닌 실패는 다시 받지 않고 그대로 던진다', async () => {
    vi.mocked(putSchedule).mockRejectedValueOnce(new ApiError(422, { code: 'VALIDATION_ERROR', message: 'bad' }))

    await expect(putOnLatest('m1', dto([item('i1', 'a', null, 0)]), want)).rejects.toMatchObject({ code: 'VALIDATION_ERROR' })
    expect(fetchSchedule).not.toHaveBeenCalled()
  })
})
