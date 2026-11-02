import { describe, expect, it } from 'vitest'

import { allInside, fitCenter, fitLevel, MAX_LEVEL, zoomSteps } from './camera'

const size = { w: 1000, h: 800 }
const none = { top: 0, right: 0, bottom: 0, left: 0 }

describe('지도가 스스로 움직일 때의 계산(#1026)', () => {
  it('확대·축소는 2단계씩 나눠 이어 간다 — 카카오는 차이 2 이하에서만 움직임을 보인다', () => {
    expect(zoomSteps(8, 3)).toEqual([6, 4, 3])
    expect(zoomSteps(3, 8)).toEqual([5, 7, 8])
    expect(zoomSteps(5, 4)).toEqual([4])
    expect(zoomSteps(5, 5)).toEqual([])
  })

  it('점 범위가 화면의 두 배면 한 단계 멀어지고, 반이면 한 단계 가까워진다', () => {
    expect(fitLevel([{ x: 0, y: 0 }, { x: 2000, y: 0 }], size, none, 5, 1)).toBe(6)
    expect(fitLevel([{ x: 0, y: 0 }, { x: 500, y: 0 }], size, none, 5, 1)).toBe(4)
    // 딱 맞으면 그대로
    expect(fitLevel([{ x: 0, y: 0 }, { x: 1000, y: 0 }], size, none, 5, 1)).toBe(5)
  })

  it('여백을 뺀 상자에 맞추고, 정한 레벨보다 가까이 가지 않는다', () => {
    const pad = { top: 0, right: 250, bottom: 0, left: 250 } // 남는 폭 500
    expect(fitLevel([{ x: 0, y: 0 }, { x: 1000, y: 0 }], size, pad, 5, 1)).toBe(6)
    // 점 하나(또는 한 자리) — 가장 가까운 허용 레벨
    expect(fitLevel([{ x: 10, y: 10 }], size, none, 9, 3)).toBe(3)
    // 아주 가까운 두 점도 3보다 가까이 들어가지 않는다
    expect(fitLevel([{ x: 0, y: 0 }, { x: 1, y: 0 }], size, none, 9, 3)).toBe(3)
    expect(fitLevel([{ x: 0, y: 0 }, { x: 1e9, y: 0 }], size, none, 9, 3)).toBe(MAX_LEVEL)
  })

  it('맞춘 뒤 점 범위의 가운데가 여백 안 상자의 가운데에 온다', () => {
    // 여백이 없으면 점 범위 가운데가 곧 지도 가운데
    expect(fitCenter([{ x: 100, y: 100 }, { x: 300, y: 300 }], size, none, 5, 5)).toEqual({ x: 200, y: 200 })
    // 아래 400px 를 시트가 가리면 상자 가운데는 y=200 — 지도 가운데(400)를 200px(목표 레벨) 아래로 둔다
    const sheet = { top: 0, right: 0, bottom: 400, left: 0 }
    expect(fitCenter([{ x: 500, y: 200 }], size, sheet, 5, 5)).toEqual({ x: 500, y: 400 })
    // 한 단계 멀어지면 목표 레벨 200px 는 지금 레벨 400px
    expect(fitCenter([{ x: 500, y: 200 }], size, sheet, 5, 6)).toEqual({ x: 500, y: 600 })
  })

  it('이미 여백 안에 다 보이면 옮기지 않는다', () => {
    const pad = { top: 100, right: 0, bottom: 300, left: 0 }
    expect(allInside([{ x: 10, y: 150 }, { x: 990, y: 490 }], size, pad)).toBe(true)
    expect(allInside([{ x: 10, y: 150 }, { x: 500, y: 600 }], size, pad)).toBe(false)
  })
})
