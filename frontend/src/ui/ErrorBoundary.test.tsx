import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter } from 'react-router'
import { afterEach, beforeEach, expect, it, vi } from 'vitest'

import ErrorBoundary from './ErrorBoundary'

let broken = true
function Child() {
  if (broken) throw new Error('boom')
  return <p>정상 화면</p>
}

const ui = (resetKey: string) => (
  <MemoryRouter>
    <ErrorBoundary resetKey={resetKey}>
      <Child />
    </ErrorBoundary>
  </MemoryRouter>
)

beforeEach(() => {
  broken = true
  // 던져진 오류를 React 와 경계가 콘솔에 남기는 것은 기대한 일이다.
  vi.spyOn(console, 'error').mockImplementation(() => {})
})
afterEach(() => vi.restoreAllMocks())

it('자식이 던지면 안내를 보인다', () => {
  render(ui('a'))
  expect(screen.getByText('화면을 그리지 못했어요')).toBeInTheDocument()
  expect(screen.getByRole('link', { name: '처음으로' })).toHaveAttribute('href', '/')
})

it('「다시 열기」는 자식을 다시 그린다', async () => {
  render(ui('a'))
  broken = false
  await userEvent.click(screen.getByRole('button', { name: '다시 열기' }))
  expect(screen.getByText('정상 화면')).toBeInTheDocument()
})

it('resetKey 가 바뀌면 오류를 비운다', () => {
  const { rerender } = render(ui('a'))
  broken = false
  rerender(ui('b'))
  expect(screen.getByText('정상 화면')).toBeInTheDocument()
})
