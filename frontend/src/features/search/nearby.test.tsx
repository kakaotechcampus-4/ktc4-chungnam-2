import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { act, render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { server, resetScenario } from '@pingo/contracts/mocks/node'
import { MemoryRouter } from 'react-router'
import { afterAll, afterEach, beforeAll, describe, expect, it, vi } from 'vitest'

import { fromKakao, pickNearby } from './kakaoNearby'
import type { PlaceSearchResultDto } from './model'
import { SearchResultsBody } from './SearchResults'
import { useSearchStore } from './searchStore'

const kakao = (id: string, name: string, code: string, y = '37.5', x = '127.0') =>
  ({ id, place_name: name, category_group_code: code, x, y, place_url: '', address_name: '서울 어딘가', road_address_name: '' }) as kakao.maps.services.PlaceResult

describe('카카오 근처 장소(#1549)', () => {
  it('음식점·카페·관광지만 실시간 핀 후보로 바꾸고, 장소 ID는 kakao:<id> 다', () => {
    expect(fromKakao(kakao('1', '국숫집', 'FD6'))).toMatchObject({ place_id: 'kakao:1', category: '음식점', pinnable: false, lat: 37.5, lng: 127 })
    expect(fromKakao(kakao('2', '편의점', 'CS2'))).toBeNull()
  })

  it('가까운 순, 같은 가게는 한 번, 자체 DB 결과와 이름이 같고 가까우면 뺀다', () => {
    const at = { lat: 37.5, lng: 127.0 }
    const near = fromKakao(kakao('1', '가까운집', 'FD6', '37.5001'))!
    const far = fromKakao(kakao('2', '먼집', 'CE7', '37.5008'))!
    const own = fromKakao(kakao('3', '우리집', 'FD6', '37.5002'))!
    const ownDb: PlaceSearchResultDto = { place_id: 'own:x', place_name: '우리집', lat: 37.5002, lng: 127.0 }
    expect(pickNearby([far, near, near, own], at, [ownDb]).map((r) => r.place_name)).toEqual(['가까운집', '먼집'])
  })
})

const NEARBY = [fromKakao(kakao('9', '골목국수', 'FD6', '37.5', '127.0'))!]
vi.mock('./kakaoNearby', async (importOriginal) => ({
  ...(await importOriginal<typeof import('./kakaoNearby')>()),
  nearbyKakaoPlaces: vi.fn(async () => NEARBY),
}))

describe('신규 핀 찍기 목록(#1549)', () => {
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

  it('자체 DB 장소가 없어도 카카오 근처 장소를 따로 보이고, 고르면 실시간 핀 남기기로 간다', async () => {
    act(() => useSearchStore.getState().openTap({ lat: 37.5, lng: 127.0 }))
    render(
      <QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}>
        <MemoryRouter>
          <SearchResultsBody mapId="map_1" pins={[]} />
        </MemoryRouter>
      </QueryClientProvider>,
    )
    expect(await screen.findByRole('heading', { name: '카카오에서 찾은 근처 장소' })).toBeInTheDocument()
    await userEvent.click(screen.getByRole('button', { name: '핀 남기기' }))
    expect(await screen.findByRole('heading', { name: '골목국수' })).toBeInTheDocument()
    expect(screen.getByRole('button', { name: '누른 곳 근처 장소' })).toBeInTheDocument()
  })
})
