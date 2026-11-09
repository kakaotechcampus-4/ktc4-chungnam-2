import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { http, HttpResponse } from 'msw'
import { server, resetScenario } from '@pingo/contracts/mocks/node'
import { MemoryRouter, Outlet, Route, Routes, useLocation } from 'react-router'
import { afterAll, afterEach, beforeAll, describe, expect, it, vi } from 'vitest'

import type { ShellContext } from '@/features/shell/shellContext'

import CourseTab from './CourseTab'

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

const shell: ShellContext = { mapId: 'map_1', activeControl: null, onControl: () => {}, connection: { state: 'open', reconnect: () => {} }, getCenter: () => null, showRegion: () => {} }

function renderTab(entry: string) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return render(
    <QueryClientProvider client={client}>
      <MemoryRouter initialEntries={[entry]}>
        <Routes>
          <Route path="/maps/:mapId" element={<Outlet context={shell} />}>
            <Route path="course" element={<><CourseTab /><Where /></>} />
          </Route>
        </Routes>
      </MemoryRouter>
    </QueryClientProvider>,
  )
}

function Where() {
  const { pathname, search } = useLocation()
  return <p data-testid="where">{pathname + search}</p>
}

describe('AI 코스 탭 — 핀 상세(#1127 리뷰)', () => {
  it('지도에서 고른 핀(?pin=)은 코스 탭 안에서 열리고, 「‹ AI 코스」로 코스 화면에 돌아온다', async () => {
    const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
    render(
      <QueryClientProvider client={client}>
        <MemoryRouter initialEntries={['/maps/map_1/course?pin=pin_1']}>
          <Routes>
            <Route path="/maps/:mapId" element={<Outlet context={shell} />}>
              <Route path="course" element={<><CourseTab /><Where /></>} />
            </Route>
          </Routes>
        </MemoryRouter>
      </QueryClientProvider>,
    )
    const back = await screen.findByRole('button', { name: /AI 코스/ })
    expect(screen.queryByText('AI 코스 짜기')).not.toBeInTheDocument()
    await userEvent.click(back)
    expect(await screen.findByText('AI 코스 짜기')).toBeInTheDocument()
    expect(screen.getByTestId('where')).toHaveTextContent('/maps/map_1/course')
    expect(screen.getByTestId('where')).not.toHaveTextContent('pin=')
  })
})

describe('AI 코스 날짜별 카드의 장소 줄(#1692)', () => {
  it('분류, 의견 수를 보이고, 누르면 그 핀을 골라(?pin=) 탭 안에서 핀 상세가 열린다', async () => {
    for (const pin_id of ['pin_1', 'pin_2']) {
      await fetch('http://localhost/maps/map_1/shortlist', { method: 'POST', body: JSON.stringify({ pin_id }) })
    }
    const done = {
      id: 'run_card', map_id: 'map_1', status: 'done', outcome: 'solved', failure_code: null, goals: [], unmatched: [],
      steps: [], days: [{ date: '2026-10-10', slots: [{ pin_id: 'pin_1', order: 1, needs_check: true }, { pin_id: 'pin_2', order: 2, needs_check: true }], legs: [] }],
      violations: [], checks: [], excluded: [], snapshot_at: '2026-10-21T00:00:00Z', stale: false,
      created_at: '2026-10-21T00:00:00Z', finished_at: '2026-10-21T00:00:00Z',
    }
    server.use(http.get('*/maps/:mapId/courses/latest', () => HttpResponse.json(done)))
    const user = userEvent.setup({ delay: null })
    renderTab('/maps/map_1/course')
    await user.click(await screen.findByRole('button', { name: '최근 코스 보기' }))

    const day = await screen.findByRole('article')
    const row = await within(day).findByRole('button', { name: /흑돼지식당/ })
    expect(row).toHaveTextContent('음식점')
    expect(within(row).getByLabelText(/좋음 \d+, 반대 \d+, 미확인 \d+/)).toBeInTheDocument()

    await user.click(row)
    expect(screen.getByTestId('where')).toHaveTextContent('pin=pin_1')
    expect(await screen.findByRole('button', { name: /AI 코스/ })).toBeInTheDocument() // 핀 상세의 뒤로 가기
  })
})
