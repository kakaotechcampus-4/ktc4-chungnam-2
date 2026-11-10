import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { server, resetScenario } from '@pingo/contracts/mocks/node'
import { MemoryRouter, Outlet, Route, Routes, useLocation } from 'react-router'
import { afterAll, afterEach, beforeAll, describe, expect, it, vi } from 'vitest'

import type { ShellContext } from '@/features/shell/shellContext'

import MeTab from './MeTab'

beforeAll(() => {
  server.listen({ onUnhandledRequest: 'error' })
  // 휴대폰 화면 — 프로필 탭은 휴대폰에만 있다.
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

function Where() {
  const { search } = useLocation()
  return <p data-testid="where">{search}</p>
}

function renderTab() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return render(
    <QueryClientProvider client={client}>
      <MemoryRouter initialEntries={['/maps/map_1/me']}>
        <Routes>
          <Route path="/maps/:mapId" element={<Outlet context={shell} />}>
            <Route path="me" element={<><MeTab /><Where /></>} />
          </Route>
        </Routes>
      </MemoryRouter>
    </QueryClientProvider>,
  )
}

describe('프로필 탭은 알림함, 설정, 지도 정보를 같은 시트 안에서 연다(#1710)', () => {
  it.each([
    ['알림 종', /^알림/, 'alerts', '모두 읽음'],
    ['설정 톱니', '설정', 'settings', '로그아웃'],
    ['지도 정보 버튼', '지도 정보', 'map', '초대 링크 공유하기'],
  ])('%s을 누르면 모달 없이 시트 내용이 바뀌고, ‹ 프로필로 돌아온다', async (_, opener, view, inside) => {
    const user = userEvent.setup()
    renderTab()
    await user.click(await screen.findByRole('button', { name: opener }))

    expect(await screen.findByRole('button', { name: inside })).toBeVisible()
    expect(screen.queryByRole('dialog')).toBeNull()
    expect(screen.getByTestId('where')).toHaveTextContent(`?view=${view}`)

    await user.click(screen.getByRole('button', { name: '프로필' }))
    expect(await screen.findByRole('heading', { name: '프로필' })).toBeVisible()
    expect(screen.getByTestId('where')).toBeEmptyDOMElement()
  })

  it('알림 설정은 알림 아래 한 단계이고, ‹ 알림으로 알림함에 돌아온다', async () => {
    const user = userEvent.setup()
    renderTab()
    await user.click(await screen.findByRole('button', { name: /^알림/ }))
    await user.click(await screen.findByRole('button', { name: '설정' }))

    expect(await screen.findByRole('heading', { name: '알림 설정' })).toBeVisible()
    expect(screen.getByTestId('where')).toHaveTextContent('?view=alert-settings')

    await user.click(screen.getByRole('button', { name: '알림' }))
    expect(await screen.findByRole('button', { name: '모두 읽음' })).toBeVisible()
  })
})
