import { fireEvent, render, screen } from '@testing-library/react'
import { expect, it, vi } from 'vitest'

import { ScheduleDayList } from './ScheduleDay'

// jsdom 에는 matchMedia 가 없어 터치 화면으로 본다(밀기 켜짐).
function setup() {
  const onTakeOut = vi.fn()
  const onOpen = vi.fn()
  render(
    <ScheduleDayList day="2026-10-10" ids={['p1']} nameOf={() => '흑돼지식당'} onOpen={onOpen} onTakeOut={onTakeOut} onDrop={() => {}} onShift={() => {}} empty="" />,
  )
  const row = screen.getByRole('listitem')
  const drag = (to: { x: number; y: number }) => {
    fireEvent.pointerDown(row, { clientX: 300, clientY: 100, pointerId: 1 })
    fireEvent.pointerMove(row, { clientX: 300 + (to.x - 300) / 2, clientY: 100 + (to.y - 100) / 2, pointerId: 1 })
    fireEvent.pointerMove(row, { clientX: to.x, clientY: to.y, pointerId: 1 })
    fireEvent.pointerUp(row, { clientX: to.x, clientY: to.y, pointerId: 1 })
  }
  return { onTakeOut, onOpen, drag }
}

it('왼쪽으로 충분히 밀고 놓으면 일정에서 뺀다(#1669)', () => {
  const { onTakeOut, drag } = setup()
  drag({ x: 150, y: 104 })
  expect(onTakeOut).toHaveBeenCalledWith('p1')
})

it('덜 밀거나 세로로 움직이면 빼지 않는다', () => {
  const { onTakeOut, drag } = setup()
  drag({ x: 250, y: 102 })
  drag({ x: 290, y: 220 })
  expect(onTakeOut).not.toHaveBeenCalled()
})

it('민 뒤의 클릭은 이름 버튼을 열지 않고, 그냥 누르면 연다', () => {
  const { onOpen, drag } = setup()
  drag({ x: 250, y: 102 })
  fireEvent.click(screen.getByRole('button', { name: '흑돼지식당' }))
  expect(onOpen).not.toHaveBeenCalled()
  fireEvent.click(screen.getByRole('button', { name: '흑돼지식당' }))
  expect(onOpen).toHaveBeenCalledWith('p1')
})
