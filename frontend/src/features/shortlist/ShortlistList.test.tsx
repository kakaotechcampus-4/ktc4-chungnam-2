import { fireEvent, render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it, vi } from 'vitest'

import type { ShortlistItemDto } from './model'
import ShortlistList from './ShortlistList'

const item = (id: string, name: string) =>
  ({ id, pin: { id: `pin_${id}`, place_name: name, category: '음식점' }, permissions: { can_remove_from_shortlist: true } }) as unknown as ShortlistItemDto

const items = [item('a', '흑돼지식당'), item('b', '우진해장국')]

describe('확정 리스트 줄(일정에 아직 넣지 않은 곳)', () => {
  it('순서 바꾸기·「위로」「아래로」·밀어서 빼기는 없고, 체크박스로 고르고 「확정 해제」가 있다', async () => {
    const onCheck = vi.fn()
    const onRemove = vi.fn()
    render(<ShortlistList items={items} checked={new Set()} onCheck={onCheck} onOpen={() => {}} onRemove={onRemove} />)

    expect(screen.queryByRole('button', { name: /순서 바꾸기/ })).not.toBeInTheDocument()
    expect(screen.queryByRole('button', { name: '위로' })).not.toBeInTheDocument()
    expect(screen.queryByRole('button', { name: /빼기/ })).not.toBeInTheDocument()

    await userEvent.click(screen.getByRole('checkbox', { name: '우진해장국 고르기' }))
    expect(onCheck).toHaveBeenCalledWith('pin_b', true)
    await userEvent.click(screen.getAllByRole('button', { name: '확정 해제' })[0])
    expect(onRemove).toHaveBeenCalledWith(expect.objectContaining({ id: 'a' }))
  })

  it('「일정 짜기」 패널이 열려 있을 때만 ≡ 가 있고, 끌어서 칸에 놓으면 그 자리에 넣는다', () => {
    const onDrop = vi.fn()
    // 패널의 날짜 칸 하나와 그 안의 줄 하나(jsdom 은 위치 계산이 없어 손가락 밑 요소와 줄 위치를 정해 준다).
    const day = document.createElement('section')
    day.dataset.day = '2026-10-11'
    const row = document.createElement('li')
    row.dataset.pin = 'pin_x'
    row.getBoundingClientRect = () => ({ top: 300, height: 40 }) as DOMRect
    day.append(row)
    document.body.append(day)
    const doc = document as { elementFromPoint?: Document['elementFromPoint'] }
    doc.elementFromPoint = () => day

    const { container, rerender } = render(<ShortlistList items={items} checked={new Set()} onCheck={() => {}} onOpen={() => {}} onRemove={() => {}} />)
    expect(container.querySelector('.cursor-grab')).toBeNull()

    rerender(<ShortlistList items={items} checked={new Set()} onCheck={() => {}} onOpen={() => {}} onRemove={() => {}} onDrop={onDrop} />)
    const handle = container.querySelectorAll<HTMLElement>('.cursor-grab')[0]
    fireEvent.pointerDown(handle, { clientX: 400, clientY: 100, pointerId: 1 })
    fireEvent.pointerMove(handle, { clientX: 640, clientY: 280, pointerId: 1 })
    fireEvent.pointerUp(handle, { clientX: 640, clientY: 280, pointerId: 1 })

    // 손가락(280)이 줄 가운데(320)보다 위라 그 줄 앞(0번째)이다.
    expect(onDrop).toHaveBeenCalledWith(expect.objectContaining({ id: 'a' }), { day: '2026-10-11', index: 0 })
    day.remove()
    delete doc.elementFromPoint
  })
})
