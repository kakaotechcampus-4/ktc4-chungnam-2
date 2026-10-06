import { create } from 'zustand'

import type { RecommendRunDto } from './model'

/**
 * 지도마다 지금 보고 있는 추천 run. run 은 요청한 사람에게만 보이는 것이라(5-5-1) 서버에 "내 run 목록"이 없다 —
 * 화면이 들고 있는다.
 * ponytail: 새로고침하면 잊는다. 이어 보기가 필요해지면 sessionStorage 에 runId 를 둔다.
 */
type AiState = {
  runs: Record<string, RecommendRunDto | undefined>
  setRun: (mapId: string, run: RecommendRunDto | undefined) => void
}

export const useAiStore = create<AiState>((set) => ({
  runs: {},
  setRun: (mapId, run) => set((s) => ({ runs: { ...s.runs, [mapId]: run } })),
}))
