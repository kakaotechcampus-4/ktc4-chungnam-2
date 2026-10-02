import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'

import { useAiStore } from './aiStore'
import { confirmRegions, createRun, executeRun, fetchEvidence, fetchReadiness, patchEvidence } from './api'
import type { EvidencePatchRequest, RecommendCategory, RecommendRunDto } from './model'

export const recommendKeys = {
  readiness: (mapId: string) => ['recommend', mapId, 'readiness'] as const,
  evidence: (runId: string) => ['runs', runId, 'evidence'] as const,
  result: (runId: string) => ['runs', runId, 'result'] as const,
}

/** 카테고리별 추천 가능 여부(5-4). 의견이 바뀌면 달라지니 탭을 열 때마다 다시 본다. */
export function useReadinessQuery(mapId: string) {
  return useQuery({ queryKey: recommendKeys.readiness(mapId), queryFn: () => fetchReadiness(mapId), refetchOnMount: 'always' })
}

/** run 을 바꾸는 요청은 모두 응답(RecommendRun)으로 화면의 run 을 갈아 끼운다. */
function useRunMutation<V>(mapId: string, fn: (v: V) => Promise<RecommendRunDto>) {
  const setRun = useAiStore((s) => s.setRun)
  return useMutation({ mutationFn: fn, onSuccess: (run) => setRun(mapId, run) })
}

export function useCreateRunMutation(mapId: string) {
  return useRunMutation(mapId, (category: RecommendCategory) => createRun(mapId, category))
}

export function useExecuteRunMutation(mapId: string) {
  return useRunMutation(mapId, (runId: string) => executeRun(runId))
}

export function useEvidenceQuery(runId: string) {
  return useQuery({ queryKey: recommendKeys.evidence(runId), queryFn: () => fetchEvidence(runId) })
}

/** 근거 빼기(−)·되돌리기·직접 추가(+). 응답이 근거 전체라 그대로 덮는다. */
export function usePatchEvidenceMutation(runId: string) {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (body: EvidencePatchRequest) => patchEvidence(runId, body),
    onSuccess: (lines) => queryClient.setQueryData(recommendKeys.evidence(runId), lines),
  })
}

/** 지역 확인(5-6-1). 반경 사유끼리 안 겹치면 409 REGION_CONFLICT — 부르는 쪽이 확인창을 띄운다. */
export function useConfirmRegionsMutation(runId: string) {
  return useMutation({ mutationFn: (acceptUnion: boolean) => confirmRegions(runId, acceptUnion) })
}
