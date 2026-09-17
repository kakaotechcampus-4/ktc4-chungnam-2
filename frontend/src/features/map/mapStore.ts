import { create } from 'zustand'

/**
 * 지도 탭의 UI 상태만 둔다. 서버에서 온 것(핀 목록)은 TanStack Query 소관이다 —
 * 여기 복사해두기 시작하면 캐시와 두 벌이 되고 어느 쪽이 최신인지 알 수 없어진다.
 *
 * 스토어를 앱 전역이 아니라 피처 안에 두는 이유: 지도 탭 하나에 #17·#18·#19·#20·#21
 * 다섯 이슈가 동시에 붙는다. 전역 스토어 한 파일에 모으면 그 파일이 곧 충돌 지점이 된다.
 * 필터 상태(#18)처럼 다른 이슈의 UI 상태는 각자 자기 스토어 파일을 새로 만든다.
 */
interface MapUiState {
  /** 바텀시트(핀 상세, #21)를 여는 키. 닫힘 = null */
  selectedPinId: string | null
  selectPin: (pinId: string | null) => void
}

export const useMapUiStore = create<MapUiState>((set) => ({
  selectedPinId: null,
  selectPin: (pinId) => set({ selectedPinId: pinId }),
}))
