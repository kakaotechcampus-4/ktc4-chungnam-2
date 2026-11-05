import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen } from '@testing-library/react'
import { server, resetScenario } from '@pingo/contracts/mocks/node'
import { MemoryRouter, Outlet, Route, Routes } from 'react-router'
import { afterAll, afterEach, beforeAll, describe, expect, it, vi } from 'vitest'

import type { ShellContext } from './shellContext'
import type { TabKey } from './sheetStore'
import TabSheet from './TabSheet'

beforeAll(() => {
  server.listen({ onUnhandledRequest: 'error' })
  // 휴대폰 화면 — 지도 버튼과 조언 버튼이 시트 윗변에 붙는다.
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

const shell: ShellContext = { mapId: 'map_1', activeControl: null, onControl: () => {}, connection: { state: 'open', reconnect: () => {} }, getCenter: () => null, showRegion: () => {} }

describe('「핑고 AI 조언」 버튼(#1162)', () => {
  it.each<TabKey>(['map', 'recommend', 'shortlist', 'course'])('지도가 떠 있는 %s 탭에서도 보인다', async (tab) => {
    const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
    render(
      <QueryClientProvider client={client}>
        <MemoryRouter initialEntries={['/maps/map_1']}>
          <Routes>
            <Route path="/maps/:mapId" element={<Outlet context={shell} />}>
              <Route index element={<TabSheet tab={tab} header={<p>머리</p>}>본문</TabSheet>} />
            </Route>
          </Routes>
        </MemoryRouter>
      </QueryClientProvider>,
    )
    expect(await screen.findByRole('button', { name: /^핑고 AI 조언/ })).toBeVisible()
  })
})
