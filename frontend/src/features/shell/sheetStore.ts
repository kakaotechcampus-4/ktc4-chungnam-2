import { create } from 'zustand'

/** 바텀시트 3단계(최종기획안 4절). 1 = 접힘(손잡이·제목만), 2 = 절반, 3 = 전체. */
export type SheetStage = 1 | 2 | 3
export type TabKey = 'map' | 'recommend' | 'shortlist'

type SheetState = {
  /** 탭마다 마지막 단계를 기억한다(FE 회의) — 탭을 오가도 시트가 매번 2단계로 튀지 않게. */
  stages: Record<TabKey, SheetStage>
  setStage: (tab: TabKey, stage: SheetStage) => void
  /** 지도를 끄는 동안 지도 버튼·검색창을 숨긴다(Figma '지도 움직일 때 버튼 페이드'). */
  mapMoving: boolean
  setMapMoving: (moving: boolean) => void
  /** 프로필 같은 모달이 떠 있으면 지도 버튼을 숨긴다. */
  modalOpen: boolean
  setModalOpen: (open: boolean) => void
}

export const useSheetStore = create<SheetState>((set) => ({
  stages: { map: 2, recommend: 2, shortlist: 2 },
  setStage: (tab, stage) => set((s) => ({ stages: { ...s.stages, [tab]: stage } })),
  mapMoving: false,
  setMapMoving: (mapMoving) => set({ mapMoving }),
  modalOpen: false,
  setModalOpen: (modalOpen) => set({ modalOpen }),
}))
