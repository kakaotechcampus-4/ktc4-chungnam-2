import { create } from 'zustand'

import type { RecommendCategory, RecommendRunDto } from './model'

/**
 * 지도마다 지금 보고 있는 추천 run. run 은 요청한 사람에게만 보이는 것이라(5-5-1) 서버에 "내 run 목록"이 없다 —
 * 화면이 들고 있는다.
 * ponytail: 새로고침하면 잊는다. 이어 보기가 필요해지면 sessionStorage 에 runId 를 둔다.
 */
type AiState = {
  runs: Record<string, RecommendRunDto | undefined>
  setRun: (mapId: string, run: RecommendRunDto | undefined) => void
  /** 추천 전 준비 화면에서 고른 카테고리. 광고 영역도 같은 카테고리로 부른다(docs/ads.md 4절). */
  picked: Record<string, RecommendCategory | undefined>
  setPicked: (mapId: string, category: RecommendCategory) => void
}

export const useAiStore = create<AiState>((set) => ({
  runs: {},
  setRun: (mapId, run) => set((s) => ({ runs: { ...s.runs, [mapId]: run } })),
  picked: {},
  setPicked: (mapId, category) => set((s) => ({ picked: { ...s.picked, [mapId]: category } })),
}))
