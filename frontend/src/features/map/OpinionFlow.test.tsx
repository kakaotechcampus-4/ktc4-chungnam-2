import { QueryClient, QueryClientProvider, useQuery } from '@tanstack/react-query'
import { fireEvent, render, screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { server, resetScenario } from '@pingo/contracts/mocks/node'
import type { ReactNode } from 'react'
import { MemoryRouter } from 'react-router'
import { afterAll, afterEach, beforeAll, describe, expect, it, vi } from 'vitest'

import { fetchPins } from './api'
import { isTodo, type Pin } from './model'
import { PinDetailBody } from './PinDetail'
import PinList from './PinList'
import { pinKeys } from './queries'

const MAP = 'map_1'
const members = [{ userId: 'u_me', name: '나', initial: '나', isMe: true, isOwner: true, isGuest: false }]

beforeAll(() => {
  server.listen({ onUnhandledRequest: 'error' })
  vi.stubGlobal('matchMedia', (query: string) => ({ matches: false, media: query, addEventListener() {}, removeEventListener() {}, addListener() {}, removeListener() {} }))
})
afterEach(() => {
  server.resetHandlers()
  resetScenario('happy-path')
})
afterAll(() => {
  server.close()
  vi.unstubAllGlobals()
})

function setup(ui: ReactNode, pins: Pin[]) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  client.setQueryData(pinKeys.list(MAP), pins)
  render(
    <QueryClientProvider client={client}>
      <MemoryRouter>{ui}</MemoryRouter>
    </QueryClientProvider>,
  )
  return client
}

describe('핀 찍기 목록의 할 일 묶음과 바로 반응(#1696)', () => {
  it('할 일 핀을 "의견 남길 핀"으로 위에 묶고, ✕ 반대는 상세를 반대로 연다', async () => {
    const pins = await fetchPins(MAP)
    const todo = pins.filter(isTodo)
    expect(todo.length).toBeGreaterThan(0)
    const onSelect = vi.fn()
    setup(<PinList mapId={MAP} pins={pins} memberCount={4} onSelect={onSelect} todoIds={new Set(todo.map((p) => p.id))} />, pins)

    const group = screen.getByRole('region', { name: /의견 남길 핀/ })
    expect(within(group).getAllByRole('article')).toHaveLength(todo.length)
    expect(screen.getByRole('region', { name: /나머지 핀/ })).toBeInTheDocument()

    const name = todo[0].place_name!
    await userEvent.click(within(group).getByRole('button', { name: `${name} 반대, 이유 쓰기` }))
    expect(onSelect).toHaveBeenCalledWith(todo[0].id, { against: true })
  })

  it('♥ 좋음은 목록에서 바로 등록되고, 카드는 그 자리에서 내 의견 카드가 된다', async () => {
    const pins = await fetchPins(MAP)
    const todo = pins.filter(isTodo)
    const ids = new Set(todo.map((p) => p.id))
    const client = setup(<PinList mapId={MAP} pins={pins} memberCount={4} onSelect={() => {}} todoIds={ids} />, pins)

    const name = todo[0].place_name!
    await userEvent.click(screen.getByRole('button', { name: `${name} 좋음` }))
    await vi.waitFor(() => expect(client.getQueryData<Pin[]>(pinKeys.list(MAP))!.find((p) => p.id === todo[0].id)!.my_reaction?.type).toBe('like'))
  })
  it('♥는 버튼 안에서 끝난 표시를 보인 뒤 카드가 남김 모양이 된다(#1736)', async () => {
    const pins = await fetchPins(MAP)
    const todo = pins.filter(isTodo)
    setup(<LiveList initial={pins} todoIds={new Set(todo.map((p) => p.id))} />, pins)

    const name = todo[0].place_name!
    const like = screen.getByRole('button', { name: `${name} 좋음` })
    await userEvent.click(like)
    // 등록이 끝나도 바로 사라지지 않고 초록 "남겼어요"를 보인다.
    await vi.waitFor(() => expect(like).toHaveClass('btn-done'))
    expect(like).toHaveTextContent('남겼어요')
    // 잠시 뒤 카드가 남김 모양(내 의견 태그)이 되고 반응 버튼이 사라진다.
    await vi.waitFor(() => expect(screen.queryByRole('button', { name: `${name} 좋음` })).not.toBeInTheDocument(), { timeout: 3000 })
  })
})

/** 캐시를 읽어 다시 그리는 목록 — 실제 화면처럼 ♥ 뒤 바뀐 핀이 카드에 반영된다. */
function LiveList({ initial, todoIds }: { initial: Pin[]; todoIds: ReadonlySet<string> }) {
  const { data } = useQuery({ queryKey: pinKeys.list(MAP), queryFn: () => initial, staleTime: Infinity })
  return <PinList mapId={MAP} pins={data ?? initial} memberCount={4} onSelect={() => {}} todoIds={todoIds} />
}

describe('핀 카드를 누르면 상세가 열린다(#1724)', () => {
  it('포인터를 붙잡아 클릭이 카드로 와도 열리고, 이름 버튼은 한 번만, 바로 반응 버튼은 열지 않는다', async () => {
    const pins = await fetchPins(MAP)
    const todo = pins.filter(isTodo)
    const done = pins.filter((p) => !isTodo(p))
    const onSelect = vi.fn()
    setup(<PinList mapId={MAP} pins={pins} memberCount={4} onSelect={onSelect} todoIds={new Set(todo.map((p) => p.id))} />, pins)

    const name = done[0].place_name!
    const nameButton = screen.getByRole('button', { name: new RegExp(`^${name} `) })
    // 끌어서 버리기가 포인터를 붙잡으면 클릭의 대상은 이름 버튼이 아니라 카드다.
    fireEvent.click(nameButton.closest('article')!)
    expect(onSelect).toHaveBeenLastCalledWith(done[0].id, undefined)
    expect(onSelect).toHaveBeenCalledTimes(1)

    fireEvent.click(nameButton)
    expect(onSelect).toHaveBeenCalledTimes(2)

    onSelect.mockClear()
    await userEvent.click(screen.getByRole('button', { name: `${todo[0].place_name} 좋음` }))
    expect(onSelect).not.toHaveBeenCalled()
  })
})

describe('핀 상세 내 의견(#1696)', () => {
  it('처음 남기는 ♥는 바로 등록하고 목록으로 돌아간다', async () => {
    const pin = (await fetchPins(MAP)).find(isTodo)!
    const onDone = vi.fn()
    setup(<PinDetailBody pin={pin} mapId={MAP} members={members} onDone={onDone} />, [pin])

    expect(screen.getByRole('heading', { name: '이곳 어때요?' })).toBeInTheDocument()
    await userEvent.click(screen.getByRole('radio', { name: '좋음' }))
    await vi.waitFor(() => expect(onDone).toHaveBeenCalled())
  })

  it('목록의 ✕로 열면 반대가 골라진 채로 사유 입력이 보인다', async () => {
    const pin = (await fetchPins(MAP)).find(isTodo)!
    setup(<PinDetailBody pin={pin} mapId={MAP} members={members} startAgainst onDone={() => {}} />, [pin])

    expect(screen.getByRole('radio', { name: '반대' })).toHaveAttribute('aria-checked', 'true')
    expect(screen.getByRole('button', { name: '반대 남기기' })).toBeInTheDocument()
  })

  it('남긴 의견은 한 줄로 접히고 "고치기"로 다시 연다', async () => {
    const pin = (await fetchPins(MAP)).find((p) => p.my_reaction)!
    setup(<PinDetailBody pin={pin} mapId={MAP} members={members} onDone={() => {}} />, [pin])

    expect(screen.queryByRole('radiogroup', { name: '내 의견' })).toBeNull()
    await userEvent.click(screen.getByRole('button', { name: '고치기' }))
    expect(screen.getByRole('radiogroup', { name: '내 의견' })).toBeInTheDocument()
    expect(screen.getByRole('button', { name: '의견 취소' })).toBeInTheDocument()
  })
})
