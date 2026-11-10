import { render, screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { expect, it } from 'vitest'

import DatePicker, { Calendar } from './DatePicker'

const SIX_WEEKS = 'grid-rows-[repeat(6,2.75rem)]'
/** 날짜 버튼들이 놓인 grid. */
const gridOf = (scope: HTMLElement, name: RegExp) => within(scope).getByRole('button', { name }).parentElement!

it('창으로 뜨는 달력은 짧은 달도 6주 높이라 달을 넘겨도 버튼 자리가 그대로다', async () => {
  // 2026년 2월은 일요일에 시작하는 28일이라 4주뿐이다.
  render(<DatePicker value="2026-02-10" onChange={() => {}} />)
  await userEvent.click(screen.getByRole('button', { name: /^2026\.2\.10/ }))
  const calendar = await screen.findByRole('dialog', { name: '날짜 고르기' })
  expect(gridOf(calendar, /^2026년 2월 10일 /)).toHaveClass(SIX_WEEKS)

  await userEvent.click(within(calendar).getByRole('button', { name: '다음 달' }))
  expect(gridOf(calendar, /^2026년 3월 1일 /)).toHaveClass(SIX_WEEKS)
})

it('화면에 까는 달력은 그 달의 주만 그린다', () => {
  const { container } = render(<Calendar value="2026-02-10" onPick={() => {}} />)
  expect(gridOf(container, /^2026년 2월 10일 /)).not.toHaveClass(SIX_WEEKS)
})
