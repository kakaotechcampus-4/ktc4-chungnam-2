import { describe, expect, it } from 'vitest'

import { REGION_CODES, REGIONS } from '@/features/maps/regions'

import seoul from './regionBoundaries/11.json'
import {
  boundaryCorners,
  circleExtremes,
  circleOutsideRegion,
  distanceToBoundaryM,
  pointInRegion,
  type RegionBoundary,
} from './regionGeo'

// 위도 37~37.1, 경도 127~127.1 네모(약 11km × 9km)에 가운데 구멍 하나, 멀리 떨어진 섬 하나.
const square: RegionBoundary = [
  [
    [
      [37, 127],
      [37, 127.1],
      [37.1, 127.1],
      [37.1, 127],
    ],
    [
      [37.04, 127.04],
      [37.06, 127.04],
      [37.06, 127.06],
      [37.04, 127.06],
    ],
  ],
  [
    [
      [36.5, 127.5],
      [36.5, 127.51],
      [36.51, 127.51],
      [36.51, 127.5],
    ],
  ],
]

describe('pointInRegion', () => {
  it('안·밖·구멍·섬', () => {
    expect(pointInRegion({ lat: 37.02, lng: 127.02 }, square)).toBe(true)
    expect(pointInRegion({ lat: 37.2, lng: 127.05 }, square)).toBe(false)
    expect(pointInRegion({ lat: 37.05, lng: 127.05 }, square)).toBe(false)
    expect(pointInRegion({ lat: 36.505, lng: 127.505 }, square)).toBe(true)
  })
})

describe('circleOutsideRegion', () => {
  it('가운데가 밖이어도 원이 경계에 걸치면 밖이 아니다', () => {
    // 북쪽 경계(37.1)에서 약 2.2km 위
    const near = { lat: 37.12, lng: 127.05 }
    expect(distanceToBoundaryM(near, square)).toBeCloseTo(2224, -1)
    expect(circleOutsideRegion(near, 3000, square)).toBe(false)
    expect(circleOutsideRegion(near, 2000, square)).toBe(true)
  })

  it('멀리 떨어진 원은 밖이고, 안에 있는 원은 밖이 아니다', () => {
    expect(circleOutsideRegion({ lat: 37.5, lng: 127.05 }, 3000, square)).toBe(true)
    expect(circleOutsideRegion({ lat: 37.02, lng: 127.02 }, 3000, square)).toBe(false)
  })

  it('구멍 가운데는 밖이지만 구멍 가장자리까지 반경 안이면 밖이 아니다', () => {
    expect(circleOutsideRegion({ lat: 37.05, lng: 127.05 }, 3000, square)).toBe(false)
  })
})

describe('boundaryCorners', () => {
  it('외곽 고리들을 감싼다', () => {
    expect(boundaryCorners(square)).toEqual([
      { lat: 36.5, lng: 127 },
      { lat: 37.1, lng: 127.51 },
    ])
  })
})

describe('circleExtremes', () => {
  it('네 점이 가운데에서 반경만큼 떨어져 있다', () => {
    const c = { lat: 37.05, lng: 127.05 }
    for (const p of circleExtremes(c, 3000)) {
      const d = distanceToBoundaryM(c, [[[[p.lat, p.lng], [p.lat, p.lng], [p.lat, p.lng]]]])
      expect(d).toBeCloseTo(3000, -1)
    }
  })
})

describe('경계 파일', () => {
  it('시·도마다 경계 파일이 있다', () => {
    const files = import.meta.glob('./regionBoundaries/*.json')
    for (const region of REGIONS) {
      expect(files[`./regionBoundaries/${REGION_CODES[region.label]}.json`], region.label).toBeDefined()
    }
  })

  it('서울 시청은 서울 안, 대전 시청은 서울 밖이다', () => {
    const boundary = seoul as RegionBoundary
    const at = (label: string) => REGIONS.find((r) => r.label === label)!
    expect(pointInRegion(at('서울특별시'), boundary)).toBe(true)
    expect(circleOutsideRegion(at('대전광역시'), 3000, boundary)).toBe(true)
    expect(circleOutsideRegion(at('인천광역시'), 3000, boundary)).toBe(true)
  })
})
