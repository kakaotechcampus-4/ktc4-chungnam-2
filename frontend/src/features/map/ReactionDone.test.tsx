import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { server, resetScenario } from '@pingo/contracts/mocks/node'
import { MemoryRouter } from 'react-router'
import { afterAll, afterEach, beforeAll, expect, it, vi } from 'vitest'

import { fetchPins } from './api'
import { PinDetailBody } from './PinDetail'

const MAP = 'map_1'

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

const members = [{ userId: 'u_me', name: '나', initial: '나', isMe: true, isOwner: true, isGuest: false }]

it('의견 등록이 끝나면 버튼이 잠깐 "등록했어요"가 된 뒤 목록으로 돌아간다(#1712)', async () => {
  const pin = (await fetchPins(MAP)).find((p) => p.kind !== '확정' && !p.my_reaction)!
  const onDone = vi.fn()
  render(
    <QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}>
      <MemoryRouter>
        <PinDetailBody pin={pin} mapId={MAP} members={members} onDone={onDone} />
      </MemoryRouter>
    </QueryClientProvider>,
  )
  await userEvent.click(await screen.findByRole('radio', { name: '좋음' }))
  await userEvent.click(screen.getByRole('button', { name: '의견 등록' }))

  expect(await screen.findByRole('button', { name: '등록했어요' })).toHaveClass('btn-done')
  expect(onDone).not.toHaveBeenCalled()
  await waitFor(() => expect(onDone).toHaveBeenCalledTimes(1), { timeout: 2000 })
})
