import { afterEach, describe, expect, it, vi } from 'vitest'

import { attachLongPress, HOLD_MS } from './longPress'

function fire(el: Element, type: string, x: number, y: number, pointerType = 'touch', id = 1) {
  const e = new MouseEvent(type, { bubbles: true, cancelable: true, clientX: x, clientY: y })
  Object.defineProperties(e, { pointerId: { value: id }, pointerType: { value: pointerType }, isPrimary: { value: id === 1 } })
  el.dispatchEvent(e)
}

describe('빈 지도 길게 누르기(#1549)', () => {
  afterEach(() => vi.useRealTimers())

  function setup() {
    vi.useFakeTimers()
    const wrap = document.createElement('div')
    const map = document.createElement('div')
    const pin = document.createElement('button')
    map.append(pin)
    wrap.append(map)
    document.body.append(wrap)
    const onPress = vi.fn()
    const press = attachLongPress(map, onPress)
    return { map, pin, onPress, press, done: () => (press.detach(), wrap.remove()) }
  }

  it('0.5초 누르면 메뉴를 부르고, 뒤따르는 click 을 버리게 알린다', () => {
    const { map, onPress, press, done } = setup()
    fire(map, 'pointerdown', 20, 30)
    expect(map.parentElement!.querySelector('.press-ring')).not.toBeNull()
    vi.advanceTimersByTime(HOLD_MS - 1)
    expect(onPress).not.toHaveBeenCalled()
    vi.advanceTimersByTime(1)
    expect(onPress).toHaveBeenCalledWith(20, 30)
    expect(map.parentElement!.querySelector('.press-ring')).toBeNull()
    expect(press.justFired()).toBe(true)
    done()
  })

  it('움직이거나(지도 끌기) 일찍 떼거나 두 손가락이면 그만둔다', () => {
    const { map, onPress, done } = setup()
    fire(map, 'pointerdown', 20, 30)
    fire(map, 'pointermove', 40, 30)
    fire(map, 'pointerdown', 20, 30)
    fire(map, 'pointerup', 20, 30)
    fire(map, 'pointerdown', 20, 30)
    fire(map, 'pointerdown', 60, 30, 'touch', 2)
    vi.advanceTimersByTime(HOLD_MS * 2)
    expect(onPress).not.toHaveBeenCalled()
    done()
  })

  it('마우스(우클릭이 따로 있다)와 핀 위(핀 집기)에서는 시작하지 않는다', () => {
    const { map, pin, onPress, done } = setup()
    fire(map, 'pointerdown', 20, 30, 'mouse')
    vi.advanceTimersByTime(HOLD_MS)
    fire(pin, 'pointerdown', 20, 30)
    vi.advanceTimersByTime(HOLD_MS)
    expect(onPress).not.toHaveBeenCalled()
    done()
  })
})
