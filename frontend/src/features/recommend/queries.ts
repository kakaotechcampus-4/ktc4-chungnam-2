import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'

import { useAiStore } from './aiStore'
import { ApiError } from '@/api'
import { pinKeys } from '@/features/map/queries'
import type { Pin } from '@/features/map/model'

import {
  confirmRegions,
  createRun,
  executeRun,
  fetchEvidence,
  fetchReadiness,
  fetchResult,
  patchEvidence,
  publishCandidate,
  retryRun,
  widenRun,
} from './api'
import type { EvidencePatchRequest, RecommendCategory, RecommendResultDto, RecommendRunDto } from './model'

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

export function useWidenMutation(mapId: string) {
  return useRunMutation(mapId, (runId: string) => widenRun(runId))
}

export function useRetryMutation(mapId: string) {
  return useRunMutation(mapId, (runId: string) => retryRun(runId))
}

/**
 * 추천 결과. 실행 중이면 2초마다 다시 본다(개인 채널 SSE 가 먼저 오면 그걸로 끝난다).
 * 0곳(NO_RESULTS)·실패(RECOMMEND_FAILED)는 답이 정해진 것이라 다시 묻지 않는다.
 */
export function useResultQuery(run: RecommendRunDto) {
  return useQuery({
    queryKey: [...recommendKeys.result(run.id), run.attempt_no, run.default_radius_walk_min],
    queryFn: () => fetchResult(run.id),
    retry: (count, err) => !(err instanceof ApiError && ['NO_RESULTS', 'RECOMMEND_FAILED', 'FORBIDDEN'].includes(err.code)) && count < 1,
    refetchInterval: run.status === 'executing' ? 2000 : false,
  })
}

/**
 * 「지도에 올리기」 — 나만 보던 후보를 모두에게 공개한다(5-5-1, 가드레일 1). 만든 핀을 지도에 바로 넣고 후보를 '올림'으로 표시한다.
 * 이유·조건별 체크·구성원 충족은 핀으로 옮겨 가서 게시된 뒤에도 남는다(가드레일 5).
 */
export function usePublishMutation(mapId: string, run: RecommendRunDto) {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (candidateId: string) => publishCandidate(candidateId),
    onSuccess: (pin, candidateId) => {
      queryClient.setQueryData<Pin[]>(pinKeys.list(mapId), (pins) => pins && (pins.some((p) => p.id === pin.id) ? pins : [...pins, pin]))
      queryClient.setQueriesData<RecommendResultDto>({ queryKey: recommendKeys.result(run.id) }, (r) =>
        r && { ...r, candidates: r.candidates.map((c) => (c.id === candidateId ? { ...c, visibility: 'published', published_pin_id: pin.id } : c)) },
      )
    },
  })
}
