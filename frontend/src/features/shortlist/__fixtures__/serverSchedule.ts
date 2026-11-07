import { groupsFor, scheduleFromDto } from '../scheduleQueries'
import type { ScheduleDto } from '../model'
import type { Schedule } from '../schedule'

/** 목 서버의 일정을 읽고 심는 시험 도구 — 일정이 서버에 있으므로(#1172) 시험도 서버를 통해 본다. */
const BASE = 'http://localhost'

async function read(mapId: string): Promise<ScheduleDto> {
  return (await fetch(`${BASE}/maps/${mapId}/shortlist/schedule`)).json()
}

/** 지금 서버 일정의 날짜별 핀 id. */
export async function serverDays(mapId: string): Promise<Schedule['days']> {
  return scheduleFromDto(await read(mapId)).days
}

/** 서버 일정을 이 일정으로 바꾼다(확정 리스트에 있는 핀만 들어간다). */
export async function seedSchedule(mapId: string, next: Schedule) {
  const dto = await read(mapId)
  const { groups } = groupsFor(dto, next)
  const res = await fetch(`${BASE}/maps/${mapId}/shortlist/schedule`, { method: 'PUT', body: JSON.stringify({ version: dto.version, groups }) })
  if (!res.ok) throw new Error(`일정 심기 실패 ${res.status}`)
}
