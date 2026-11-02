import { useEffect } from 'react'

import { dayOrdinal } from '@/features/course/model'
import { useMapQuery } from '@/features/maps/queries'
import { showToast } from '@/features/shell/toast'
import { josa } from '@/ui/josa'

import { useShortlistQuery } from './queries'
import { dayOf, place, prune, tripDays, UNSET_DAY, type DropSpot, type Schedule } from './schedule'
import { getSchedule, setSchedule, useSchedule } from './scheduleStore'

/**
 * 지도의 여행 날짜와 확정 리스트에 맞춘 일정(이 기기의 저장 일정에서). 기간 밖 날의 장소와 확정 해제된 장소를 뺀 것이다.
 * 맞추며 바뀐 게 있으면 저장하고, 기간 때문에 빠진 수를 남긴다(확정 탭 리스트 위에 알린다).
 * 확정 탭, 「일정 짜기」 패널, 지도(동선 선)가 같이 쓴다 — 맞추는 규칙은 여기 한 곳이다.
 * (`scheduleStore`에 두면 `maps/queries` → `scheduleStore` → `maps/queries` 순환이 생겨서 따로 둔다.)
 */
export function useTripSchedule(mapId: string): { schedule: Schedule; dates: string[]; ready: boolean } {
  const map = useMapQuery(mapId).data
  const items = useShortlistQuery(mapId).data
  const stored = useSchedule(mapId)
  const dates = tripDays(map?.startDate, map?.endDate)
  const ready = Boolean(map && items)
  const { schedule, moved } = ready && items ? prune(stored, dates, items.map((i) => i.pin.id)) : { schedule: stored, moved: 0 }

  useEffect(() => {
    if (schedule !== stored) setSchedule(mapId, schedule, moved)
  }, [schedule, stored, moved, mapId])

  return { schedule, dates, ready }
}

/**
 * 일정 고치기 — 넣기·빼기는 토스트로 알리고 「되돌리기」를 준다(줄이 목록에서 사라지거나 생겨서, 화면 읽기에도 이 토스트가 알린다).
 * 같은 날 안의 순서·다른 날로 옮기기는 화면에서 바로 보여서 알리지 않는다. 되돌리기는 누르는 순간의 일정에서 그 일만 되돌린다.
 */
export function useScheduleEdit(mapId: string) {
  const trip = useTripSchedule(mapId)
  const { schedule, dates } = trip
  const dayName = (day: string) => dayOrdinal(dates.indexOf(day))
  const save = (next: Schedule) => setSchedule(mapId, next)

  /** 확정 리스트에서 그날로 넣는다(여러 곳이면 고른 순서대로). */
  function put(pinIds: string[], names: string[], day: string, index?: number) {
    if (pinIds.length === 0) return
    save(place(schedule, pinIds, day, index))
    const what = pinIds.length === 1 ? `${names[0]}${josa(names[0], '을', '를')}` : `${pinIds.length}곳을`
    showToast(`${what} ${dayName(day)}에 넣었어요`, { label: '되돌리기', onClick: () => save(place(getSchedule(mapId), pinIds, null)) })
  }

  /** 일정에서 빼 확정 리스트로 돌린다. */
  function takeOut(pinId: string, name: string) {
    const day = dayOf(schedule, pinId)
    if (!day) return
    const index = schedule.days[day].indexOf(pinId)
    save(place(schedule, [pinId], null))
    showToast(`${name}${josa(name, '을', '를')} 일정에서 뺐어요`, { label: '되돌리기', onClick: () => save(place(getSchedule(mapId), [pinId], day, index)) })
  }

  /** 끌어 놓은 자리로 — 리스트 칸이면 빼기, 날짜 칸이면 그 자리에 끼운다(같은 날이면 순서 바꾸기). */
  function drop(pinId: string, name: string, spot: DropSpot) {
    if (spot.day === UNSET_DAY) return takeOut(pinId, name)
    if (!dayOf(schedule, pinId)) return put([pinId], [name], spot.day, spot.index)
    save(place(schedule, [pinId], spot.day, spot.index))
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
