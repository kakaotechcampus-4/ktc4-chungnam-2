import { QueryClient } from '@tanstack/react-query'
import { server, resetScenario } from '@pingo/contracts/mocks/node'
import { afterAll, afterEach, beforeAll, describe, expect, it, vi } from 'vitest'

import { nearestPlaces } from '@/features/search/api'

import { fetchPins, fetchPinTrash, fetchReactions } from './api'
import type { Pin } from './model'
import { attachTrashDrag, setMapBridge, usePinDragStore } from './pinDrag'
import { moveBlockedReason, movePin, moveTargets, undoMove } from './pinMove'
import { pinKeys } from './queries'

const MAP = 'map_1'

function fire(el: Element, type: string, x: number, y: number) {
  const e = new MouseEvent(type, { bubbles: true, cancelable: true, clientX: x, clientY: y, button: 0 })
  Object.defineProperties(e, { pointerId: { value: 1 }, pointerType: { value: 'mouse' } })
  el.dispatchEvent(e)
}

describe('지도 위에 놓기(#1549)', () => {
  afterEach(() => setMapBridge(null))

  function drag(toX: number, toY: number, onMap: boolean) {
    usePinDragStore.setState({ drag: null })
    setMapBridge({ toLatLng: () => (onMap ? { lat: 37.5, lng: 127 } : null), toScreen: () => ({ x: 0, y: 0 }) })
    const el = document.createElement('button')
    document.body.append(el)
    const detach = attachTrashDrag(el, () => ({ id: 'p' }) as Pin, () => '')
    fire(el, 'pointerdown', 10, 10)
    fire(el, 'pointermove', 30, 30)
    fire(el, 'pointermove', toX, toY)
    fire(el, 'pointerup', toX, toY)
    const result = usePinDragStore.getState().drag
    detach()
    el.remove()
    return result
  }

  it('충분히 끌어 지도 위에 놓으면 옮기기 단계로 넘긴다(놓은 자리 좌표와 함께)', () => {
    expect(drag(200, 200, true)).toMatchObject({ phase: 'move', at: { lat: 37.5, lng: 127 } })
  })
  it('지도가 아닌 곳(패널, 시트)이나 집은 자리 가까이에 놓으면 제자리다', () => {
    expect(drag(200, 200, false)).toBeNull()
    expect(drag(40, 30, true)).toBeNull()
  })
})

describe('옮길 수 있는 핀과 옮길 곳', () => {
  const pin = (extra: Partial<Pin>) => ({ kind: '일반', permissions: { can_edit: true, can_delete: true }, ...extra }) as Pin
  it('확정, AI 추천, 남이 찍은 핀은 이유를 알린다', () => {
    expect(moveBlockedReason(pin({}))).toBeNull()
    expect(moveBlockedReason(pin({ kind: '확정' }))).toMatch('확정')
    expect(moveBlockedReason(pin({ kind: 'AI추천' }))).toMatch('AI 추천')
    expect(moveBlockedReason(pin({ permissions: { can_edit: false, can_delete: true } as Pin['permissions'] }))).toMatch('내가 찍은')
  })
  it('지금 있는 장소는 옮길 곳에서 뺀다', () => {
    const here = pin({ place_name: '가게', lat: 37.5, lng: 127 })
    expect(
      moveTargets(here, [
        { place_id: 'own:a', place_name: '가게', lat: 37.5001, lng: 127 },
        { place_id: 'own:b', place_name: '옆가게', lat: 37.5001, lng: 127 },
      ]).map((p) => p.place_name),
    ).toEqual(['옆가게'])
  })
})

describe('옮기기와 되돌리기(목 서버)', () => {
  beforeAll(() => server.listen({ onUnhandledRequest: 'error' }))
  afterEach(() => {
    server.resetHandlers()
    resetScenario('happy-path')
  })
  afterAll(() => server.close())

  it('새 장소에 핀을 만들고 옛 핀은 휴지통으로, 되돌리면 옛 핀이 의견과 함께 돌아온다', async () => {
    const client = new QueryClient()
    const pins = await fetchPins(MAP)
    client.setQueryData(pinKeys.list(MAP), pins)
    const old = pins.find((p) => p.permissions.can_edit && p.kind === '일반')!
    const reactionsBefore = await fetchReactions(old.id)
    const [place] = moveTargets(old, await nearestPlaces({ lat: 35.1631, lng: 129.1639 }))

    const created = await movePin(client, MAP, old, place)
    expect(created.place_name).toBe(place.place_name)
    const after = client.getQueryData<Pin[]>(pinKeys.list(MAP))!
    expect(after.map((p) => p.id)).toContain(created.id)
    expect(after.map((p) => p.id)).not.toContain(old.id)
    expect((await fetchPinTrash(MAP)).items.map((i) => i.pin.id)).toContain(old.id)

    await undoMove(client, MAP, created, old)
    const back = client.getQueryData<Pin[]>(pinKeys.list(MAP))!
    expect(back.map((p) => p.id)).toContain(old.id)
    expect(back.map((p) => p.id)).not.toContain(created.id)
    expect(await fetchReactions(old.id)).toEqual(reactionsBefore)
    vi.restoreAllMocks()
  })
})
