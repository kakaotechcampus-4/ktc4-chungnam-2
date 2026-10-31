import { useIsMutating, useMutation, useQuery, useQueryClient } from '@tanstack/react-query'

import { useAiStore } from './aiStore'
import { ApiError } from '@/api'
import { invalidateCredits } from '@/features/credits/queries'
import { pinKeys } from '@/features/map/queries'
import type { Pin } from '@/features/map/model'
import { showToast } from '@/features/shell/toast'

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
import { runErrorMessage, type EvidencePatchRequest, type RecommendCategory, type RecommendResultDto, type RecommendRunDto } from './model'

export const recommendKeys = {
  readiness: (mapId: string) => ['recommend', mapId, 'readiness'] as const,
  evidence: (runId: string) => ['runs', runId, 'evidence'] as const,
  result: (runId: string) => ['runs', runId, 'result'] as const,
  evidencePatch: (runId: string) => ['runs', runId, 'evidence-patch'] as const,
}

/** 카테고리별 추천 가능 여부(5-4). 의견이 바뀌면 달라지니 탭을 열 때마다 다시 본다. */
export function useReadinessQuery(mapId: string) {
  return useQuery({ queryKey: recommendKeys.readiness(mapId), queryFn: () => fetchReadiness(mapId), refetchOnMount: 'always' })
}

/** 서버가 아직 같은 키의 첫 요청을 처리 중이다(409 REQUEST_IN_PROGRESS) — 진행 표시를 두고 같은 키로 다시 묻는다(#811). */
const IN_PROGRESS_WAIT_MS = 2000
/** 서버 처리 상한(90초)을 넘기면 그만 묻는다. */
const IN_PROGRESS_TRIES = 45
const inProgress = (err: unknown) => err instanceof ApiError && err.code === 'REQUEST_IN_PROGRESS'

/**
 * 「추천받기」 — 사유 정리와 첫 검색을 한 번에 하고 결과로 간다(#845). 근거 확인 화면을 거치지 않는다.
 * 시도마다 키를 하나 만든다: 처리 중이라 다시 묻는 것(retry)은 같은 변수 = 같은 키다.
 */
export function useCreateRunMutation(mapId: string) {
  const setRun = useAiStore((s) => s.setRun)
  const queryClient = useQueryClient()
  const mutation = useMutation({
    mutationFn: ({ category, key }: { category: RecommendCategory; key: string }) => createRun(mapId, category, key),
    retry: (count, err) => inProgress(err) && count < IN_PROGRESS_TRIES,
    retryDelay: IN_PROGRESS_WAIT_MS,
    onSuccess: (run) => {
      setRun(mapId, run)
      // 「추천받기」 1번에 크레딧을 쓴다(#432). 다시 추천·넓히기·근거 고치기는 쓰지 않아 아래 훅은 다시 받지 않는다.
      void invalidateCredits(queryClient)
    },
  })
  const start = (category: RecommendCategory, opts?: { onError?: (err: Error) => void }) =>
    mutation.mutate({ category, key: crypto.randomUUID() }, opts)
  return { ...mutation, start }
}

/**
 * 추천을 실제로 돌리는 요청(실행·다시 추천·반경 넓히기, #349).
 * v1 서버는 진행 이벤트를 보내지 않고 요청 안에서 끝낸다(docs/events.md) — 그래서 보내는 순간 run 을 '실행 중'으로 두어
 * 탭이 '진행 중' 시트를 그리게 하고, 응답이 오면 그 run 으로 갈아 끼운다.
 * 500 RECOMMEND_FAILED 는 run 을 '실패'로 두어 '추천 실패' 화면을 띄운다. 그 밖의 실패는 원래 상태로 되돌리고 알린다.
 * 이 처리(안내 포함)를 버튼이 아니라 여기에 두는 이유: 누른 화면(근거 확인·결과·0곳)은 '실행 중'이 되는 순간
 * 사라져서 그 화면의 mutate 콜백은 불리지 않는다.
 */
function useRunningMutation(mapId: string, fn: (runId: string) => Promise<RecommendRunDto>) {
  const setRun = useAiStore((s) => s.setRun)
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (run: RecommendRunDto) => fn(run.id),
    onMutate: (run) => {
      setRun(mapId, { ...run, status: 'executing' })
      return { before: run }
    },
    onSuccess: (run) => {
      // 실패 뒤 「다시 시도」로 성공하면 같은 run·같은 시도 번호라 예전(실패) 결과가 캐시에 남아 있을 수 있다 — 새로 받는다.
      void queryClient.invalidateQueries({ queryKey: recommendKeys.result(run.id) })
      setRun(mapId, run)
    },
    onError: (err, _run, ctx) => {
      if (!ctx) return
      if (err instanceof ApiError && err.code === 'RECOMMEND_FAILED') {
        setRun(mapId, { ...ctx.before, status: 'failed' })
        return
      }
      setRun(mapId, ctx.before)
      showToast(runErrorMessage(err))
    },
  })
}

export function useExecuteRunMutation(mapId: string) {
  return useRunningMutation(mapId, executeRun)
}

export function useEvidenceQuery(runId: string) {
  return useQuery({ queryKey: recommendKeys.evidence(runId), queryFn: () => fetchEvidence(runId) })
}

/**
 * 근거 빼기(×)·되돌리기·직접 추가(＋). 응답이 근거 전체라 그대로 덮는다.
 * 고친 것은 다음 「다시 추천」 때 쓰인다 — 그 전에 다시 추천하면 순서가 꼬이니 진행 중인지 밖에서 본다(useEvidencePatching).
 */
export function usePatchEvidenceMutation(runId: string) {
  const queryClient = useQueryClient()
  return useMutation({
    mutationKey: recommendKeys.evidencePatch(runId),
    mutationFn: (body: EvidencePatchRequest) => patchEvidence(runId, body),
    onSuccess: (lines) => queryClient.setQueryData(recommendKeys.evidence(runId), lines),
  })
}

/** 이 run 의 근거를 고치는 요청이 아직 끝나지 않았는지(「다시 추천」을 막는다, #849). */
export function useEvidencePatching(runId: string) {
  return useIsMutating({ mutationKey: recommendKeys.evidencePatch(runId) }) > 0
}

/** 지역 확인(5-6-1). 반경 사유끼리 안 겹치면 409 REGION_CONFLICT — 부르는 쪽이 확인창을 띄운다. */
export function useConfirmRegionsMutation(runId: string) {
  return useMutation({ mutationFn: (acceptUnion: boolean) => confirmRegions(runId, acceptUnion) })
}

export function useWidenMutation(mapId: string) {
  return useRunningMutation(mapId, widenRun)
}

export function useRetryMutation(mapId: string) {
  return useRunningMutation(mapId, retryRun)
}

/**
 * 추천 결과. 실행 중이면 2초마다 다시 본다. v1 서버는 실행 요청 안에서 끝내므로 보통은 한 번에 받는다
 * (run.candidates_ready·run.failed 이벤트를 기다리지 않는다 — docs/events.md).
 * 0곳(NO_RESULTS)·실패(RECOMMEND_FAILED)는 답이 정해진 것이라 다시 묻지 않는다.
 */
/** run 이 없으면 묻지 않는다 — 지도(MapLayout)가 AI 후보를 그리려고 같은 캐시를 볼 때(#843). */
export function useResultQuery(run: RecommendRunDto | undefined) {
  return useQuery({
    queryKey: [...recommendKeys.result(run?.id ?? ''), run?.attempt_no, run?.default_radius_walk_min],
    queryFn: () => fetchResult(run!.id),
    retry: (count, err) => !(err instanceof ApiError && ['NO_RESULTS', 'RECOMMEND_FAILED', 'FORBIDDEN'].includes(err.code)) && count < 1,
    // v1 은 실행이 요청 안에서 끝난다 — 실행 중에 결과를 물으면 끝나기 전 상태(0곳 등)가 올 수 있어 묻지 않는다(#349).
    enabled: !!run && run.status !== 'executing' && run.status !== 'failed',
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
