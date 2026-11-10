import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter, Route, Routes } from 'react-router'
import { afterAll, afterEach, beforeAll, beforeEach, describe, expect, it, vi } from 'vitest'
import { resetScenario, server } from '@pingo/contracts/mocks/node'

import MapListPage from './MapListPage'

// 캔버스로 줄이는 일은 jsdom 에서 못 해서, 고른 파일을 그대로 돌려준다.
vi.mock('@/features/maps/look', async (orig) => ({ ...(await orig<object>()), shrinkImage: async (f: File) => f }))

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
    expect(items.map((i) => i.textContent)).toEqual(['이름·날짜 수정', '대표 이미지 편집', '색상 변경', '지도 복사', '지도 삭제'])
    expect(screen.queryByRole('menuitem', { name: '지도 나가기' })).not.toBeInTheDocument()

    await userEvent.click(items[4])
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
  it('색상 변경은 견본을 골라도 「닫기」면 버리고, 「저장」을 눌러야 카드 바탕이 그 색이 된다(#1643)', async () => {
    setup()
    const card = (await screen.findByRole('button', { name: '제주도 여행 메뉴' })).closest('li')!.querySelector('a')!
    const before = card.style.background
    await userEvent.click(screen.getByRole('button', { name: '제주도 여행 메뉴' }))
    await userEvent.click(screen.getByRole('menuitem', { name: '색상 변경' }))
    expect(await screen.findByRole('button', { name: '저장' })).toBeDisabled()
    await userEvent.click(screen.getByRole('radio', { name: '민트' }))
    await userEvent.click(screen.getByRole('button', { name: '닫기' }))
    expect(card.style.background).toBe(before)
    await userEvent.click(screen.getByRole('button', { name: '제주도 여행 메뉴' }))
    await userEvent.click(screen.getByRole('menuitem', { name: '색상 변경' }))
    await userEvent.click(await screen.findByRole('radio', { name: '민트' }))
    expect(screen.getByRole('radio', { name: '민트', checked: true })).toBeInTheDocument()
    await userEvent.click(screen.getByRole('button', { name: '저장' }))
    await vi.waitFor(() => expect(screen.queryByRole('button', { name: '저장' })).not.toBeInTheDocument())
    const saved = (await screen.findByRole('button', { name: '제주도 여행 메뉴' })).closest('li')!.querySelector('a')!
    await vi.waitFor(() => expect(saved.style.background).not.toBe(before))
  })
  it('대표 이미지는 사진을 골라도 바로 올리지 않고 「저장」을 눌러야 올린다(#1643)', async () => {
    vi.stubGlobal('URL', Object.assign(URL, { createObjectURL: () => 'blob:preview', revokeObjectURL: () => {} }))
    const puts: string[] = []
    server.events.on('request:start', ({ request }) => {
      if (request.method === 'PUT' && request.url.endsWith('/cover')) puts.push(request.url)
    })
    setup()
    await userEvent.click(await screen.findByRole('button', { name: '제주도 여행 메뉴' }))
    await userEvent.click(screen.getByRole('menuitem', { name: '대표 이미지 편집' }))
    const save = await screen.findByRole('button', { name: '저장' })
    expect(save).toBeDisabled()
    await userEvent.upload(screen.getByLabelText('사진 고르기'), new File([new Uint8Array([0xff, 0xd8, 0xff, 0xe0])], 'a.jpg', { type: 'image/jpeg' }))
    await vi.waitFor(() => expect(save).toBeEnabled())
    expect(puts).toHaveLength(0)
    await userEvent.click(save)
    await vi.waitFor(() => expect(puts).toHaveLength(1))
    await vi.waitFor(() => expect(screen.queryByRole('button', { name: '저장' })).not.toBeInTheDocument())
    server.events.removeAllListeners()
  })
  it('지도 복사를 확인하면 「제주도 여행 (1)」이 내가 만든 지도에 바로 생긴다', async () => {
    setup()
    await userEvent.click(await screen.findByRole('button', { name: '제주도 여행 메뉴' }))
    await userEvent.click(screen.getByRole('menuitem', { name: '지도 복사' }))
    await userEvent.click(await screen.findByRole('button', { name: '복사' }))
    expect(await screen.findByRole('button', { name: '제주도 여행 (1) 메뉴' })).toBeInTheDocument()
  })
  it('복사한 지도를 목록에서 삭제하면 확인 창이 닫히고 그 카드만 사라진다', async () => {
    setup()
    await userEvent.click(await screen.findByRole('button', { name: '제주도 여행 메뉴' }))
    await userEvent.click(screen.getByRole('menuitem', { name: '지도 복사' }))
    await userEvent.click(await screen.findByRole('button', { name: '복사' }))
    await userEvent.click(await screen.findByRole('button', { name: '제주도 여행 (1) 메뉴' }))
    await userEvent.click(screen.getByRole('menuitem', { name: '지도 삭제' }))
    await userEvent.click(await screen.findByRole('button', { name: '삭제' }))
    await vi.waitFor(() => expect(screen.queryByRole('alertdialog')).not.toBeInTheDocument())
    expect(screen.queryByRole('button', { name: '제주도 여행 (1) 메뉴' })).not.toBeInTheDocument()
    expect(screen.getByRole('button', { name: '제주도 여행 메뉴' })).toBeInTheDocument()
  })
})
