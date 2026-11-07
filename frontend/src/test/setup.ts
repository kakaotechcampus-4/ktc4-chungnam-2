import '@testing-library/jest-dom/vitest'
import { cleanup } from '@testing-library/react'
import { afterEach } from 'vitest'

afterEach(cleanup)

// jsdom 에는 ResizeObserver 가 없다 — Radix Slider 가 손잡이 크기를 잴 때 쓴다(ui/RangeSlider). 화면 테스트는 크기를 보지 않는다.
globalThis.ResizeObserver ??= class {
  observe() {}
  unobserve() {}
  disconnect() {}
}
