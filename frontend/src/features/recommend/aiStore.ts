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
  /**
   * 카드나 지도에서 고른 후보(#843). 카드와 지도 점선 핀이 같은 값을 본다.
   * n 은 누를 때마다 늘린다 — 같은 후보를 다시 눌러도 지도가 다시 그리로 간다.
   */
  focus: { id: string; n: number } | null
  focusCandidate: (candidateId: string) => void
}

export const useAiStore = create<AiState>((set) => ({
  runs: {},
  // 새 run·다시 추천이면 후보가 바뀌어서 고른 것도 푼다.
  setRun: (mapId, run) => set((s) => ({ runs: { ...s.runs, [mapId]: run }, focus: null })),
  focus: null,
  focusCandidate: (id) => set((s) => ({ focus: { id, n: (s.focus?.n ?? 0) + 1 } })),
}))
