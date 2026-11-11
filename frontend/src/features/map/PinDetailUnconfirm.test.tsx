import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { server, resetScenario } from '@pingo/contracts/mocks/node'
import { http, HttpResponse } from 'msw'
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

it('확정 버튼은 켜고 끄는 버튼 하나다 — 넣으면 「확정 리스트 보기」 토스트, 빼면 「되돌리기」 토스트, 버튼 포커스는 남는다', async () => {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  render(
    <QueryClientProvider client={client}>
      <MemoryRouter>
        <Header />
      </MemoryRouter>
    </QueryClientProvider>,
  )

  await userEvent.click(await screen.findByRole('button', { name: '확정하기', pressed: false }))
  const on = await screen.findByRole('button', { name: '확정됨', pressed: true })
  expect(on).toHaveFocus()
  // 버튼은 응답 전에 바뀐다(#1676) — 넣기가 끝날 때(토스트)까지 다시 누르면 무시하니, 끝난 뒤에 뺀다.
  await waitFor(() => expect(useToastStore.getState().toast?.action?.label).toBe('확정한 장소 보기'))
  expect(await fetchShortlist(MAP)).toHaveLength(1)

  useToastStore.setState({ toast: null })
  await userEvent.click(on)
  const off = await screen.findByRole('button', { name: '확정하기', pressed: false })
  expect(off).toHaveFocus()
  expect(await fetchShortlist(MAP)).toHaveLength(0)
  expect(useToastStore.getState().toast?.action?.label).toBe('되돌리기')
  // 넣고 빼며 핀·확정 리스트를 두 번씩 다시 받는다 — 부하가 높으면 기본 5초를 넘는다.
}, 15_000)

function renderHeader() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  render(
    <QueryClientProvider client={client}>
      <MemoryRouter>
        <Header />
      </MemoryRouter>
    </QueryClientProvider>,
  )
}

it('넣기는 응답 전에 확정됨으로 바뀐다(낙관적, #1676)', async () => {
  let answer: () => void = () => {}
  server.use(http.post('*/maps/:mapId/shortlist', () => new Promise<Response>((done) => (answer = () => done(HttpResponse.json({}, { status: 500 }))))))
  renderHeader()
  await userEvent.click(await screen.findByRole('button', { name: '확정하기', pressed: false }))
  // 서버는 아직 답하지 않았다.
  expect(await screen.findByRole('button', { name: '확정됨', pressed: true })).toBeInTheDocument()
  // 실패하면 그 핀만 되돌리고 알린다.
  answer()
  expect(await screen.findByRole('button', { name: '확정하기', pressed: false })).toBeInTheDocument()
  expect(useToastStore.getState().toast?.message).toBe('확정하지 못했어요')
})
