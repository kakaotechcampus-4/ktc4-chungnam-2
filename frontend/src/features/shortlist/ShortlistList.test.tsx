import { fireEvent, render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it, vi } from 'vitest'

import type { ShortlistItemDto } from './model'
import ShortlistList from './ShortlistList'

const item = (id: string, name: string) =>
  ({ id, pin: { id: `pin_${id}`, place_name: name, category: '음식점' }, permissions: { can_remove_from_shortlist: true } }) as unknown as ShortlistItemDto

const items = [item('a', '흑돼지식당'), item('b', '우진해장국')]

describe('확정 리스트 줄(일정에 아직 넣지 않은 곳)', () => {
  it('순서 바꾸기·밀어서 빼기·체크박스·「확정 해제」는 없고, 줄의 「넣기」가 고른 날에 넣는다', async () => {
    const onPut = vi.fn()
    const { rerender } = render(<ShortlistList items={items} dayLabel="둘째 날" onPut={onPut} onOpen={() => {}} />)

    expect(screen.queryByRole('button', { name: /순서 바꾸기/ })).not.toBeInTheDocument()
    expect(screen.queryByRole('button', { name: /빼기/ })).not.toBeInTheDocument()
    expect(screen.queryByRole('checkbox')).not.toBeInTheDocument()
    expect(screen.queryByRole('button', { name: '확정 해제' })).not.toBeInTheDocument()

    await userEvent.click(screen.getByRole('button', { name: '우진해장국 둘째 날에 넣기' }))
    expect(onPut).toHaveBeenCalledWith(expect.objectContaining({ id: 'b' }))

    // 여행 날짜가 없으면 넣을 곳이 없어 「넣기」도 없다.
    rerender(<ShortlistList items={items} dayLabel="" onOpen={() => {}} />)
    expect(screen.queryByRole('button', { name: /넣기/ })).not.toBeInTheDocument()
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

    // 리스트는 확정 탭의 리스트 자리(UNSET_DAY 칸) 안에 있다.
    const zone = document.body.appendChild(document.createElement('div'))
    zone.dataset.day = 'unset'
    const { container, rerender } = render(<ShortlistList items={items} dayLabel="첫째 날" onOpen={() => {}} />, { container: zone })
    expect(container.querySelector('.cursor-grab')).toBeNull()

    rerender(<ShortlistList items={items} dayLabel="첫째 날" onOpen={() => {}} onDrop={onDrop} />)
    const handle = container.querySelectorAll<HTMLElement>('.cursor-grab')[0]
    fireEvent.pointerDown(handle, { clientX: 400, clientY: 100, pointerId: 1 })
    fireEvent.pointerMove(handle, { clientX: 640, clientY: 280, pointerId: 1 })
    // 끄는 동안 글자 선택이 시작되지 않고(사파리가 지나간 글을 선택해 통째로 끌었다), 끄는 곳이 html에 적힌다(놓을 칸만 밝게).
    expect(fireEvent(document.body, new Event('selectstart', { bubbles: true, cancelable: true }))).toBe(false)
    expect(document.documentElement.dataset.scheduleDrag).toBe('list')
    fireEvent.pointerUp(handle, { clientX: 640, clientY: 280, pointerId: 1 })
    expect(fireEvent(document.body, new Event('selectstart', { bubbles: true, cancelable: true }))).toBe(true)
    expect(document.documentElement.dataset.scheduleDrag).toBeUndefined()

    // 손가락(280)이 줄 가운데(320)보다 위라 그 줄 앞(0번째)이다.
    expect(onDrop).toHaveBeenCalledWith(expect.objectContaining({ id: 'a' }), { day: '2026-10-11', index: 0 })
    day.remove()
    zone.remove()
    delete doc.elementFromPoint
  })
})
