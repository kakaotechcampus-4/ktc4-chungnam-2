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

/**
 * 「남은 크레딧 12/30」. 상한은 GET /credits/me 의 max_balance(#981) — 없으면(구버전 서버) 「남은 크레딧 12」.
 * 화면은 상한을 판단하지 않고 받은 두 숫자를 그대로 적는다.
 */
export const balanceText = ({ balance, max_balance }: Pick<CreditBalanceDto, 'balance'> & { max_balance?: number }) =>
  max_balance === undefined ? `남은 크레딧 ${balance}` : `남은 크레딧 ${balance}/${max_balance}`

/**
 * 새 후기 작성 시트의 한 줄(docs/credits-reviews.md 5절 「화면 문구」). 보상은 GET /credits/me 의 review_reward, 아직 없으면 숫자 없이.
 * 상한 근처라 덜 받는 경우는 따로 알리지 않는다(2026-11-01 결정). 가득 차 0을 받는 경우는 줄을 숨긴다(showsReviewReward).
 */
export const reviewRewardText = (reviewReward?: number) =>
  reviewReward === undefined ? '후기를 작성하면 크레딧이 충전돼요' : `후기를 작성하면 ${reviewReward} 크레딧이 충전돼요`

/**
 * 새 후기 작성 시트에 보상 한 줄을 보일지(docs/credits-reviews.md 5절 「화면 문구」, #982).
 * 잔액이 상한(max_balance) 이상이면 첫 후기의 보상이 0이라 약속을 지킬 수 없어 숨긴다 — 대신할 문구는 없다.
 * 응답이 아직 없거나(로딩) max_balance 가 없으면(구버전 서버) 보인다.
 */
export const showsReviewReward = (credits?: Pick<CreditBalanceDto, 'balance'> & { max_balance?: number }) =>
  credits?.max_balance === undefined || credits.balance < credits.max_balance

/** 「크레딧이 부족해요. 후기를 쓰면 10 크레딧을 드려요」. 보상은 GET /credits/me 의 review_reward, 아직 없으면 숫자 없이. */
export const insufficientText = (reviewReward?: number) =>
  reviewReward === undefined ? '크레딧이 부족해요. 후기를 쓰면 크레딧을 드려요' : `크레딧이 부족해요. 후기를 쓰면 ${reviewReward} 크레딧을 드려요`
