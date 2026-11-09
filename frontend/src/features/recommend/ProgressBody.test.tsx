import { act, render, screen } from '@testing-library/react'
import { afterEach, expect, it, vi } from 'vitest'

import { ProgressBody } from './Readiness'

afterEach(() => vi.useRealTimers())

it('진행 단계는 처음부터 모두 보이고, 시간이 지나면 지금 단계가 다음으로 넘어간다(#1659)', () => {
  vi.useFakeTimers()
  render(<ProgressBody steps={['모으는 중', '거르는 중', '정하는 중']} />)
  // 번호 원은 aria-hidden 이라 글자에만 섞인다.
  const rows = () => screen.getAllByRole('listitem').map((li) => li.textContent)
  expect(rows()).toEqual(['지금 단계: 모으는 중진행 중', '2남은 단계: 거르는 중', '3남은 단계: 정하는 중'])
  act(() => vi.advanceTimersByTime(3000))
  expect(rows()).toEqual(['끝난 단계: 모으는 중', '지금 단계: 거르는 중진행 중', '3남은 단계: 정하는 중'])
})
