import type { components } from '@pingo/contracts/src/types/api'

import { ApiError } from '@/api'

export type CreditBalanceDto = components['schemas']['CreditBalance']
/** 크레딧을 쓰는 AI 실행(CreditBalance.prices 의 키). 가격 숫자는 응답에서만 읽는다(docs/credits-reviews.md 3.2). */
export type CreditFeature = keyof CreditBalanceDto['prices']

/**
 * 크레딧 때문에 AI 실행을 못 하는 이유(#432). 게스트는 403 GUEST_NOT_ALLOWED, 잔액 부족은 402 CREDIT_INSUFFICIENT.
 * 게스트가 받을 크레딧은 그 오류의 detail.initial_credits 에서만 온다 — 게스트는 GET /credits/me 를 받을 수 없다(3.5절).
 * 크레딧과 무관한 오류면 null.
 */
export type CreditBlock = { kind: 'guest'; initialCredits?: number } | { kind: 'insufficient' }

export function creditBlock(err: unknown): CreditBlock | null {
  if (!(err instanceof ApiError)) return null
  if (err.code === 'CREDIT_INSUFFICIENT') return { kind: 'insufficient' }
  if (err.code === 'GUEST_NOT_ALLOWED') {
    const n = err.detail?.initial_credits
    return { kind: 'guest', initialCredits: typeof n === 'number' ? n : undefined }
  }
  return null
}

/** 「카카오로 로그인하면 30 크레딧을 드려요」. 숫자가 안 오면(구버전 서버) 숫자 없이. */
export const guestCreditText = (initialCredits?: number) =>
  initialCredits === undefined ? '카카오로 로그인하면 크레딧을 드려요' : `카카오로 로그인하면 ${initialCredits} 크레딧을 드려요`

/** 「크레딧이 부족해요. 후기를 쓰면 10 크레딧을 드려요」. 보상은 GET /credits/me 의 review_reward, 아직 없으면 숫자 없이. */
export const insufficientText = (reviewReward?: number) =>
  reviewReward === undefined ? '크레딧이 부족해요. 후기를 쓰면 크레딧을 드려요' : `크레딧이 부족해요. 후기를 쓰면 ${reviewReward} 크레딧을 드려요`
