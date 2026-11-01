import { act, renderHook } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import { usePhaseLoop } from './usePhaseLoop'

const PHASES = [800, 500, 1600]

beforeEach(() => vi.useFakeTimers())
afterEach(() => {
  vi.useRealTimers()
  vi.unstubAllGlobals()
})

describe('온보딩 장면 단계', () => {
  it('단계마다 정한 시간이 지나면 다음 단계로, 끝나면 처음으로 되풀이한다', () => {
    const { result } = renderHook(() => usePhaseLoop(PHASES))
    expect(result.current).toBe(0)
    act(() => vi.advanceTimersByTime(800))
    expect(result.current).toBe(1)
    act(() => vi.advanceTimersByTime(500))
    expect(result.current).toBe(2)
    act(() => vi.advanceTimersByTime(1600))
    expect(result.current).toBe(0)
  })

  it('움직임 줄이기면 돌지 않고 쉬는 단계에 머문다', () => {
    vi.stubGlobal('matchMedia', (query: string) => ({ matches: query.includes('reduce') }))
    const { result } = renderHook(() => usePhaseLoop(PHASES, 1))
    expect(result.current).toBe(1)
    act(() => vi.advanceTimersByTime(10_000))
    expect(result.current).toBe(1)
  })
})
