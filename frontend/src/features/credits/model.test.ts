import { describe, expect, it } from 'vitest'

import { balanceText, showsReviewReward } from './model'

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
