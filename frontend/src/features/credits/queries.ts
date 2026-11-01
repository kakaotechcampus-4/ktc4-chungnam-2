import { useQuery, type QueryClient } from '@tanstack/react-query'

import { fetchCredits } from './api'
import { creditBlock } from './model'

export const creditKeys = {
  me: ['credits', 'me'] as const,
}

/**
 * 내 크레딧. 사람마다 하나라 지도와 무관하다(docs/credits-reviews.md 2절).
 * 게스트의 403 은 다시 물어도 같다 — 재시도하지 않는다. 그 오류가 곧 「게스트 안내」의 근거다(CreditGate).
 */
export function useCreditsQuery() {
  return useQuery({
    queryKey: creditKeys.me,
    queryFn: fetchCredits,
    retry: (count, err) => !creditBlock(err) && count < 1,
  })
}

/** 잔액이 바뀌었을 수 있는 요청(추천 받기·AI 코스 짜기·후기 저장)이 성공하면 부른다. 후기 쪽(#953)도 이것을 쓴다. */
export function invalidateCredits(queryClient: QueryClient) {
  return queryClient.invalidateQueries({ queryKey: creditKeys.me })
}
