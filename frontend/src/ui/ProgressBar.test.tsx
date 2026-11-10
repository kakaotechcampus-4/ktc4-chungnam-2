import { render, screen } from '@testing-library/react'
import { expect, it } from 'vitest'

import ProgressBar, { percent } from './ProgressBar'

it('%는 반올림하고 0~100 밖으로 나가지 않으며, 분모가 0이면 0이다', () => {
  expect(percent(1, 3)).toBe(33)
  expect(percent(2, 3)).toBe(67)
  expect(percent(5, 4)).toBe(100)
  expect(percent(1, 0)).toBe(0)
})

it('막대는 글을 이름으로 progressbar 로 읽힌다', () => {
  render(<ProgressBar label="4명 중 3명이 의견을 남겼어요" value={3} max={4} />)
  const bar = screen.getByRole('progressbar', { name: '4명 중 3명이 의견을 남겼어요' })
  expect(bar).toHaveAttribute('aria-valuenow', '3')
  expect(bar).toHaveAttribute('aria-valuemax', '4')
})
