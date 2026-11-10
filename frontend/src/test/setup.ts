import '@testing-library/jest-dom/vitest'
import { cleanup, configure } from '@testing-library/react'
import { afterEach } from 'vitest'

afterEach(cleanup)

// findBy, waitFor 가 화면을 기다리는 시간. 기본 1초는 컴퓨터가 바쁘면 첫 화면(목 서버 응답)이 늦어 고장 없이 실패했다
// (내 지도 목록의 첫 시험, 2026-11-10). 위 testTimeout 과 같은 이유로 늘린다. 화면이 일찍 나오면 그때 바로 넘어간다.
configure({ asyncUtilTimeout: 5_000 })

// jsdom 에는 ResizeObserver 가 없다 — Radix Slider 가 손잡이 크기를 잴 때 쓴다(ui/RangeSlider). 화면 테스트는 크기를 보지 않는다.
globalThis.ResizeObserver ??= class {
  observe() {}
  unobserve() {}
  disconnect() {}
}
