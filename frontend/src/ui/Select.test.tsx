import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { expect, it, vi } from 'vitest'

import Select from './Select'

// jsdom 에는 포인터 잡기·스크롤 함수가 없다 — Radix Select 가 목록을 열 때 부른다.
Object.assign(Element.prototype, { hasPointerCapture: () => false, releasePointerCapture: () => {}, scrollIntoView: () => {} })

const options = [
  { value: '', label: '전체' },
  { value: 'like', label: '좋음' },
]

it('목록에서 고른 값을 돌려주고, 「전체」는 빈 값으로 돌려준다(#1695)', async () => {
  const onChange = vi.fn()
  const { rerender } = render(<Select label="의견" value="" options={options} onChange={onChange} />)
  const trigger = screen.getByRole('combobox', { name: '의견' })
  expect(trigger).toHaveTextContent('전체')

  await userEvent.click(trigger)
  await userEvent.click(await screen.findByRole('option', { name: '좋음' }))
  expect(onChange).toHaveBeenLastCalledWith('like')

  rerender(<Select label="의견" value="like" options={options} onChange={onChange} />)
  await userEvent.click(trigger)
  await userEvent.click(await screen.findByRole('option', { name: '전체' }))
  expect(onChange).toHaveBeenLastCalledWith('')
})
