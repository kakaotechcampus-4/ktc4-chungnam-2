import { create } from 'zustand'

/**
 * 「동선 보기」 토글과 보는 날. 확정 탭(그날 일정)과 지도(경로선)가 같이 본다.
 * 동선은 일정 순서다(2026-11-03) — 고른 날이 기간 밖이거나 없으면 `routeDay`가 장소를 넣은 첫 날로 고른다.
 */
export const useRouteStore = create<{ on: boolean; day: string | null; set: (on: boolean) => void; setDay: (day: string | null) => void }>((set) => ({
  on: false,
  day: null,
  set: (on) => set({ on }),
  setDay: (day) => set({ day }),
}))
