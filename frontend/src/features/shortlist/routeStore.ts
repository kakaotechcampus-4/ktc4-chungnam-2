import { create } from 'zustand'

import { useSheetStore } from '@/features/shell/sheetStore'

/**
 * 「동선 보기」 토글과 보는 날. 확정 탭(그날 일정)과 지도(경로선)가 같이 본다.
 * 동선은 일정 순서다(2026-11-03) — 고른 날이 기간 밖이거나 없으면 `routeDay`가 장소를 넣은 첫 날로 고른다.
 */
export const useRouteStore = create<{ on: boolean; day: string | null; set: (on: boolean) => void; setDay: (day: string) => void }>((set) => ({
  on: false,
  day: null,
  set: (on) => set({ on }),
  setDay: (day) => set({ day }),
}))

/**
 * 다른 탭(AI 코스 점검 결과 #1428, 에이전트 제안)에서 「동선 보기」를 열 때. 장소를 넣은 첫날을 고르고(`routeDay`),
 * 시트를 절반으로 열어 날짜 칩과 지도가 함께 보이게 한다. 확정 탭으로 옮기는 것은 부르는 쪽이 한다.
 */
export function openRoute() {
  useRouteStore.setState({ on: true, day: null })
  useSheetStore.getState().setStage('shortlist', 2)
}
