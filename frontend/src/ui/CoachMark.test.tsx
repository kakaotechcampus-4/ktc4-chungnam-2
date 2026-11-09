import { act, fireEvent, render, screen } from '@testing-library/react'
import { afterEach, beforeEach, expect, it, vi } from 'vitest'

import CoachMark from './CoachMark'

const ui = () => (
  <>
    <button type="button" data-coach="put">넣기</button>
    <CoachMark id="put" target="put" title="날짜를 고르고 넣기를 눌러요">
      고른 날 일정 끝에 들어가요
    </CoachMark>
  </>
)

beforeEach(() => {
  vi.useFakeTimers()
  localStorage.clear()
  // jsdom 은 크기가 0이라 짚을 자리가 없는 것으로 본다 — 짚을 버튼에만 크기를 준다.
  vi.spyOn(HTMLElement.prototype, 'getBoundingClientRect').mockImplementation(function (this: HTMLElement) {
    return this.dataset.coach ? new DOMRect(20, 100, 80, 40) : new DOMRect(0, 0, 0, 0)
  })
})
afterEach(() => {
  vi.useRealTimers()
  vi.restoreAllMocks()
})

it('잠깐 뒤 짚고, 알겠어요로 닫으면 이 기기에서 다시 뜨지 않는다', () => {
  const { unmount } = render(ui())
  expect(screen.queryByText('날짜를 고르고 넣기를 눌러요')).not.toBeInTheDocument()
  act(() => vi.advanceTimersByTime(800))
  expect(screen.getByRole('status')).toHaveTextContent('고른 날 일정 끝에 들어가요')

  fireEvent.click(screen.getByRole('button', { name: '알겠어요' }))
  expect(screen.queryByRole('status')).not.toBeInTheDocument()
  expect(localStorage.getItem('coach.put')).toBe('1')

  unmount()
  render(ui())
  act(() => vi.advanceTimersByTime(800))
  expect(screen.queryByRole('status')).not.toBeInTheDocument()
})

it('아무 곳이나 누르면 닫힌다(누름은 막지 않는다)', () => {
  const onPut = vi.fn()
  render(
    <>
      <button type="button" data-coach="put" onClick={onPut}>넣기</button>
      <CoachMark id="put" target="put" title="제목">한 줄</CoachMark>
    </>,
  )
  act(() => vi.advanceTimersByTime(800))
  const put = screen.getByRole('button', { name: '넣기' })
  fireEvent.pointerDown(put)
  fireEvent.click(put)
  expect(screen.queryByRole('status')).not.toBeInTheDocument()
  expect(onPut).toHaveBeenCalled()
})

it('짚을 자리가 없으면 띄우지 않고 본 것으로도 치지 않는다', () => {
  render(<CoachMark id="none" target="none" title="제목">한 줄</CoachMark>)
  act(() => vi.advanceTimersByTime(800))
  expect(screen.queryByRole('status')).not.toBeInTheDocument()
  expect(localStorage.getItem('coach.none')).toBeNull()
})
