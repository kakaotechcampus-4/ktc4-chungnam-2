import { dayOrdinal } from '@/features/course/model'
import { useMapQuery } from '@/features/maps/queries'
import { showToast } from '@/features/shell/toast'
import { fireConfetti } from '@/ui/confetti'
import { josa } from '@/ui/josa'

import { currentSchedule, useSaveSchedule, useSchedule, useScheduleQuery } from './scheduleQueries'
import { dayOf, fillsLastDay, place, tripDays, UNSET_DAY, type DropSpot, type Schedule } from './schedule'
import { useQueryClient } from '@tanstack/react-query'

/**
 * 지도의 여행 날짜와 서버의 확정 일정(#1172). 일정은 서버가 갖고 구성원이 함께 본다 — 여행 날짜가 바뀌어 기간 밖이 된 장소는
 * 서버가 미배정(확정 리스트)으로 돌려놓아 여기서 따로 맞추지 않는다.
 * 확정 탭, 「일정 짜기」 패널, 지도(동선 선)가 같이 쓴다.
 */
export function useTripSchedule(mapId: string): {
  schedule: Schedule
  dates: string[]
  ready: boolean
  /** 일정을 받지 못했다(받는 중이 아니라 실패). `retry`로 다시 받는다. */
  error: unknown
  retry: () => void
} {
  const map = useMapQuery(mapId).data
  const query = useScheduleQuery(mapId)
  const dto = query.data
  const schedule = useSchedule(mapId)
  const dates = tripDays(map?.startDate, map?.endDate)
  return { schedule, dates, ready: Boolean(map && dto), error: dto ? null : query.error, retry: () => void query.refetch() }
}

/**
 * 일정 고치기 — 넣기·빼기는 토스트로 알리고 「되돌리기」를 준다(줄이 목록에서 사라지거나 생겨서, 화면 읽기에도 이 토스트가 알린다).
 * 같은 날 안의 순서·다른 날로 옮기기는 화면에서 바로 보여서 알리지 않는다. 되돌리기는 누르는 순간의 일정에서 그 일만 되돌린다.
 */
export function useScheduleEdit(mapId: string) {
  const trip = useTripSchedule(mapId)
  const queryClient = useQueryClient()
  const { schedule, dates } = trip
  const dayName = (day: string) => dayOrdinal(dates.indexOf(day))
  const saveNow = useSaveSchedule(mapId)
  // 서버 일정을 받기 전의 일정은 비어 있다 — 그 위에서 고치면 서버 일정을 덮으니 받은 뒤에만 고친다.
  const save = (next: Schedule) => {
    if (trip.ready) saveNow(next)
  }
  const now = () => currentSchedule(queryClient, mapId)
  // 내가 넣거나 옮겨서 마지막 빈 날을 채운 순간(#1723). 다른 구성원의 변경과 되돌리기는 이 길을 지나지 않는다.
  const saveMine = (next: Schedule) => {
    if (trip.ready && fillsLastDay(schedule, next, dates)) fireConfetti()
    save(next)
  }

  /** 확정 리스트에서 그날로 넣는다(여러 곳이면 고른 순서대로). */
  function put(pinIds: string[], names: string[], day: string, index?: number) {
    if (pinIds.length === 0 || !trip.ready) return
    saveMine(place(schedule, pinIds, day, index))
    const what = pinIds.length === 1 ? `${names[0]}${josa(names[0], '을', '를')}` : `${pinIds.length}곳을`
    showToast(`${what} ${dayName(day)}에 넣었어요`, { label: '되돌리기', onClick: () => save(place(now(), pinIds, null)) })
  }

  /** 일정에서 빼 확정 리스트로 돌린다. */
  function takeOut(pinId: string, name: string) {
    const day = dayOf(schedule, pinId)
    if (!day || !trip.ready) return
    const index = schedule.days[day].indexOf(pinId)
    save(place(schedule, [pinId], null))
    showToast(`${name}${josa(name, '을', '를')} 일정에서 뺐어요`, { label: '되돌리기', onClick: () => save(place(now(), [pinId], day, index)) })
  }

  /** 끌어 놓은 자리로 — 리스트 칸이면 빼기, 날짜 칸이면 그 자리에 끼운다(같은 날이면 순서 바꾸기). */
  function drop(pinId: string, name: string, spot: DropSpot) {
    if (spot.day === UNSET_DAY) return takeOut(pinId, name)
    if (!dayOf(schedule, pinId)) return put([pinId], [name], spot.day, spot.index)
    saveMine(place(schedule, [pinId], spot.day, spot.index))
  }

  /** 그날 안에서 한 칸 위(-1)·아래(+1)로(키보드 ↑↓). */
  function shift(pinId: string, delta: -1 | 1) {
    const day = dayOf(schedule, pinId)
    if (!day) return
    const at = schedule.days[day].indexOf(pinId) + delta
    if (at < 0 || at >= schedule.days[day].length) return
    save(place(schedule, [pinId], day, at))
  }

  return { ...trip, put, takeOut, drop, shift }
}
