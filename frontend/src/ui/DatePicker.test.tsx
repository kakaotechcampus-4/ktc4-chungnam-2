import { render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, expect, it, vi } from 'vitest'

import DatePicker, { Calendar } from './DatePicker'

const SIX_WEEKS = 'grid-rows-[repeat(6,2.75rem)]'
/** 날짜 버튼들이 놓인 grid. */
const gridOf = (scope: HTMLElement, name: RegExp) => within(scope).getByRole('button', { name }).parentElement!

/** jsdom 에는 matchMedia 가 없다. 넓은 화면 판정(min-width)만 `desktop`대로 답한다. */
function screenIs(desktop: boolean) {
  vi.stubGlobal('matchMedia', (query: string) => ({
    matches: desktop && query.includes('min-width'),
    media: query,
    addEventListener() {},
    removeEventListener() {},
  }))
}
afterEach(() => {
  vi.unstubAllGlobals()
})

it('넓은 화면: 칸 아래 창으로 뜨는 달력은 짧은 달도 6주 높이라 달을 넘겨도 버튼 자리가 그대로다', async () => {
  screenIs(true)
  // 2026년 2월은 일요일에 시작하는 28일이라 4주뿐이다.
  render(<DatePicker value="2026-02-10" onChange={() => {}} />)
  await userEvent.click(screen.getByRole('button', { name: /^2026\.2\.10/ }))
  const calendar = await screen.findByRole('dialog', { name: '날짜 고르기' })
  // 창은 칸 위·아래 남은 높이까지만 — 넘치면 창 안에서 내린다(#1765).
  expect(calendar).toHaveClass('max-h-[var(--radix-popover-content-available-height)]', 'overflow-y-auto')
  expect(gridOf(calendar, /^2026년 2월 10일 /)).toHaveClass(SIX_WEEKS)

  await userEvent.click(within(calendar).getByRole('button', { name: '다음 달' }))
  expect(gridOf(calendar, /^2026년 3월 1일 /)).toHaveClass(SIX_WEEKS)
})

it('좁은 화면: 달력은 바닥 시트로 뜨고, 달을 넘겨 날을 고르면 닫힌다', async () => {
  screenIs(false)
  const onChange = vi.fn()
  render(<DatePicker value="2026-02-10" onChange={onChange} />)
  await userEvent.click(screen.getByRole('button', { name: /^2026\.2\.10/ }))
  const sheet = await screen.findByRole('dialog', { name: '날짜 고르기' })
  // 시트(모달)라 칸 아래 창의 높이 제한이 아니다.
  expect(sheet).toHaveAttribute('aria-modal', 'true')
  expect(gridOf(sheet, /^2026년 2월 10일 /)).toHaveClass(SIX_WEEKS)

  await userEvent.click(within(sheet).getByRole('button', { name: '다음 달' }))
  await userEvent.click(within(sheet).getByRole('button', { name: /^2026년 3월 5일 / }))
  expect(onChange).toHaveBeenCalledWith('2026-03-05')
  await waitFor(() => expect(screen.queryByRole('dialog')).not.toBeInTheDocument())
})

it('좁은 화면: 이미 시트 안이면 그 위에 겹치고, 날을 고르면 아래 시트로 돌아온다', async () => {
  screenIs(false)
  const { default: ModalSheet } = await import('@/features/shell/ModalSheet')
  render(
    <ModalSheet label="카톡 대화로 핀 찍기" onClose={() => {}}>
      <DatePicker value="2026-02-10" onChange={() => {}} />
    </ModalSheet>,
  )
  await userEvent.click(screen.getByRole('button', { name: /^2026\.2\.10/ }))
  const picker = await screen.findByRole('dialog', { name: '날짜 고르기' })
  await userEvent.click(within(picker).getByRole('button', { name: /^2026년 2월 12일 / }))

  await waitFor(() => expect(screen.queryByRole('dialog', { name: '날짜 고르기' })).not.toBeInTheDocument())
  expect(screen.getByRole('dialog', { name: '카톡 대화로 핀 찍기' })).toBeInTheDocument()
})

it('화면에 까는 달력은 그 달의 주만 그린다', () => {
  const { container } = render(<Calendar value="2026-02-10" onPick={() => {}} />)
  expect(gridOf(container, /^2026년 2월 10일 /)).not.toHaveClass(SIX_WEEKS)
})
