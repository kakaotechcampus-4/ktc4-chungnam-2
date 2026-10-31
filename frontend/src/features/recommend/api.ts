import { api } from '@/api'
import type { PinDto } from '@/features/map/model'

import type {
  EvidenceLineDto,
  EvidencePatchRequest,
  ReadinessDto,
  RecommendCategory,
  RecommendResultDto,
  RecommendRunDto,
  RegionDto,
} from './model'

export const fetchReadiness = (mapId: string) =>
  api<Partial<Record<RecommendCategory, ReadinessDto>>>(`/maps/${mapId}/recommend/readiness`)

/**
 * 추천 시작(#845) — 사유 정리(모델)와 첫 검색을 한 요청에서 끝내고 done run 을 받는다(execute).
 * key 는 한 번 누른 시도의 표시다(#811). 같은 시도의 재전송은 같은 키로, 다시 누르면 새 키로 보낸다.
 */
export const createRun = (mapId: string, category: RecommendCategory, key: string) =>
  api<RecommendRunDto>(`/maps/${mapId}/runs`, {
    method: 'POST',
    headers: { 'Idempotency-Key': key },
    body: JSON.stringify({ category, execute: true }),
  })

export const fetchEvidence = (runId: string) => api<EvidenceLineDto[]>(`/runs/${runId}/evidence`)

export const patchEvidence = (runId: string, body: EvidencePatchRequest) =>
  api<EvidenceLineDto[]>(`/runs/${runId}/evidence`, { method: 'PATCH', body: JSON.stringify(body) })

export const confirmRegions = (runId: string, acceptUnion: boolean) =>
  api<RegionDto[]>(`/runs/${runId}/regions/confirm`, { method: 'POST', body: JSON.stringify({ accept_union: acceptUnion }) })

export const executeRun = (runId: string) => api<RecommendRunDto>(`/runs/${runId}/execute`, { method: 'POST' })

export const fetchResult = (runId: string) => api<RecommendResultDto>(`/runs/${runId}/result`)

export const widenRun = (runId: string) => api<RecommendRunDto>(`/runs/${runId}/widen`, { method: 'POST' })

export const retryRun = (runId: string) => api<RecommendRunDto>(`/runs/${runId}/retry`, { method: 'POST' })

export const publishCandidate = (candidateId: string) => api<PinDto>(`/candidates/${candidateId}/publish`, { method: 'POST' })
