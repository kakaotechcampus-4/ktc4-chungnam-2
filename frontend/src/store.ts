import { create } from 'zustand'

/**
 * UI 상태만 둔다. 서버에서 온 것(핀 목록·추천 결과·확정 리스트)은 전부 TanStack Query 소관이다.
 * 이 경계를 첫 스토어에서 못 박아 둔다 — 서버 데이터를 여기 복사해두기 시작하면
 * Query 캐시와 두 벌이 되고 어느 쪽이 최신인지 알 수 없어진다.
 */
interface UiState {
  /** 바텀시트(핀 상세, #21)를 여는 키. 닫힘 = null */
  selectedPinId: string | null
  selectPin: (pinId: string | null) => void
}

export const useUiStore = create<UiState>((set) => ({
  selectedPinId: null,
  selectPin: (pinId) => set({ selectedPinId: pinId }),
}))
