import { describe, expect, it } from 'vitest'

import { badgeText, mapOrigin, markReadLocally, notificationTarget, type NotificationDto } from './model'

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

describe('읽음을 화면에 먼저 적기(#1676)', () => {
  const n = (id: string, read: boolean) => ({ id, read }) as NotificationDto
  const data = {
    pageParams: [undefined, 'c1'],
    pages: [
      { items: [n('a', false), n('b', true)], unread_count: 5 },
      { items: [n('c', false)], unread_count: 5 },
    ],
  }
  it('한 건이면 그 줄만 읽음, 배지는 새로 읽은 수만큼 줄인다(받은 쪽 밖의 안 읽은 알림이 있다)', () => {
    const next = markReadLocally(data, ['a', 'b'])
    expect(next.pages[0].items.map((x) => x.read)).toEqual([true, true])
    expect(next.pages[1].items[0].read).toBe(false)
    expect(next.pages[0].unread_count).toBe(4)
  })
  it('전부 읽음이면 모든 줄이 읽음, 배지는 0', () => {
    const next = markReadLocally(data)
    expect(next.pages.flatMap((p) => p.items).every((x) => x.read)).toBe(true)
    expect(next.pages[0].unread_count).toBe(0)
  })
})
