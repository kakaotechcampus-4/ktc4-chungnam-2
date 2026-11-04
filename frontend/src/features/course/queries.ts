import { useIsMutating, useMutation, useQuery, useQueryClient } from '@tanstack/react-query'

import { invalidateCredits } from '@/features/credits/queries'

import { createCourse, fetchCourseRun, fetchLatestCourse } from './api'
import { useCourseViewStore } from './courseMapStore'
import { inProgressRunId, isFinished, POLL_MS, requestBody } from './model'

export const courseKeys = {
  /** 모든 run 상세(`run(runId)`의 앞부분) — 일정이 바뀌면 열려 있는 결과의 `stale`을 다시 받는다. */
  runs: ['course-runs'] as const,
  run: (runId: string) => ['course-runs', runId] as const,
  latest: (mapId: string) => ['maps', mapId, 'courses', 'latest'] as const,
  /** 코스 요청이 진행 중인지 보는 데만 쓴다(useIsMutating). */
  create: (mapId: string) => ['maps', mapId, 'courses', 'create'] as const,
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
  const mutation = useMutation({
    mutationKey: courseKeys.create(mapId),
    mutationFn: (text: string) => createCourse(mapId, requestBody(text)),
    // 새 run 이 생겼으니 「최근 코스」는 다시 받는다. 코스 1번에 크레딧을 쓴다(#432) — 잔액도 다시 받는다.
    // 결과 없이 끝나면 서버가 돌려준다. 그 잔액은 시트 입구를 다시 열 때 잔액 줄이 새로 받는다.
    // 만든 run(이미 짜는 중이면 그 run)을 여는 것과 실패를 남기는 것도 여기서 한다. 요청 중에 탭을 떠났다 오면
    // 입력 화면이 새로 붙어 그 화면의 mutate 콜백·error 는 이 요청을 모른다 — 진행 화면 대신 입력 화면이 남거나 실패가 조용히 묻혔다.
    onMutate: () => useCourseViewStore.getState().clearFail(mapId),
    onSuccess: (res) => {
      useCourseViewStore.getState().open(mapId, res.course_run_id)
      void invalidateCredits(queryClient)
      return queryClient.invalidateQueries({ queryKey: courseKeys.latest(mapId), refetchType: 'none' })
    },
    onError: (err, text) => {
      const running = inProgressRunId(err)
      if (running) useCourseViewStore.getState().open(mapId, running, true)
      else useCourseViewStore.getState().fail(mapId, err, text)
    },
  })
  // 새로 붙은 입력 화면도 진행 중인 요청을 알아야 「코스 짜기」를 두 번 보내지 않는다(크레딧이 두 번 빠진다).
  const creating = useIsMutating({ mutationKey: courseKeys.create(mapId) }) > 0
  return { ...mutation, isPending: mutation.isPending || creating }
}
