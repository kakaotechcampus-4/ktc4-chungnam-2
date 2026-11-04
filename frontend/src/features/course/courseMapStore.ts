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
 */
export const useCourseViewStore = create<{
  runs: Record<string, { runId: string; redirected: boolean } | undefined>
  open: (mapId: string, runId: string, redirected?: boolean) => void
  close: (mapId: string) => void
}>((set) => ({
  runs: {},
  open: (mapId, runId, redirected = false) => set((s) => ({ runs: { ...s.runs, [mapId]: { runId, redirected } } })),
  // 닫은 코스의 선·범례가 지도에 남지 않게 같이 끈다.
  close: (mapId) => {
    if (useCourseMapStore.getState().mapId === mapId) useCourseMapStore.getState().hide()
    set((s) => ({ runs: { ...s.runs, [mapId]: undefined } }))
  },
}))

/** 이미 반영한 고칠 점 카드(run id → 카드 id). 탭을 오가도 「반영됨」이 남게 화면 메모리에 둔다. */
export const useAppliedFixStore = create<{ applied: Record<string, string[] | undefined>; mark: (runId: string, fixId: string) => void }>((set) => ({
  applied: {},
  mark: (runId, fixId) => set((s) => ({ applied: { ...s.applied, [runId]: [...(s.applied[runId] ?? []), fixId] } })),
}))
