import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'

import { invalidateCredits } from '@/features/credits/queries'

import { createCourse, fetchCourseRun, fetchLatestCourse } from './api'
import { isFinished, POLL_MS, requestBody } from './model'

export const courseKeys = {
  run: (runId: string) => ['course-runs', runId] as const,
  latest: (mapId: string) => ['maps', mapId, 'courses', 'latest'] as const,
}

/**
 * 코스 run 조회. 끝나기(done·failed) 전까지 2초마다 다시 부른다. 포커스로는 다시 부르지 않는다 — 탭을 오가며 쓸데없이 겹치지 않게.
 * 조회가 실패(재시도 뒤)하면 그 자리에서 멈추고 화면이 「다시 불러오기」를 낸다. 무한히 두드리지 않는다.
 */
export function useCourseRunQuery(runId: string) {
  return useQuery({
    queryKey: courseKeys.run(runId),
    queryFn: () => fetchCourseRun(runId),
    refetchInterval: (query) => (query.state.status === 'error' || isFinished(query.state.data) ? false : POLL_MS),
    refetchOnWindowFocus: false,
    retry: 2,
  })
}

/** 시트를 열 때 「최근 코스 보기」가 있는지. 없으면 null. */
export function useLatestCourseQuery(mapId: string) {
  return useQuery({ queryKey: courseKeys.latest(mapId), queryFn: () => fetchLatestCourse(mapId), refetchOnWindowFocus: false })
}

export function useCreateCourseMutation(mapId: string) {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (text: string) => createCourse(mapId, requestBody(text)),
    // 새 run 이 생겼으니 「최근 코스」는 다시 받는다. 코스 1번에 크레딧을 쓴다(#432) — 잔액도 다시 받는다.
    // 결과 없이 끝나면 서버가 돌려준다. 그 잔액은 시트 입구를 다시 열 때 잔액 줄이 새로 받는다.
    onSuccess: () => {
      void invalidateCredits(queryClient)
      return queryClient.invalidateQueries({ queryKey: courseKeys.latest(mapId), refetchType: 'none' })
    },
  })
}
