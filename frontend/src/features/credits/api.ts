import { api } from '@/api'

import type { AdClaimDto, AdSessionDto, CreditBalanceDto } from './model'

/** 내 잔액·가격·후기 보상(#432). 게스트는 403 GUEST_NOT_ALLOWED. */
export const fetchCredits = () => api<CreditBalanceDto>('/credits/me')

/**
 * 광고 보고 충전 — 세션 열기(#1037, docs/credits-reviews.md 3.7). 받지 않은 세션이 있으면 서버가 그것을 돌려준다.
 * 열 수 없으면 409 AD_REWARD_UNAVAILABLE, 오늘 다 열었으면 429 AD_REWARD_LIMIT(오류 → 화면 행동은 model 의 adErrorAction).
 */
export const openAdSession = () => api<AdSessionDto>('/credits/ad-sessions', { method: 'POST' })

/** 광고 보고 충전 — 보상 받기. 연 지 claim_after_s 전이면 409 AD_REWARD_INVALID(too_early). 이미 받았으면 처음 결과 그대로. */
export const claimAdSession = (adSessionId: string) =>
  api<AdClaimDto>(`/credits/ad-sessions/${encodeURIComponent(adSessionId)}/claim`, { method: 'POST' })
