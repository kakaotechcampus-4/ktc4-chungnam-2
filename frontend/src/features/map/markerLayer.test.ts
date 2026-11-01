import { afterEach, describe, expect, it, vi } from 'vitest'

import { createMarkerLayer, LABEL_MAX_LEVEL, mapFade } from './markerLayer'
import type { Pin } from './model'

/** 카카오 SDK 대신 쓰는 가짜. 위도·경도를 그대로 화면 좌표(px)로 쓴다 — lat 이 y, lng 가 x. */
function fakeMaps(level: number) {
  const listeners: (() => void)[] = []
  class LatLng {
    lat: number
    lng: number
    constructor(lat: number, lng: number) {
      this.lat = lat
      this.lng = lng
    }
  }
  class CustomOverlay {
    content: HTMLElement
    constructor(options: { content: HTMLElement }) {
      this.content = options.content
    }
    setMap(m: unknown) {
      if (m) document.body.appendChild(this.content)
      else this.content.remove()
    }
    setZIndex() {}
  }
  const map = {
    level,
    getLevel: () => map.level,
    getProjection: () => ({ containerPointFromCoords: (p: LatLng) => ({ x: p.lng, y: p.lat }) }),
  }
  const maps = {
    LatLng,
    CustomOverlay,
    event: {
      addListener: (_m: unknown, _t: string, fn: () => void) => listeners.push(fn),
      removeListener: () => {},
    },
  }
  return { maps: maps as unknown as typeof kakao.maps, map: map as unknown as kakao.maps.Map, raw: map, idle: () => listeners.forEach((f) => f()) }
}

const pin = (id: string, x: number, y: number, extra: Partial<Pin> = {}) =>
  ({
    id,
    place_name: `가게${id}`,
    kind: '일반',
    lat: y,
    lng: x,
    created_at: '2026-10-01T00:00:00Z',
    reaction_summary: { like: 0, against: 0 },
    ...extra,
  }) as unknown as Pin

/** 이름표가 보이는지(겹침 정리로 숨긴 것은 visibility:hidden). */
const labelShown = (id: string) => {
  const el = [...document.querySelectorAll<HTMLElement>('button')].find((b) => b.getAttribute('aria-label')?.startsWith(`가게${id} `))
  const label = el?.querySelector<HTMLElement>('[data-pin-name]')
  return Boolean(label) && label!.style.visibility !== 'hidden'
}

afterEach(() => {
  document.body.innerHTML = ''
  vi.restoreAllMocks()
})

describe('지도 핀 이름표', () => {
  it('떨어진 핀은 누르지 않아도 이름표가 다 보인다', () => {
    const { maps, map } = fakeMaps(4)
    createMarkerLayer(maps, map, () => {}).sync([pin('1', 0, 100), pin('2', 300, 100)], 4)
    expect(labelShown('1')).toBe(true)
    expect(labelShown('2')).toBe(true)
  })

  it('이름표가 겹치면 확정 핀 쪽만 남는다', () => {
    const { maps, map } = fakeMaps(4)
    createMarkerLayer(maps, map, () => {}).sync([pin('1', 100, 100), pin('2', 120, 102, { kind: '확정' })], 4)
    expect(labelShown('2')).toBe(true)
    expect(labelShown('1')).toBe(false)
  })

  it('고른 핀은 겹쳐도 이름이 보이고, 그 자리의 다른 이름표가 비킨다', () => {
    const { maps, map } = fakeMaps(4)
    const layer = createMarkerLayer(maps, map, () => {})
    layer.sync([pin('1', 100, 100), pin('2', 120, 102, { kind: '확정' })], 4)
    layer.select('1')
    expect(labelShown('1')).toBe(true)
    expect(labelShown('2')).toBe(false)
  })

  it(`멀리 보면(레벨 ${LABEL_MAX_LEVEL + 1}) 고른 핀만 이름이 남고, 다시 가까이 오면 돌아온다`, () => {
    const { maps, map, raw, idle } = fakeMaps(LABEL_MAX_LEVEL + 1)
    const layer = createMarkerLayer(maps, map, () => {})
    layer.sync([pin('1', 0, 100), pin('2', 300, 100)], 4)
    layer.select('2')
    expect(labelShown('1')).toBe(false)
    expect(labelShown('2')).toBe(true)

    raw.level = LABEL_MAX_LEVEL
    idle()
    expect(labelShown('1')).toBe(true)
  })
})

describe('바탕 지도 옅게', () => {
  it('멀리 보면 그대로이고, 이름표가 뜨는 레벨부터 가까이 갈수록 옅어진다', () => {
    expect(mapFade(LABEL_MAX_LEVEL + 3)).toBe(0)
    expect(mapFade(LABEL_MAX_LEVEL + 1)).toBe(0)
    const steps = [LABEL_MAX_LEVEL, LABEL_MAX_LEVEL - 1, LABEL_MAX_LEVEL - 2].map(mapFade)
    expect(steps[0]).toBeGreaterThan(0)
    expect(steps[1]).toBeGreaterThan(steps[0])
    expect(steps[2]).toBeGreaterThan(steps[1])
    expect(mapFade(1)).toBe(1)
  })
})
