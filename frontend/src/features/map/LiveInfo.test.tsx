import { act, render, screen } from '@testing-library/react'
import { afterEach, expect, it, vi } from 'vitest'

import type { Pin } from './model'
import { LOCATE_SLOW_MS, useLivePlaceStore } from './livePlaces'
import { LiveInfo } from './PinDetail'

const pin = { id: 'pin_live', source: 'live', search_query: '동네 빵집', kakao_place_id: 'kakao:1' } as Pin

afterEach(() => {
  vi.useRealTimers()
  useLivePlaceStore.setState({ places: {}, since: {}, attempts: 0 })
})

it('위치를 1분 넘게 못 찾으면 「다시 시도할까요?」 — 누르면 다시 찾게 하고 찾는 중으로 돌아간다', () => {
  vi.useFakeTimers()
  useLivePlaceStore.getState().start(pin.id)
  render(<LiveInfo pin={pin} />)
  expect(screen.getByText('장소 위치를 확인하는 중이에요…')).toBeInTheDocument()

  act(() => vi.advanceTimersByTime(LOCATE_SLOW_MS))
  expect(screen.getByText(/다시 시도할까요\?/)).toBeInTheDocument()

  act(() => screen.getByRole('button', { name: '다시 시도' }).click())
  expect(useLivePlaceStore.getState().attempts).toBe(1)
  // 찾는 쪽이 다시 시작하면(start) 시계가 새로 돈다.
  act(() => useLivePlaceStore.getState().start(pin.id))
  expect(screen.getByText('장소 위치를 확인하는 중이에요…')).toBeInTheDocument()
})

it('예전에 시작해 멈춘 검색이면 핀 상세를 열자마자 묻는다', () => {
  useLivePlaceStore.setState({ since: { [pin.id]: Date.now() - LOCATE_SLOW_MS - 1 } })
  render(<LiveInfo pin={pin} />)
  expect(screen.getByRole('button', { name: '다시 시도' })).toBeInTheDocument()
})
