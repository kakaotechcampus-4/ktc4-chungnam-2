import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { fireEvent, render, screen, within, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { server, resetScenario } from '@pingo/contracts/mocks/node'
import { MemoryRouter, Outlet, Route, Routes } from 'react-router'
import { afterAll, afterEach, beforeAll, beforeEach, describe, expect, it, vi } from 'vitest'

import type { ShellContext } from '@/features/shell/shellContext'
import { useToastStore } from '@/features/shell/toast'
import { useRouteStore } from '@/features/shortlist/routeStore'
import { serverDays } from '@/features/shortlist/__fixtures__/serverSchedule'
import { forgetSchedule } from '@/features/shortlist/scheduleStore'

import ShortlistTab from './ShortlistTab'

const BASE = 'http://localhost'
const MAP = 'map_1' // 목 서버 지도: 2026-10-10 ~ 10-12(3일)

beforeAll(() => {
  server.listen({ onUnhandledRequest: 'error' })
  // 휴대폰 폭(넓은 화면이 아니다).
  vi.stubGlobal('matchMedia', (query: string) => ({ matches: false, media: query, addEventListener() {}, removeEventListener() {}, addListener() {}, removeListener() {} }))
})
afterEach(() => {
  server.resetHandlers()
  resetScenario('happy-path')
  forgetSchedule()
  useRouteStore.setState({ on: false, day: null })
  useToastStore.setState(useToastStore.getInitialState())
})
afterAll(() => {
  server.close()
  vi.unstubAllGlobals()
})

// 목 서버의 확정 리스트에 핀 셋을 넣는다(흑돼지식당·우진해장국·카페 한라).
beforeEach(async () => {
  for (const pin_id of ['pin_1', 'pin_2', 'pin_3']) {
    await fetch(`${BASE}/maps/${MAP}/shortlist`, { method: 'POST', body: JSON.stringify({ pin_id }) })
  }
})

const shell: ShellContext = { mapId: MAP, activeControl: null, onControl: () => {}, connection: { state: 'open', reconnect: () => {} } }

function renderTab() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return render(
    <QueryClientProvider client={client}>
      <MemoryRouter initialEntries={[`/maps/${MAP}/shortlist`]}>
        <Routes>
          <Route path="/maps/:mapId" element={<Outlet context={shell} />}>
            <Route path="shortlist" element={<ShortlistTab />} />
          </Route>
        </Routes>
      </MemoryRouter>
    </QueryClientProvider>,
  )
}

async function putTwoOnSecondDay() {
  await userEvent.click(await screen.findByRole('checkbox', { name: '흑돼지식당 고르기' }))
  await userEvent.click(screen.getByRole('checkbox', { name: '우진해장국 고르기' }))
  await userEvent.selectOptions(screen.getByLabelText('넣을 날짜'), '둘째 날')
  await userEvent.click(screen.getByRole('button', { name: '2곳 넣기' }))
}

describe('확정 탭 — 체크박스로 일정에 넣기, 동선 보기로 날짜별 일정(휴대폰)', () => {
  it('휴대폰에는 「일정 짜기」 패널 칩이 없고, 일정이 비어 있으면 동선 보기 대신 넣는 법을 알린다', async () => {
    renderTab()
    await screen.findByRole('checkbox', { name: '흑돼지식당 고르기' })
    expect(screen.queryByRole('button', { name: '일정 짜기' })).not.toBeInTheDocument()
    await userEvent.click(screen.getByRole('button', { name: '동선 보기' }))
    expect(await screen.findByText('장소를 골라 날짜에 넣으면 동선을 볼 수 있어요')).toBeInTheDocument()
    expect(useRouteStore.getState().on).toBe(false)
  })

  it('고른 곳을 한 번에 그날로 넣으면 리스트에서 빠지고 토스트가 알린다 — 되돌리기로 돌아온다', async () => {
    renderTab()
    await putTwoOnSecondDay()

    expect(await screen.findByText('2곳을 둘째 날에 넣었어요')).toBeInTheDocument()
    await waitFor(async () => expect((await serverDays(MAP))['2026-10-11']).toEqual(['pin_1', 'pin_2']))
    expect(screen.queryByRole('checkbox', { name: '흑돼지식당 고르기' })).not.toBeInTheDocument()
    expect(screen.getByText('1곳 · 일정에 넣은 곳 2')).toBeInTheDocument()

    await userEvent.click(screen.getByRole('button', { name: '되돌리기' }))
    expect(await screen.findByRole('checkbox', { name: '흑돼지식당 고르기' })).toBeInTheDocument()
    await waitFor(async () => expect(await serverDays(MAP)).toEqual({}))
  })

  it('동선 보기를 켜면 날짜 칩과 그날 순서가 보이고, ↑↓ 로 순서를 바꾸고 「빼기」로 리스트에 돌린다', async () => {
    renderTab()
    await putTwoOnSecondDay()
    await userEvent.click(screen.getByRole('button', { name: '동선 보기' }))

    // 장소를 넣은 첫 날(둘째 날)이 골라져 있다.
    const days = within(await screen.findByRole('group', { name: '볼 날짜' }))
    expect(days.getByRole('button', { name: '둘째 날' })).toHaveAttribute('aria-pressed', 'true')
    const second = () => within(screen.getByRole('region', { name: /^둘째 날/ }))
    expect(second().getAllByRole('listitem').map((li) => li.textContent)).toEqual([expect.stringMatching(/^1흑돼지식당/), expect.stringMatching(/^2우진해장국/)])
    expect(screen.getByRole('link', { name: /카카오맵에서 길찾기/ })).toHaveAttribute('href', expect.stringContaining('map.kakao.com/link/by/walk/'))

    fireEvent.keyDown(second().getByRole('button', { name: '흑돼지식당 순서 바꾸기' }), { key: 'ArrowDown' })
    await waitFor(async () => expect((await serverDays(MAP))['2026-10-11']).toEqual(['pin_2', 'pin_1']))

    await userEvent.click(second().getByRole('button', { name: '우진해장국 일정에서 빼기' }))
    expect(await screen.findByText('우진해장국을 일정에서 뺐어요')).toBeInTheDocument()
    await waitFor(async () => expect((await serverDays(MAP))['2026-10-11']).toEqual(['pin_1']))

    // 다른 날은 비어 있다.
    await userEvent.click(days.getByRole('button', { name: '첫째 날' }))
    expect(within(screen.getByRole('region', { name: /^첫째 날/ })).getByText('이 날은 비어 있어요')).toBeInTheDocument()

    await userEvent.click(screen.getByRole('button', { name: /동선 보기/ }))
    expect(await screen.findByRole('checkbox', { name: '우진해장국 고르기' })).toBeInTheDocument()
  })

  it('넓은 화면의 「일정 짜기」는 다시 누르면 닫힌다', async () => {
    vi.stubGlobal('matchMedia', (query: string) => ({ matches: true, media: query, addEventListener() {}, removeEventListener() {}, addListener() {}, removeListener() {} }))
    try {
      renderTab()
      const chip = await screen.findByRole('button', { name: '일정 짜기' })
      expect(chip).toHaveAttribute('aria-pressed', 'false')
      await userEvent.click(chip)
      expect(chip).toHaveAttribute('aria-pressed', 'true')
      await userEvent.click(chip)
      expect(chip).toHaveAttribute('aria-pressed', 'false')
    } finally {
      vi.stubGlobal('matchMedia', (query: string) => ({ matches: false, media: query, addEventListener() {}, removeEventListener() {}, addListener() {}, removeListener() {} }))
    }
  })
})
