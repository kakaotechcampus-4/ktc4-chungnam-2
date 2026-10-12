import { create } from 'zustand'

/** 「동선 보기」 토글. 확정 탭(시트)과 지도(경로선)가 같이 본다. */
export const useRouteStore = create<{ on: boolean; set: (on: boolean) => void }>((set) => ({
  on: false,
  set: (on) => set({ on }),
}))
