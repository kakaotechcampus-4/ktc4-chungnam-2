import { describe, expect, it } from 'vitest'

import { balanceText } from './model'

describe('남은 크레딧 표시(#982)', () => {
  it('상한은 응답의 max_balance — 「N/상한」', () => {
    expect(balanceText({ balance: 12, max_balance: 30 })).toBe('남은 크레딧 12/30')
  })

  it('max_balance 가 없으면(구버전 서버) N 만', () => {
    expect(balanceText({ balance: 12 })).toBe('남은 크레딧 12')
  })
})
