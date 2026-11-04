import { create } from 'zustand'

import type { CourseDrawing } from './model'

/** AI 코스를 지도에 보여 주는 중인지(#683). 결과의 「지도에서 보기」가 켜고, AI 코스 탭 범례의 「끄기」가 끈다. 요청한 사람 화면에만 있다. */
export const useCourseMapStore = create<{ mapId: string | null; days: CourseDrawing[]; show: (mapId: string, days: CourseDrawing[]) => void; hide: () => void }>((set) => ({
  mapId: null,
  days: [],
  show: (mapId, days) => set({ mapId, days }),
  hide: () => set({ mapId: null, days: [] }),
}))

/**
 * AI 코스 탭에서 보고 있는 코스(run). 탭을 오가도 진행·결과 화면이 이어지게 지도별로 화면 메모리에만 둔다.
 * 새로고침하면 잊는다 — 입력 화면의 「최근 코스 보기」·「짜는 중인 코스 보기」로 다시 연다.
 * `failed` 는 마지막 코스 요청의 실패(보낸 요청 글 포함)다. 요청 중에 탭을 오가면 입력 화면이 새로 붙어
 * 그 화면의 요청 훅은 실패를 모른다 — 그래서 요청 훅이 여기에 남기고 입력 화면은 여기서 읽는다.
 */
export const useCourseViewStore = create<{
  runs: Record<string, { runId: string; redirected: boolean } | undefined>
  failed: Record<string, { error: unknown; text: string } | undefined>
  open: (mapId: string, runId: string, redirected?: boolean) => void
  close: (mapId: string) => void
  fail: (mapId: string, error: unknown, text: string) => void
  clearFail: (mapId: string) => void
}>((set) => ({
  runs: {},
  failed: {},
  open: (mapId, runId, redirected = false) =>
    set((s) => ({ runs: { ...s.runs, [mapId]: { runId, redirected } }, failed: { ...s.failed, [mapId]: undefined } })),
  // 닫은 코스의 선·범례가 지도에 남지 않게 같이 끈다.
  close: (mapId) => {
    if (useCourseMapStore.getState().mapId === mapId) useCourseMapStore.getState().hide()
    set((s) => ({ runs: { ...s.runs, [mapId]: undefined } }))
  },
  fail: (mapId, error, text) => set((s) => ({ failed: { ...s.failed, [mapId]: { error, text } } })),
  clearFail: (mapId) => set((s) => ({ failed: { ...s.failed, [mapId]: undefined } })),
}))
