import { describe, expect, it } from 'vitest'

import { guestMergedMessage, inviteToken } from './model'

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

describe('inviteToken (#1631 초대 링크 붙여넣기)', () => {
  const token = 'Qm3xV8kR2pLw9TnYc4HdJs7EaUf1BgZo5Ni6Xy0WtKe'
  it('초대 링크에서 토큰만 꺼낸다', () => {
    expect(inviteToken(`https://pingopingo.app/invites/${token}`)).toBe(token)
    expect(inviteToken(`  http://localhost:5173/invites/${token}?from=kakao#x \n`)).toBe(token)
  })
  it('토큰만 붙여 넣어도 받는다', () => {
    expect(inviteToken(token)).toBe(token)
  })
  it('초대 링크가 아니면 받지 않는다', () => {
    expect(inviteToken('https://naver.me/abc')).toBeNull()
    expect(inviteToken('부산 여행')).toBeNull()
    expect(inviteToken('')).toBeNull()
  })
})
