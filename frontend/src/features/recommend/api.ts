import { api } from '@/api'

import type {
  CandidateDto,
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

export const createRun = (mapId: string, category: RecommendCategory) =>
  api<RecommendRunDto>(`/maps/${mapId}/runs`, { method: 'POST', body: JSON.stringify({ category }) })

export const fetchEvidence = (runId: string) => api<EvidenceLineDto[]>(`/runs/${runId}/evidence`)

export const patchEvidence = (runId: string, body: EvidencePatchRequest) =>
  api<EvidenceLineDto[]>(`/runs/${runId}/evidence`, { method: 'PATCH', body: JSON.stringify(body) })

export const confirmRegions = (runId: string, acceptUnion: boolean) =>
  api<RegionDto[]>(`/runs/${runId}/regions/confirm`, { method: 'POST', body: JSON.stringify({ accept_union: acceptUnion }) })

export const executeRun = (runId: string) => api<RecommendRunDto>(`/runs/${runId}/execute`, { method: 'POST' })

export const fetchResult = (runId: string) => api<RecommendResultDto>(`/runs/${runId}/result`)

export const widenRun = (runId: string) => api<RecommendRunDto>(`/runs/${runId}/widen`, { method: 'POST' })

export const retryRun = (runId: string) => api<RecommendRunDto>(`/runs/${runId}/retry`, { method: 'POST' })

export const publishCandidate = (candidateId: string) =>
  api<CandidateDto & Record<string, unknown>>(`/candidates/${candidateId}/publish`, { method: 'POST' })
