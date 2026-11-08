import { act, renderHook } from '@testing-library/react'
import { afterEach, beforeEach, expect, it, vi } from 'vitest'

import { DROWSY_AFTER_MS, SLEEP_AFTER_MS, useIdleStage } from './useIdleStage'

beforeEach(() => vi.useFakeTimers())
afterEach(() => vi.useRealTimers())

it('5분 가만히 있으면 졸고, 10초 더 지나면 자고, 손을 대면 바로 깬다', () => {
  const { result } = renderHook(() => useIdleStage())
  expect(result.current).toBeNull()

  act(() => vi.advanceTimersByTime(DROWSY_AFTER_MS + 1_000))
  expect(result.current).toBe('drowsy')

  act(() => vi.advanceTimersByTime(SLEEP_AFTER_MS - DROWSY_AFTER_MS))
  expect(result.current).toBe('sleep')

  act(() => {
    window.dispatchEvent(new Event('pointerdown'))
  })
  expect(result.current).toBeNull()

  // 깬 뒤에는 다시 처음부터 센다.
  act(() => vi.advanceTimersByTime(DROWSY_AFTER_MS - 5_000))
  expect(result.current).toBeNull()
})
