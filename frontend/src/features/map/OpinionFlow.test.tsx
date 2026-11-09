import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen, within } from '@testing-library/react'
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
