import { create } from 'zustand'

import type { CourseDrawing } from './model'

/** AI 코스를 지도에 보여 주는 중인지(#683). 결과 시트의 「지도에서 보기」가 켜고, 확정 탭 범례의 「끄기」가 끈다. 요청한 사람 화면에만 있다. */
export const useCourseMapStore = create<{ mapId: string | null; days: CourseDrawing[]; show: (mapId: string, days: CourseDrawing[]) => void; hide: () => void }>((set) => ({
  mapId: null,
  days: [],
  show: (mapId, days) => set({ mapId, days }),
  hide: () => set({ mapId: null, days: [] }),
}))
