import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
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

const shell: ShellContext = { mapId: 'map_1', activeControl: null, onControl: () => {}, connection: { state: 'open', reconnect: () => {} } }

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
