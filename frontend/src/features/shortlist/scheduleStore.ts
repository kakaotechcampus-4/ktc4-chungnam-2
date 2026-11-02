import { useMemo } from 'react'
import { create } from 'zustand'

import { EMPTY_SCHEDULE, type DropSpot, type Schedule } from './schedule'

/**
 * 확정 탭 일정의 화면 상태와 저장. 백엔드에 일정 API가 없어서(2026-11-03) **이 기기에만** 지도별로 둔다 —
 * 동행자와 나누려면 서버가 있어야 한다. 저장하는 것은 날짜와 핀 id뿐이다.
 * 「일정 짜기」 패널(넓은 화면) 열림도 여기 둔다 — 패널은 탭 화면 밖 한 자리(`SchedulePanelHost`)에서 그려서,
 * 확정 탭 안이 핀 상세로 바뀌어도 닫히지 않는다(#1045와 같은 방식).
 */
type State = {
  /** 패널이 열린 지도. 닫히면 null. */
  openFor: string | null
  /** 이번에 읽거나 고친 지도별 일정. 없으면 저장소에서 읽는다. */
  byMap: Record<string, Schedule>
  /** 여행 날짜가 바뀌어 일정에서 빠진 장소 수. 확정 탭 리스트 위에 알리고, 탭을 떠나면 지운다. */
  moved: Record<string, number>
  /** 끄는 줄을 지금 놓으면 들어갈 자리. 칸 테두리와 끼울 자리 선을 그린다. 끄는 곳(패널·동선 보기·리스트)이 다 여기에 적는다. */
  hover: DropHover | null
}

/** 끄는 핀과, 지금 놓으면 들어갈 자리. */
export type DropHover = DropSpot & { pinId: string }

const useScheduleStore = create<State>(() => ({ openFor: null, byMap: {}, moved: {}, hover: null }))

const PREFIX = 'pingo.schedule.v1.'
const keyOf = (mapId: string) => `${PREFIX}${mapId}`

/** 시크릿 창·차단으로 저장소가 막혀 있으면 null — 그때는 이 화면 메모리에만 둔다. */
function storage(): Storage | null {
  try {
    return window.localStorage
  } catch {
    return null
  }
}

function isSchedule(v: unknown): v is Schedule {
  if (!v || typeof v !== 'object' || !('days' in v)) return false
  const days = (v as Schedule).days
  return !!days && typeof days === 'object' && Object.values(days).every((ids) => Array.isArray(ids) && ids.every((id) => typeof id === 'string'))
}

export function loadSchedule(mapId: string): Schedule {
  try {
    const raw = storage()?.getItem(keyOf(mapId))
    const parsed: unknown = raw ? JSON.parse(raw) : null
    return isSchedule(parsed) ? parsed : EMPTY_SCHEDULE
  } catch {
    return EMPTY_SCHEDULE
  }
}

/** 지금의 일정(React 밖 — 토스트의 「되돌리기」가 누르는 순간의 일정에서 되돌린다). */
export const getSchedule = (mapId: string): Schedule => useScheduleStore.getState().byMap[mapId] ?? loadSchedule(mapId)

/** 지도의 일정 — 이번에 고친 것이 있으면 그것, 없으면 저장소에서 읽은 것. */
export function useSchedule(mapId: string): Schedule {
  const mine = useScheduleStore((s) => s.byMap[mapId])
  return useMemo(() => mine ?? loadSchedule(mapId), [mine, mapId])
}

/** 일정을 바꾸고 저장한다. `moved`는 여행 날짜에 맞추며 일정에서 뺀 장소 수다(알림용). */
export function setSchedule(mapId: string, schedule: Schedule, moved = 0) {
  useScheduleStore.setState((s) => ({
    byMap: { ...s.byMap, [mapId]: schedule },
    ...(moved > 0 ? { moved: { ...s.moved, [mapId]: moved } } : {}),
  }))
  try {
    const s = storage()
    if (!s) return
    if (Object.keys(schedule.days).length === 0) s.removeItem(keyOf(mapId))
    else s.setItem(keyOf(mapId), JSON.stringify(schedule))
  } catch {
    // 저장이 막혀도(용량·차단) 이 화면에서는 그대로 쓴다.
  }
}

/** 지도를 나가거나 지우면 그 지도의 일정을, 로그아웃하면 모든 지도의 일정을 지운다. */
export function forgetSchedule(mapId?: string) {
  useScheduleStore.setState((s) => {
    if (!mapId) return { openFor: null, byMap: {}, moved: {} }
    const rest = { ...s.byMap }
    delete rest[mapId]
    return { openFor: s.openFor === mapId ? null : s.openFor, byMap: rest, moved: {} }
  })
  try {
    const s = storage()
    if (!s) return
    if (mapId) return s.removeItem(keyOf(mapId))
    // 지우면서 번호가 당겨지므로 뒤에서부터 본다.
    for (let i = s.length - 1; i >= 0; i--) {
      const key = s.key(i)
      if (key?.startsWith(PREFIX)) s.removeItem(key)
    }
  } catch {
    // 저장소가 막혀 있으면 지울 것도 없다.
  }
}

export const openSchedule = (mapId: string) => useScheduleStore.setState({ openFor: mapId })
export const closeSchedule = () => useScheduleStore.setState({ openFor: null, hover: null })
/** 확정 탭을 떠나면 패널을 닫고 빠진 수 알림도 지운다. */
export const leaveScheduleTab = () => useScheduleStore.setState({ openFor: null, moved: {}, hover: null })
export const setDropHover = (hover: DropHover | null) => useScheduleStore.setState({ hover })
export const useDropHover = () => useScheduleStore((s) => s.hover)
export const useScheduleOpen = (mapId: string) => useScheduleStore((s) => s.openFor === mapId)
export const useMovedCount = (mapId: string) => useScheduleStore((s) => s.moved[mapId] ?? 0)
