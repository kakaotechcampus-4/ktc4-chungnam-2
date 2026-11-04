import { describe, expect, it } from 'vitest'

import { ApiError } from '@/api'

import { AD_TEXT, adButtonText, adCreditedText, adErrorAction, adOfferText, balanceText, showsReviewReward } from './model'

describe('남은 크레딧 표시(#982)', () => {
  it('상한은 응답의 max_balance — 「N/상한」', () => {
    expect(balanceText({ balance: 12, max_balance: 30 })).toBe('남은 크레딧 12/30')
  })

  it('max_balance 가 없으면(구버전 서버) N 만', () => {
    expect(balanceText({ balance: 12 })).toBe('남은 크레딧 12')
  })
})

describe('후기 보상 한 줄을 보일지(#982)', () => {
  it('잔액이 상한 아래면 보인다', () => {
    expect(showsReviewReward({ balance: 20, max_balance: 30 })).toBe(true)
  })

  it('잔액이 상한 이상이면 숨긴다 — 첫 후기 보상이 0이다', () => {
    expect(showsReviewReward({ balance: 30, max_balance: 30 })).toBe(false)
    expect(showsReviewReward({ balance: 35, max_balance: 30 })).toBe(false)
  })

  it('응답이 없거나(로딩) max_balance 가 없으면(구버전 서버) 보인다', () => {
    expect(showsReviewReward(undefined)).toBe(true)
    expect(showsReviewReward({ balance: 30 })).toBe(true)
  })
})

const apiError = (status: number, code: string, detail?: Record<string, unknown>) => new ApiError(status, { code, message: code, detail })

describe('광고 보고 충전 문구(#1039)', () => {
  it('고지 한 줄 — 보상과 남은 횟수(daily_max − used_today)는 응답 값', () => {
    expect(adOfferText({ reward: 10, daily_max: 3, used_today: 1 })).toBe('광고를 끝까지 보면 10 크레딧을 드려요. 오늘 2번 남았어요')
    expect(adOfferText({ reward: 7, daily_max: 5, used_today: 0 })).toBe('광고를 끝까지 보면 7 크레딧을 드려요. 오늘 5번 남았어요')
  })

  it('남은 횟수는 0 아래로 적지 않는다', () => {
    expect(adOfferText({ reward: 10, daily_max: 3, used_today: 4 })).toBe('광고를 끝까지 보면 10 크레딧을 드려요. 오늘 0번 남았어요')
  })

  it('버튼과 받은 뒤 토스트도 응답 값', () => {
    expect(adButtonText({ reward: 10 })).toBe('광고 보고 10 크레딧 받기')
    expect(adCreditedText(4)).toBe('4 크레딧을 받았어요')
  })
})

describe('광고 충전 오류 → 화면 행동(docs/errors.md AD_REWARD_*)', () => {
  it('AD_REWARD_UNAVAILABLE 는 토스트 없이 다시 읽기만', () => {
    expect(adErrorAction(apiError(409, 'AD_REWARD_UNAVAILABLE', { reason: 'off' }))).toEqual({ kind: 'refresh' })
    expect(adErrorAction(apiError(409, 'AD_REWARD_UNAVAILABLE', { reason: 'not_needed' }))).toEqual({ kind: 'refresh' })
  })

  it('AD_REWARD_LIMIT 는 detail.limit 으로 문구', () => {
    expect(adErrorAction(apiError(429, 'AD_REWARD_LIMIT', { limit: 3 }))).toEqual({ kind: 'toast', message: '오늘은 광고 충전을 3번 모두 썼어요' })
    expect(adErrorAction(apiError(429, 'AD_REWARD_LIMIT'))).toEqual({ kind: 'toast', message: '오늘은 광고 충전을 모두 썼어요' })
  })

  it('AD_REWARD_INVALID too_early 는 retry_after_s 뒤 한 번만 다시', () => {
    const early = apiError(409, 'AD_REWARD_INVALID', { reason: 'too_early', retry_after_s: 2 })
    expect(adErrorAction(early)).toEqual({ kind: 'retry', afterS: 2 })
    expect(adErrorAction(early, { retried: true })).toEqual({ kind: 'toast', message: AD_TEXT.failed })
  })

  it('AD_REWARD_INVALID expired 는 광고를 다시 봐 달라고', () => {
    expect(adErrorAction(apiError(409, 'AD_REWARD_INVALID', { reason: 'expired' }))).toEqual({ kind: 'toast', message: '광고를 다시 봐 주세요' })
  })

  it('그 밖(서버 오류·네트워크·이유 없는 INVALID)은 실패 토스트', () => {
    expect(adErrorAction(apiError(500, 'INTERNAL_ERROR'))).toEqual({ kind: 'toast', message: AD_TEXT.failed })
    expect(adErrorAction(new TypeError('Failed to fetch'))).toEqual({ kind: 'toast', message: AD_TEXT.failed })
    expect(adErrorAction(apiError(409, 'AD_REWARD_INVALID'))).toEqual({ kind: 'toast', message: AD_TEXT.failed })
  })
})
