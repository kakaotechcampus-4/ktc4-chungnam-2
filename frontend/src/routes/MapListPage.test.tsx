import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter, Route, Routes } from 'react-router'
import { afterAll, afterEach, beforeAll, beforeEach, describe, expect, it, vi } from 'vitest'
import { resetScenario, server } from '@pingo/contracts/mocks/node'

import MapListPage from './MapListPage'

beforeAll(() => server.listen({ onUnhandledRequest: 'error' }))
beforeEach(() => {
  resetScenario('happy-path')
  localStorage.setItem('welcomeSeen', '1')
  // 휴대폰 폭(useIsDesktop 이 false).
  vi.stubGlobal('matchMedia', (query: string) => ({ matches: false, media: query, addEventListener() {}, removeEventListener() {}, addListener() {}, removeListener() {} }))
})
afterEach(() => {
  vi.unstubAllGlobals()
  server.resetHandlers()
  localStorage.clear()
})
afterAll(() => server.close())

function setup() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  render(
    <QueryClientProvider client={client}>
      <MemoryRouter initialEntries={['/']}>
        <Routes>
          <Route path="/" element={<MapListPage />} />
        </Routes>
      </MemoryRouter>
    </QueryClientProvider>,
  )
}

describe('내 지도 목록 — 카드 「⋯」 메뉴와 두 묶음(#1444)', () => {
  it('초대받은 지도가 없어도 두 묶음으로 나누고, 방장 카드 메뉴는 수정과 빨간 삭제다', async () => {
    setup()
    const menu = await screen.findByRole('button', { name: '제주도 여행 메뉴' })
    expect(screen.getByRole('heading', { name: /내가 만든 지도/ })).toBeInTheDocument()
    expect(screen.getByRole('heading', { name: /초대받은 지도/ })).toBeInTheDocument()

    await userEvent.click(menu)
    const items = within(screen.getByRole('menu')).getAllByRole('menuitem')
    expect(items.map((i) => i.textContent)).toEqual(['이름·날짜 수정', '대표 이미지 편집', '색상 변경', '지도 삭제'])
    expect(screen.queryByRole('menuitem', { name: '지도 나가기' })).not.toBeInTheDocument()

    await userEvent.click(items[3])
    expect(await screen.findByRole('alertdialog', { name: '지도를 삭제할까요?' })).toBeInTheDocument()
  })
  it('카드 메뉴에서 이름을 고치면 목록 카드도 바로 바뀐다', async () => {
    setup()
    await userEvent.click(await screen.findByRole('button', { name: '제주도 여행 메뉴' }))
    await userEvent.click(screen.getByRole('menuitem', { name: '이름·날짜 수정' }))
    const title = await screen.findByRole('textbox', { name: /제목|이름/ })
    await userEvent.clear(title)
    await userEvent.type(title, '부산 먹방')
    await userEvent.click(screen.getByRole('button', { name: '저장' }))
    expect(await screen.findByRole('button', { name: '부산 먹방 메뉴' })).toBeInTheDocument()
  })
  it('색상 변경에서 견본을 누르면 바로 저장되고 카드 바탕이 그 색이 된다', async () => {
    setup()
    await userEvent.click(await screen.findByRole('button', { name: '제주도 여행 메뉴' }))
    await userEvent.click(screen.getByRole('menuitem', { name: '색상 변경' }))
    await userEvent.click(await screen.findByRole('radio', { name: '민트' }))
    expect(await screen.findByRole('radio', { name: '민트', checked: true })).toBeInTheDocument()
    await userEvent.click(screen.getByRole('button', { name: '닫기' }))
    const card = (await screen.findByRole('button', { name: '제주도 여행 메뉴' })).closest('li')!.querySelector('a')!
    await vi.waitFor(() => expect(card.style.background).not.toBe(''))
  })
})
