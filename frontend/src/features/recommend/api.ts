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
  RunSummaryDto,
} from './model'

export type Center = { lat: number; lng: number }

/** center 를 주면 「근처 정예 수」를 run 생성과 같은 기준(그 점 주변)으로 센다(#1331). */
/** radiusM 은 「찾는 범위」에서 고른 반경 — 근처 정예 수를 그 반경으로 센다(#1416). 중심이 있을 때만 뜻이 있다. */
export const fetchReadiness = (mapId: string, center: Center | null, radiusM?: number) =>
  api<Partial<Record<RecommendCategory, ReadinessDto>>>(
    `/maps/${mapId}/recommend/readiness${center ? `?center_lat=${center.lat}&center_lng=${center.lng}${radiusM ? `&radius_m=${radiusM}` : ''}` : ''}`,
  )

/**
 * 추천 시작(#845) — 사유 정리(모델)와 첫 검색을 한 요청에서 끝내고 done run 을 받는다(execute).
 * key 는 한 번 누른 시도의 표시다(#811). 같은 시도의 재전송은 같은 키로, 다시 누르면 새 키로 보낸다.
 * center 는 누른 순간 보고 있던 지도 가운데 — 후보를 찾는 원의 중심이다(#1331). 서버가 run 에 저장해 다시 추천·넓히기도 같은 점을 쓴다.
 */
export const createRun = (mapId: string, category: RecommendCategory, key: string, center: Center | null = null, radiusM?: number) =>
  api<RecommendRunDto>(`/maps/${mapId}/runs`, {
    method: 'POST',
    headers: { 'Idempotency-Key': key },
    // radius_m 은 「찾는 범위」에서 고른 반경(#1416). 없으면 서버 기본값이다.
    body: JSON.stringify({ category, execute: true, center, ...(radiusM ? { radius_m: radiusM } : {}) }),
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

/** 내가 이 지도에서 요청한 지난 추천, 최근순(#482). 다른 구성원의 run 은 없다(가드레일 1). */
export const fetchRunHistory = (mapId: string) => api<RunSummaryDto[]>(`/maps/${mapId}/runs`)
