import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen, within } from '@testing-library/react'
import { server, resetScenario } from '@pingo/contracts/mocks/node'
import { http, HttpResponse } from 'msw'
import type { ReactNode } from 'react'
import { MemoryRouter } from 'react-router'
import { afterAll, afterEach, beforeAll, expect, it, vi } from 'vitest'

import { fetchPins } from './api'
import type { Pin } from './model'
import { PinDetailBody } from './PinDetail'

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

function renderBody(pin: Pin) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  const ui: ReactNode = (
    <QueryClientProvider client={client}>
      <MemoryRouter>
        <PinDetailBody pin={pin} mapId={MAP} members={members} onDone={() => {}} />
      </MemoryRouter>
    </QueryClientProvider>
  )
  return render(ui)
}

it('#1157 자체 DB 핀 상세에 블로그 사진 3장이 원문 링크로 뜬다', async () => {
  const pin = (await fetchPins(MAP))[0] as Pin
  renderBody(pin)
  const row = await screen.findByRole('region', { name: '블로그 사진' })
  expect(within(row).getAllByRole('link')).toHaveLength(3)
})

it('#1157 실시간 핀은 사진을 부르지도 그리지도 않는다', async () => {
  let called = false
  server.use(http.get('*/pins/:pinId/photos', () => { called = true; return HttpResponse.json([]) }))
  const pin = { ...((await fetchPins(MAP))[0] as Pin), source: 'live' as const }
  renderBody(pin)
  await screen.findAllByText(/의견/)
  expect(screen.queryByRole('region', { name: '블로그 사진' })).toBeNull()
  expect(called).toBe(false)
})

it('#1157 사진을 못 받으면 조용히 넘기지 않고 짧게 알린다', async () => {
  server.use(http.get('*/pins/:pinId/photos', () => HttpResponse.json({ code: 'PLACES_UNAVAILABLE', message: 'x' }, { status: 503 })))
  const pin = (await fetchPins(MAP))[0] as Pin
  renderBody(pin)
  expect(await screen.findByText('사진을 불러오지 못했어요')).toBeInTheDocument()
})
