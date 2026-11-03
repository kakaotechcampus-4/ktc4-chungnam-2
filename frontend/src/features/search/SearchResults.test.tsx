import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { act, render, screen } from '@testing-library/react'
import { server, resetScenario } from '@pingo/contracts/mocks/node'
import { MemoryRouter } from 'react-router'
import { afterAll, afterEach, beforeAll, describe, expect, it } from 'vitest'

import { SearchResultsBody, SearchResultsHeader } from './SearchResults'
import { useSearchStore } from './searchStore'

beforeAll(() => server.listen({ onUnhandledRequest: 'error' }))
afterEach(() => {
  server.resetHandlers()
  resetScenario('happy-path')
  act(() => useSearchStore.getState().close())
})
afterAll(() => server.close())

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
    expect(await screen.findByText('누른 곳 가까이에 찍을 수 있는 장소가 없어요')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: '검색으로 남기기' })).toBeInTheDocument()
  })
})
