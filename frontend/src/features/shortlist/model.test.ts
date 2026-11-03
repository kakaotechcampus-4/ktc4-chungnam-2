import { describe, expect, it } from 'vitest'

import { routableCount, type ShortlistItemDto } from './model'

const item = (source: 'db' | 'live') => ({ pin: { source } }) as unknown as ShortlistItemDto

describe('위치를 아는 확정 장소 수(#1127 리뷰 — 동선 보기·AI 코스가 같이 쓴다)', () => {
  it('실시간 핀은 좌표를 저장하지 않아 세지 않는다', () => {
    expect(routableCount([])).toBe(0)
    expect(routableCount([item('db'), item('live'), item('db')])).toBe(2)
  })
})
