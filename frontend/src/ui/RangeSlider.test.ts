import { describe, expect, it } from 'vitest'

import { snapToMark } from './RangeSlider'

describe('snapToMark — 끌 때 눈금 근처에서 붙는다(#1416)', () => {
  const marks = [2000, 3000, 4000]
  it('가장 가까운 눈금이 거리 안이면 그 눈금, 밖이면 값 그대로', () => {
    expect(snapToMark(3100, marks, 150)).toBe(3000)
    expect(snapToMark(2850, marks, 150)).toBe(3000)
    expect(snapToMark(3200, marks, 150)).toBe(3200)
    expect(snapToMark(3600, marks, 150)).toBe(3600)
  })
  it('눈금이 없거나 거리가 0이면 붙지 않는다', () => {
    expect(snapToMark(3100, [], 150)).toBe(3100)
    expect(snapToMark(3100, marks, 0)).toBe(3100)
  })
})
