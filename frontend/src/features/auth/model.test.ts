import { describe, expect, it } from 'vitest'

import { guestMergedMessage } from './model'

describe('guestMergedMessage (#485 게스트 → 카카오 전환 결과)', () => {
  it('이어졌으면 이어졌다고, 못 이었으면 기록이 남았다고 알린다', () => {
    expect(guestMergedMessage('true')).toContain('이어졌어요')
    expect(guestMergedMessage('false')).toContain('옮기지 못했어요')
  })
  it('게스트 전환이 아니면(쿼리 없음·다른 값) 알리지 않는다', () => {
    expect(guestMergedMessage(null)).toBeNull()
    expect(guestMergedMessage('1')).toBeNull()
  })
})
