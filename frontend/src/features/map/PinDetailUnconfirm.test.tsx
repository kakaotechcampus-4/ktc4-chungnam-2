import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { server, resetScenario } from '@pingo/contracts/mocks/node'
import { MemoryRouter } from 'react-router'
import { afterAll, afterEach, beforeAll, expect, it, vi } from 'vitest'

import { useToastStore } from '@/features/shell/toast'
import { fetchShortlist } from '@/features/shortlist/api'

import { PinDetailHeader } from './PinDetail'
import { usePinsQuery } from './queries'

const MAP = 'map_1'

beforeAll(() => {
  server.listen({ onUnhandledRequest: 'error' })
  // jsdom 에는 matchMedia 가 없다(넓은 화면 판정에 쓴다).
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

/** 화면처럼 핀 목록 조회에서 핀을 받아 넘긴다 — 넣고 빼면 핀 종류가 바뀌어 버튼이 따라 바뀐다. */
function Header() {
  const pin = usePinsQuery(MAP).data?.[0]
  return pin ? <PinDetailHeader pin={pin} mapId={MAP} onBack={() => {}} /> : null
}

it('확정 버튼은 켜고 끄는 버튼 하나다 — 토스트 없이 글자가 바뀌고 포커스가 남는다', async () => {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  render(
    <QueryClientProvider client={client}>
      <MemoryRouter>
        <Header />
      </MemoryRouter>
    </QueryClientProvider>,
  )

  await userEvent.click(await screen.findByRole('button', { name: '★ 확정 리스트에 넣기', pressed: false }))
  const on = await screen.findByRole('button', { name: '✓ 확정됨', pressed: true })
  expect(on).toHaveFocus()
  expect(await fetchShortlist(MAP)).toHaveLength(1)

  await userEvent.click(on)
  const off = await screen.findByRole('button', { name: '★ 확정 리스트에 넣기', pressed: false })
  expect(off).toHaveFocus()
  expect(await fetchShortlist(MAP)).toHaveLength(0)
  expect(useToastStore.getState().toast).toBeNull()
})
