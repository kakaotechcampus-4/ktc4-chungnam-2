import { create } from 'zustand'

import type { DropSpot } from './schedule'

/**
 * 확정 탭 일정의 **화면 상태** — 일정 자체는 서버가 갖고(`scheduleQueries.ts`, #1172) 여기에는 열림·끌기 같은 순간 상태만 둔다.
 * 「일정 짜기」 패널(넓은 화면) 열림도 여기 둔다 — 패널은 탭 화면 밖 한 자리(`SchedulePanelHost`)에서 그려서,
 * 확정 탭 안이 핀 상세로 바뀌어도 닫히지 않는다(#1045와 같은 방식).
 */
type State = {
  /** 패널이 열린 지도. 닫히면 null. */
  openFor: string | null
  /** 끄는 줄을 지금 놓으면 들어갈 자리. 칸 테두리와 끼울 자리 선을 그린다. 끄는 곳(패널·동선 보기·리스트)이 다 여기에 적는다. */
  hover: DropHover | null
}

/** 끄는 핀과, 지금 놓으면 들어갈 자리. */
export type DropHover = DropSpot & { pinId: string }

const useScheduleStore = create<State>(() => ({ openFor: null, hover: null }))

/** 일정이 서버로 옮겨 가기 전(2026-11-03)에 이 기기에 저장하던 키. 서버 일정으로 덮어쓰지 않고, 남은 것은 지울 때만 쓴다. */
const LEGACY_PREFIX = 'pingo.schedule.v1.'

/** 지도를 나가거나 지우면 그 지도의 화면 상태를, 로그아웃하면 모든 상태를 지운다. 예전 이 기기 저장 일정도 함께 지운다. */
export function forgetSchedule(mapId?: string) {
  useScheduleStore.setState((s) => (!mapId ? { openFor: null, hover: null } : { openFor: s.openFor === mapId ? null : s.openFor, hover: null }))
  try {
    const s = window.localStorage
    if (mapId) return s.removeItem(`${LEGACY_PREFIX}${mapId}`)
    // 지우면서 번호가 당겨지므로 뒤에서부터 본다.
    for (let i = s.length - 1; i >= 0; i--) {
      const key = s.key(i)
      if (key?.startsWith(LEGACY_PREFIX)) s.removeItem(key)
    }
  } catch {
    // 저장소가 막혀 있으면 지울 것도 없다.
  }
}

export const openSchedule = (mapId: string) => useScheduleStore.setState({ openFor: mapId })
export const closeSchedule = () => useScheduleStore.setState({ openFor: null, hover: null })
/** 확정 탭을 떠나면 패널을 닫는다. */
export const leaveScheduleTab = () => useScheduleStore.setState({ openFor: null, hover: null })
export const setDropHover = (hover: DropHover | null) => useScheduleStore.setState({ hover })
export const useDropHover = () => useScheduleStore((s) => s.hover)
export const useScheduleOpen = (mapId: string) => useScheduleStore((s) => s.openFor === mapId)
