import { afterEach, expect, it, vi } from 'vitest'

import { fireConfetti } from './confetti'

afterEach(() => {
  vi.useRealTimers()
  vi.unstubAllGlobals()
})

it('뿌린 뒤 스스로 지운다(#1723)', () => {
  vi.useFakeTimers()
  fireConfetti()
  expect(document.querySelector('.confetti')).toBeInTheDocument()
  vi.advanceTimersByTime(2000)
  expect(document.querySelector('.confetti')).not.toBeInTheDocument()
})

it('동작 줄이기면 뿌리지 않는다', () => {
  vi.stubGlobal('matchMedia', () => ({ matches: true }))
  fireConfetti()
  expect(document.querySelector('.confetti')).not.toBeInTheDocument()
})
