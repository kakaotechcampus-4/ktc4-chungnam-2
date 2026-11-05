import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { act, render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { server, resetScenario } from '@pingo/contracts/mocks/node'
import { useState } from 'react'
import { MemoryRouter } from 'react-router'
import { afterAll, afterEach, beforeAll, describe, expect, it, vi } from 'vitest'

import { useToastStore } from '@/features/shell/toast'
import { addToShortlist } from '@/features/shortlist/api'

import { createPin, deletePin } from './api'
import type { Pin } from './model'
import { attachTrashDrag, usePinDragStore } from './pinDrag'
import PinTrashSheet from './PinTrashSheet'
import { usePinsQuery, useTrashPinMutation } from './queries'

const MAP = 'map_1'

/** jsdom 에는 PointerEvent 가 없을 수 있어 MouseEvent 에 포인터 값만 얹는다. */
function fire(el: Element, type: string, x: number, y: number, pointerType = 'mouse') {
  const e = new MouseEvent(type, { bubbles: true, cancelable: true, clientX: x, clientY: y, button: 0 })
  Object.defineProperties(e, { pointerId: { value: 1 }, pointerType: { value: pointerType } })
  el.dispatchEvent(e)
}

describe('핀 끌기(#1012)', () => {
  const pin = { id: 'pin_x', kind: '일반' } as Pin
  function setup() {
    usePinDragStore.setState({ drag: null })
    const bin = document.createElement('div')
    bin.setAttribute('data-trash-bin', '')
    bin.getBoundingClientRect = () => ({ left: 200, right: 260, top: 400, bottom: 450, width: 60, height: 50 }) as DOMRect
    const el = document.createElement('button')
    const clicked = vi.fn()
    el.addEventListener('click', clicked)
    document.body.append(bin, el)
    const detach = attachTrashDrag(el, () => pin, () => '<svg></svg>')
    return { el, clicked, detach: () => (detach(), bin.remove(), el.remove()) }
  }
  const drag = () => usePinDragStore.getState().drag

  it('마우스: 끌어서 휴지통 위에 놓으면 지운다(drop), 놓은 뒤 클릭은 상세를 열지 않는다', () => {
    const { el, clicked, detach } = setup()
    fire(el, 'pointerdown', 10, 10)
    fire(el, 'pointermove', 14, 12)
    expect(drag()).toBeNull() // 8px 안은 그냥 누르기
    fire(el, 'pointermove', 100, 100)
    expect(drag()).toMatchObject({ phase: 'drag', over: false })
    fire(el, 'pointermove', 230, 420)
    expect(drag()?.over).toBe(true)
    fire(el, 'pointerup', 230, 420)
    expect(drag()).toMatchObject({ phase: 'drop', pin })
    el.click()
    expect(clicked).not.toHaveBeenCalled()
    detach()
  })

  it('마우스: 휴지통 밖에서 놓으면 그대로 둔다', () => {
    const { el, detach } = setup()
    fire(el, 'pointerdown', 10, 10)
    fire(el, 'pointermove', 100, 100)
    fire(el, 'pointerup', 100, 100)
    expect(drag()).toBeNull()
    expect(el.style.opacity).toBe('')
    detach()
  })

  it('터치: 짧게 누르면 상세(클릭), 0.4초 전에 움직이면 지도 끌기, 길게 누르면 집는다', () => {
    vi.useFakeTimers()
    const { el, clicked, detach } = setup()
    fire(el, 'pointerdown', 10, 10, 'touch')
    vi.advanceTimersByTime(200)
    fire(el, 'pointerup', 10, 10, 'touch')
    el.click()
    expect(clicked).toHaveBeenCalledTimes(1)
    expect(drag()).toBeNull()

    fire(el, 'pointerdown', 10, 10, 'touch')
    fire(el, 'pointermove', 40, 10, 'touch')
    vi.advanceTimersByTime(500)
    expect(drag()).toBeNull()
    fire(el, 'pointerup', 40, 10, 'touch')

    fire(el, 'pointerdown', 10, 10, 'touch')
    vi.advanceTimersByTime(400)
    expect(drag()).toMatchObject({ phase: 'drag', touch: true })
    fire(el, 'pointerup', 10, 10, 'touch')
    el.click()
    expect(clicked).toHaveBeenCalledTimes(1) // 집었다 놓으면 상세가 열리지 않는다

    // 집었다 놓은 뒤 click 이 오지 않아도(모바일에서 흔하다) 다음 짧은 탭은 상세를 연다.
    fire(el, 'pointerdown', 10, 10, 'touch')
    vi.advanceTimersByTime(400)
    fire(el, 'pointerup', 10, 10, 'touch')
    fire(el, 'pointerdown', 10, 10, 'touch')
    fire(el, 'pointerup', 10, 10, 'touch')
    el.click()
    expect(clicked).toHaveBeenCalledTimes(2)
    detach()
    vi.useRealTimers()
  })
})

describe('삭제와 되돌리기(목 서버)', () => {
  beforeAll(() => {
    server.listen({ onUnhandledRequest: 'error' })
    vi.stubGlobal('matchMedia', (query: string) => ({ matches: false, media: query, addEventListener() {}, removeEventListener() {}, addListener() {}, removeListener() {} }))
  })
  afterEach(() => {
    server.resetHandlers()
    resetScenario('happy-path')
    useToastStore.setState({ toast: null })
  })
  afterAll(() => {
    server.close()
    vi.unstubAllGlobals()
  })

  function Harness() {
    const pins = usePinsQuery(MAP).data
    const trash = useTrashPinMutation(MAP)
    const [sheet, setSheet] = useState(false)
    return (
      <>
        <ul aria-label="핀">{pins?.map((p) => <li key={p.id}>{p.place_name}</li>)}</ul>
        {pins?.map((p) => (
          <button key={p.id} type="button" onClick={() => trash.mutate(p)}>
            {p.place_name} 지우기
          </button>
        ))}
        <button type="button" onClick={() => setSheet(true)}>
          삭제한 핀
        </button>
        {sheet && <PinTrashSheet mapId={MAP} onClose={() => {}} />}
      </>
    )
  }
  function renderHarness() {
    const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
    render(
      <QueryClientProvider client={client}>
        <MemoryRouter>
          <Harness />
        </MemoryRouter>
      </QueryClientProvider>,
    )
  }
  const list = (opts?: { hidden: boolean }) => screen.getByRole('list', { name: '핀', ...opts })

  it('확정 핀을 지우면 「확정 리스트에서도 빠졌어요」, 「되돌리기」로 핀이 돌아온다', async () => {
    await addToShortlist(MAP, 'pin_1')
    renderHarness()
    await userEvent.click(await screen.findByRole('button', { name: '흑돼지식당 지우기' }))
    await waitFor(() => expect(useToastStore.getState().toast?.message).toBe('확정 리스트에서도 빠졌어요'))
    expect(within(list()).queryByText('흑돼지식당')).toBeNull()

    act(() => useToastStore.getState().toast?.action?.onClick())
    expect(await within(list()).findByText('흑돼지식당')).toBeInTheDocument()
  }, 15_000)

  it('「삭제한 핀」에서 되돌리고, 같은 장소에 새 핀이 있으면 「이미 지도에 같은 장소가 있어요」', async () => {
    const body = { source: 'search', place_id: 'kakao:mock-5', place_name: '제주 흑돼지 거리', lat: 33.5131, lng: 126.5296, category: '음식점' } as const
    const first = await createPin(MAP, body)
    await deletePin(first.id)
    await createPin(MAP, body)
    renderHarness()

    await userEvent.click(await screen.findByRole('button', { name: '우진해장국 지우기' }))
    await waitFor(() => expect(useToastStore.getState().toast?.message).toBe('삭제했어요'))
    await userEvent.click(screen.getByRole('button', { name: '삭제한 핀' }))

    const row = (await screen.findByText('우진해장국', { selector: 'p' })).closest('li')!
    await userEvent.click(within(row).getByRole('button', { name: '되돌리기' }))
    await waitFor(() => expect(useToastStore.getState().toast?.message).toBe('우진해장국을 되돌렸어요'))
    await waitFor(() => expect(within(list({ hidden: true })).getByText('우진해장국')).toBeInTheDocument())

    const dupRow = (await screen.findByText('제주 흑돼지 거리', { selector: 'p' })).closest('li')!
    await userEvent.click(within(dupRow).getByRole('button', { name: '되돌리기' }))
    expect(await within(dupRow).findByText('이미 지도에 같은 장소가 있어요')).toBeInTheDocument()
  }, 15_000)
})
