import { describe, expect, it } from 'vitest'

import { badgeText, mapOrigin, notificationTarget } from './model'

describe('알림 (#483)', () => {
  it('배지는 0이면 없고 99를 넘으면 99+', () => {
    expect([badgeText(0), badgeText(7), badgeText(99), badgeText(120)]).toEqual([null, '7', '99', '99+'])
  })
  it('누르면 갈 곳 — 핀 반응은 그 핀, 삭제된 지도는 목록', () => {
    expect(notificationTarget({ type: 'pin_reaction', map_id: 'm1', pin_id: 'p 1' })).toBe('/maps/m1?pin=p%201')
    expect(notificationTarget({ type: 'map_deleted', map_id: 'm1' })).toBe('/')
    expect(notificationTarget({ type: 'member_joined', map_id: 'm1' })).toBe('/maps/m1')
  })
  it('지도 화면이면 이 지도와 다른 지도를 나누고, 목록 화면이면 나누지 않는다 (#1036)', () => {
    expect([mapOrigin({ map_id: 'm1' }, 'm1'), mapOrigin({ map_id: 'm2' }, 'm1'), mapOrigin({ map_id: 'm1' }, undefined)]).toEqual(['here', 'other', 'all'])
  })
})
