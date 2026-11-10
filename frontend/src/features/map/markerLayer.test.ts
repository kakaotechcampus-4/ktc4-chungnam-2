import { afterEach, describe, expect, it, vi } from 'vitest'

import { createMarkerLayer, LABEL_MAX_LEVEL, mapFade, PIN_GROUP_PX, placeLabels } from './markerLayer'
import type { Pin } from './model'
import { createCandidateMarkerElement, setPinLabel } from './pinMarker'

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
    permissions: { can_delete: false },
    ...extra,
  }) as unknown as Pin

/** 이름표가 보이는지(겹침 정리로 숨긴 것은 visibility:hidden). */
const labelShown = (id: string) => {
  const el = [...document.querySelectorAll<HTMLElement>('button')].find((b) => b.getAttribute('aria-label')?.startsWith(`가게${id},`))
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
    createMarkerLayer(maps, map, () => {}, () => {}).sync([pin('1', 0, 100), pin('2', 300, 100)], 4)
    expect(labelShown('1')).toBe(true)
    expect(labelShown('2')).toBe(true)
  })

  it('이름표가 겹치면 확정 핀 쪽만 남는다', () => {
    const { maps, map } = fakeMaps(4)
    createMarkerLayer(maps, map, () => {}, () => {}).sync([pin('1', 100, 100), pin('2', 130, 102, { kind: '확정' })], 4)
    expect(labelShown('2')).toBe(true)
    expect(labelShown('1')).toBe(false)
  })

  it('고른 핀은 겹쳐도 이름이 보이고, 그 자리의 다른 이름표가 비킨다', () => {
    const { maps, map } = fakeMaps(4)
    const layer = createMarkerLayer(maps, map, () => {}, () => {})
    layer.sync([pin('1', 100, 100), pin('2', 130, 102, { kind: '확정' })], 4)
    layer.select('1')
    expect(labelShown('1')).toBe(true)
    expect(labelShown('2')).toBe(false)
  })

  it(`멀리 보면(레벨 ${LABEL_MAX_LEVEL + 1}) 고른 핀만 이름이 남고, 다시 가까이 오면 돌아온다`, () => {
    const { maps, map, raw, idle } = fakeMaps(LABEL_MAX_LEVEL + 1)
    const layer = createMarkerLayer(maps, map, () => {}, () => {})
    layer.sync([pin('1', 0, 100), pin('2', 300, 100)], 4)
    layer.select('2')
    expect(labelShown('1')).toBe(false)
    expect(labelShown('2')).toBe(true)

    raw.level = LABEL_MAX_LEVEL
    idle()
    expect(labelShown('1')).toBe(true)
  })
})

describe('겹친 핀 묶음(#1576)', () => {
  const groupButton = () => [...document.querySelectorAll<HTMLElement>('button')].find((b) => b.getAttribute('aria-label')?.startsWith('핀 '))
  const pinShown = (id: string) => {
    const el = [...document.querySelectorAll<HTMLElement>('button')].find((b) => b.getAttribute('aria-label')?.startsWith(`가게${id},`))
    return Boolean(el) && !el!.hidden
  }

  it(`핀 끝끼리 ${PIN_GROUP_PX}px 안이면 숫자 핀 하나로 묶이고, 누르면 그 핀들과 좌표를 넘긴다`, () => {
    const { maps, map } = fakeMaps(4)
    const onGroup = vi.fn()
    createMarkerLayer(maps, map, () => {}, onGroup).sync([pin('1', 100, 100), pin('2', 110, 104, { kind: '확정' }), pin('3', 300, 100)], 4)
    expect(groupButton()?.getAttribute('aria-label')).toBe('핀 2곳이 겹쳐 있어요 · 가게1, 가게2')
    expect(groupButton()?.textContent).toContain('2')
    expect(pinShown('1')).toBe(false)
    expect(pinShown('2')).toBe(false)
    expect(pinShown('3')).toBe(true)
    groupButton()!.click()
    expect(onGroup).toHaveBeenCalledWith(['1', '2'], [{ lat: 100, lng: 100 }, { lat: 104, lng: 110 }])
  })

  it('묶음을 정리해도 낱개 핀의 가운데 정렬(display:flex)은 그대로다 — 비우면 핀 그림만 왼쪽 위로 붙어 이름표 꼬리가 어긋났다', () => {
    const { maps, map } = fakeMaps(4)
    createMarkerLayer(maps, map, () => {}, () => {}).sync([pin('1', 100, 100), pin('2', 110, 104), pin('3', 300, 100)], 4)
    const el = [...document.querySelectorAll<HTMLElement>('button')].find((b) => b.getAttribute('aria-label')?.startsWith('가게3,'))!
    expect(el.hidden).toBe(false)
    expect(el.style.display).toBe('flex')
  })

  it('확대해서 벌어지면 풀리고, 고른 핀은 묶지 않는다', () => {
    const { maps, map, raw, idle } = fakeMaps(4)
    const layer = createMarkerLayer(maps, map, () => {}, () => {})
    layer.sync([pin('1', 100, 100), pin('2', 110, 104)], 4)
    layer.select('1')
    expect(groupButton()).toBeUndefined()
    expect(pinShown('2')).toBe(true)

    layer.select(null)
    expect(groupButton()).toBeDefined()
    // 가짜 지도는 축척을 모른다 — 확대한 것처럼 좌표를 벌려 다시 넣는다.
    raw.level = 3
    layer.sync([pin('1', 100, 100), pin('2', 140, 104)], 4)
    idle()
    expect(groupButton()).toBeUndefined()
    expect(pinShown('1')).toBe(true)
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

describe('AI 후보 이름표(placeLabels)', () => {
  /** MapCanvas 처럼 고른 후보 > 순위 순으로 넘긴다. */
  const candidate = (rank: number, x: number, y: number) => {
    const el = createCandidateMarkerElement({ rank, name: `후보${rank}` }, () => {})
    setPinLabel(el, `후보${rank}`, 'quiet')
    document.body.appendChild(el)
    return { id: String(rank), el, name: `후보${rank}`, x, y, keep: false }
  }
  const shown = (c: { el: HTMLElement }) => c.el.querySelector<HTMLElement>('[data-pin-name]')?.style.visibility !== 'hidden'

  it('누르지 않아도 이름표가 있고, 겹치면 순위 높은 후보만 남는다', () => {
    const items = [candidate(1, 100, 100), candidate(2, 130, 102), candidate(3, 400, 100)]
    placeLabels(items, items, false)
    expect(items[0].el.querySelector('[data-pin-name="quiet"]')?.textContent).toBe('후보1')
    expect(items.map(shown)).toEqual([true, false, true])
  })

  it('멀리 보면 이름표가 숨는다', () => {
    const items = [candidate(1, 0, 100), candidate(2, 400, 100)]
    placeLabels(items, items, true)
    expect(items.map(shown)).toEqual([false, false])
  })
})

describe('AI 후보와 지도 핀 이름표를 한 번에 정리(#1744)', () => {
  it('후보 이름표가 지도 핀 이름표와 겹치면 후보가 남고, 후보를 치우면 지도 핀 이름표가 돌아온다', () => {
    const { maps, map } = fakeMaps(4)
    const layer = createMarkerLayer(maps, map, () => {}, () => {})
    layer.sync([pin('1', 130, 102)], 4)
    const el = createCandidateMarkerElement({ rank: 1, name: '후보1' }, () => {})
    setPinLabel(el, '후보1', 'quiet')
    document.body.appendChild(el)
    const shown = () => el.querySelector<HTMLElement>('[data-pin-name]')?.style.visibility !== 'hidden'

    layer.setLeadLabels(() => [{ id: 'ai:1', el, name: '후보1', x: 100, y: 100, keep: false }])
    expect([shown(), labelShown('1')]).toEqual([true, false])

    layer.setLeadLabels(() => [])
    expect(labelShown('1')).toBe(true)
  })
})
