import { describe, expect, it } from 'vitest'

import { mapTapAction } from './mapTap'

const at = { lat: 37.5, lng: 127 }

describe('지도 빈 곳 누르기(#1028) — 탭과 상관없이 같다', () => {
  it('고른 것이 있으면 풀기만 한다(말풍선이 떠 있어도)', () => {
    expect(mapTapAction({ selected: true, bubbleOpen: false, at })).toBe('release')
    expect(mapTapAction({ selected: true, bubbleOpen: true, at })).toBe('release')
  })

  it('고른 것이 없으면 말풍선을 띄우고, 떠 있으면 닫는다 — 누르자마자 검색하지 않는다', () => {
    expect(mapTapAction({ selected: false, bubbleOpen: false, at })).toBe('open')
    expect(mapTapAction({ selected: false, bubbleOpen: true, at })).toBe('close')
  })

  it('누른 자리를 모르면 아무것도 하지 않는다', () => {
    expect(mapTapAction({ selected: false, bubbleOpen: false, at: null })).toBe('none')
  })
})
