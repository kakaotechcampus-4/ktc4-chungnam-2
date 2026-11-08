import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { act, render, screen } from '@testing-library/react'
import { http, HttpResponse } from 'msw'
import { server, resetScenario } from '@pingo/contracts/mocks/node'
import { MemoryRouter } from 'react-router'
import { afterAll, afterEach, beforeAll, describe, expect, it, vi } from 'vitest'

import { wholeText } from '@/test/text'

import { SearchResultsBody, SearchResultsHeader } from './SearchResults'
import { useSearchStore } from './searchStore'

beforeAll(() => {
  server.listen({ onUnhandledRequest: 'error' })
  vi.stubGlobal('matchMedia', (query: string) => ({ matches: false, media: query, addEventListener() {}, removeEventListener() {}, addListener() {}, removeListener() {} }))
})
afterEach(() => {
  server.resetHandlers()
  resetScenario('happy-path')
  act(() => useSearchStore.getState().close())
})
afterAll(() => {
  server.close()
  vi.unstubAllGlobals()
})

function tapAt(lat: number, lng: number) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  act(() => useSearchStore.getState().openTap({ lat, lng }))
  render(
    <QueryClientProvider client={client}>
      <MemoryRouter>
        <SearchResultsHeader count={null} />
        <SearchResultsBody mapId="map_1" pins={[]} />
      </MemoryRouter>
    </QueryClientProvider>,
  )
}

describe('지도를 눌러 핀 찍기 (#486)', () => {
  it('누른 곳 근처 자체 DB 장소를 결과 시트에 보인다', async () => {
    tapAt(35.1631, 129.1639)
    expect(screen.getByText('누른 곳 근처 장소')).toBeInTheDocument()
    expect(await screen.findByText('해운대 밀면')).toBeInTheDocument()
  })

  it('근처에 장소가 없으면 지어내지 않고 이름 검색을 권한다', async () => {
    tapAt(37.5, 127.0)
    expect(await screen.findByText(wholeText('누른 곳 가까이에 찍을 수 있는 장소가 없어요'))).toBeInTheDocument()
    expect(screen.getByRole('button', { name: '검색으로 남기기' })).toBeInTheDocument()
  })
})

/** 이름 검색이 0곳이 되게 한다. */
const noPlaces = () => server.use(http.get('*/places/search', () => HttpResponse.json([])))

function renderSearch(query: string) {
  act(() => useSearchStore.getState().submit(query, null))
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return render(
    <QueryClientProvider client={client}>
      <MemoryRouter>
        <SearchResultsBody mapId="map_1" pins={[]} />
      </MemoryRouter>
    </QueryClientProvider>,
  )
}

describe('장소 검색 결과 없음의 카카오맵 링크(#905)', () => {
  it('친 검색어 그대로 서버가 준 카카오맵 링크를 새 창으로 열고, 「검색어 지우고 다시 찾기」는 그대로 둔다', async () => {
    noPlaces()
    const asked: string[] = []
    server.events.on('request:start', ({ request }) => {
      const url = new URL(request.url)
      if (url.pathname.endsWith('/places/external-search')) asked.push(url.searchParams.get('q') ?? '')
    })
    renderSearch('성수 노포 곱창')

    const link = await screen.findByRole('link', { name: /카카오맵에서 더 찾아보기/ })
    expect(link).toHaveAttribute('href', `https://map.kakao.com/link/search/${encodeURIComponent('성수 노포 곱창')}`)
    expect(link).toHaveAttribute('target', '_blank')
    expect(asked).toEqual(['성수 노포 곱창'])
    expect(screen.getByText('찾는 장소가 없어요')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: '검색어 지우고 다시 찾기' })).toBeInTheDocument()
    server.events.removeAllListeners()
  })

  it('링크를 받지 못하면 링크만 숨기고 결과 없음 화면은 그대로다', async () => {
    noPlaces()
    server.use(http.get('*/places/external-search', () => HttpResponse.json({ code: 'INTERNAL' }, { status: 500 })))
    renderSearch('없는 가게')

    expect(await screen.findByText('찾는 장소가 없어요')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: '검색어 지우고 다시 찾기' })).toBeInTheDocument()
    // 실패 응답이 끝날 때까지 기다린 뒤에도 링크가 없다.
    await new Promise((r) => setTimeout(r, 50))
    expect(screen.queryByRole('link', { name: /카카오맵에서 더 찾아보기/ })).not.toBeInTheDocument()
  })

  it('결과가 있으면 링크를 부르지 않는다', async () => {
    const asked: string[] = []
    server.events.on('request:start', ({ request }) => {
      if (new URL(request.url).pathname.endsWith('/places/external-search')) asked.push(request.url)
    })
    renderSearch('곱창')
    expect(await screen.findByText(/곱창/, { selector: 'p, span, button' })).toBeInTheDocument()
    expect(screen.queryByText('찾는 장소가 없어요')).not.toBeInTheDocument()
    expect(asked).toEqual([])
    server.events.removeAllListeners()
  })
})
