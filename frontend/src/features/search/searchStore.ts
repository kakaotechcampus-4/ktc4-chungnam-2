import { create } from 'zustand'

import type { LatLng } from './model'

/**
 * 장소 검색은 잠깐 하는 작업이라 주소에 두지 않는다. 검색창(지도 위)과 결과 시트(마킹 탭)가 같이 본다.
 * `near` 는 검색할 때의 지도 가운데 — 결과를 가까운 순으로 받고 거리를 적는 기준이다.
 */
type SearchState = {
  query: string | null
  near: LatLng | null
  selectedId: string | null
  submit: (query: string, near: LatLng | null) => void
  select: (id: string | null) => void
  close: () => void
}

export const useSearchStore = create<SearchState>((set) => ({
  query: null,
  near: null,
  selectedId: null,
  submit: (query, near) => set({ query, near, selectedId: null }),
  select: (selectedId) => set({ selectedId }),
  close: () => set({ query: null, near: null, selectedId: null }),
}))
