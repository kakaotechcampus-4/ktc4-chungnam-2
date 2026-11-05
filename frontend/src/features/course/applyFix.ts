import type { QueryClient } from '@tanstack/react-query'

import { fetchSchedule, putSchedule } from '@/features/shortlist/api'
import { groupsFor, saveScheduleOutside, scheduleFromDto, scheduleKeys } from '@/features/shortlist/scheduleQueries'
import type { Schedule } from '@/features/shortlist/schedule'
import type { ScheduleDto } from '@/features/shortlist/model'

import { fetchCourseRun } from './api'
import type { CourseMoveDto } from './model'
import { courseKeys } from './queries'

/**
 * 카드의 moves 를 일정에 적용한다(스펙 CourseFix). 옮겨 간 장소는 그 날에 남는 장소 뒤에, 원래 일정의 순서(날짜 → 그날 순서)대로 붙는다.
 * 미배정(from_date null)에서 오는 장소는 맨 뒤에 moves 순서대로 붙는다. 일정에 없는 pin_id 는 일정이 서버에서 바뀐 것이라 건너뛰지 않고 그대로 넣는다.
 */
export function applyMoves(schedule: Schedule, moves: CourseMoveDto[]): Schedule {
  const target = new Map(moves.map((m) => [m.pin_id, m.to_date]))
  const days: Record<string, string[]> = {}
  for (const [day, ids] of Object.entries(schedule.days)) {
    const rest = ids.filter((id) => !target.has(id))
    if (rest.length > 0) days[day] = rest
  }
  // 원래 일정 순서(날짜 → 그날 순서)로 정렬 — 미배정은 뒤에 moves 순서대로
  const original = Object.keys(schedule.days)
    .sort()
    .flatMap((d) => schedule.days[d])
  const rank = (id: string) => {
    const i = original.indexOf(id)
    return i === -1 ? Infinity : i
  }
  const ordered = moves.map((m, k) => ({ m, k })).sort((a, b) => rank(a.m.pin_id) - rank(b.m.pin_id) || a.k - b.k)
  for (const { m } of ordered) (days[m.to_date] ??= []).push(m.pin_id)
  return { days }
}

/**
 * 「반영」 — 지금 일정을 읽어 moves 대로 옮기고 같은 응답의 version 으로 저장한다(서버에 반영 API 는 없다).
 * 카드는 코스를 짤 때의 일정 기준이라, 그 뒤 일정이 바뀌었으면 저장하지 않고 false 를 돌려준다. 화면의 run.stale 은
 * `shortlist.changed` 로만 새로 받아서 연결이 끊긴 동안 바뀐 것을 모른다 — 그래서 저장 직전에 run 을 다시 받는다(서버가 받을 때 stale 을 센다).
 * 일정을 먼저 읽고 run 을 읽는다: run 이 stale 이 아니면 읽은 일정이 코스 때 일정이고, 그 뒤에 바뀌면 PUT 이 409 SHORTLIST_STALE 이다.
 * 저장한 일정을 캐시에 넣어 일정 화면이 바로 바뀐다.
 */
export function applyFix(queryClient: QueryClient, mapId: string, runId: string, moves: CourseMoveDto[]): Promise<boolean> {
  return saveScheduleOutside(mapId, async () => {
    const dto = await fetchSchedule(mapId)
    const run = await fetchCourseRun(runId)
    queryClient.setQueryData(courseKeys.run(runId), run)
    if (run.stale) return false
    const next = applyMoves(scheduleFromDto(dto), moves)
    const saved = await putSchedule(mapId, {
      version: dto.version,
      groups: groupsFor(dto, next).groups,
    })
    queryClient.setQueryData<ScheduleDto>(scheduleKeys.one(mapId), saved)
    return true
  })
}
