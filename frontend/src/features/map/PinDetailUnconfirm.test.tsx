import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { server, resetScenario } from '@pingo/contracts/mocks/node'
import { MemoryRouter } from 'react-router'
import { afterAll, afterEach, beforeAll, expect, it, vi } from 'vitest'

import { useToastStore } from '@/features/shell/toast'
import { addToShortlist, fetchShortlist } from '@/features/shortlist/api'

import { fetchPins } from './api'
import type { Pin } from './model'
import { PinDetailHeader } from './PinDetail'

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

it('「✓ 확정됨」을 다시 누르면 확정 리스트에서 빠지고 「되돌리기」 토스트가 뜬다', async () => {
  const item = await addToShortlist(MAP, (await fetchPins(MAP))[0].id)
  const pin: Pin = { ...item.pin, kind: '확정', permissions: { ...item.pin.permissions, can_remove_from_shortlist: true } }
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  render(
    <QueryClientProvider client={client}>
      <MemoryRouter>
        <PinDetailHeader pin={pin} mapId={MAP} onBack={() => {}} />
      </MemoryRouter>
    </QueryClientProvider>,
  )

  const button = screen.getByRole('button', { name: '✓ 확정됨', pressed: true })
  // 항목 id는 확정 리스트를 받아야 안다 — 받기 전에 누르면 안내만 한다.
  await waitFor(() => expect(client.getQueryData(['shortlist', MAP])).toBeDefined())
  await userEvent.click(button)

  await waitFor(() => expect(useToastStore.getState().toast?.action?.label).toBe('되돌리기'))
  expect((await fetchShortlist(MAP)).some((i) => i.id === item.id)).toBe(false)
})
