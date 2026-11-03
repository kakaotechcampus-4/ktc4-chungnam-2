import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { http, HttpResponse } from 'msw'
import { server, resetScenario } from '@pingo/contracts/mocks/node'
import { afterAll, afterEach, beforeAll, beforeEach, describe, expect, it, vi } from 'vitest'

import { useAiStore } from '@/features/recommend/aiStore'
import type { CandidateDto, RecommendRunDto } from '@/features/recommend/model'

import AdArea from './AdArea'
import { useRecommendAds } from './queries'

// 제주 시드 광고 근처(반경 밖 광고 하나는 빠진다).
vi.mock('@/features/shell/shellContext', () => ({ useShell: () => ({ getCenter: () => ({ lat: 33.5124, lng: 126.5226 }) }) }))

let gets = 0
let clicks: string[] = []

beforeAll(() => server.listen({ onUnhandledRequest: 'error' }))
beforeEach(() => {
  gets = 0
  clicks = []
  server.events.on('request:start', ({ request }) => {
    const url = new URL(request.url)
    if (request.method === 'GET' && url.pathname.endsWith('/ads')) gets += 1
    if (request.method === 'POST' && url.pathname.endsWith('/clicks')) clicks.push(url.pathname)
  })
  useAiStore.getState().setRun('map_1', { id: 'run_x', category: '카페', attempt_no: 1, status: 'done' } as RecommendRunDto)
})
afterEach(() => {
  server.resetHandlers()
  server.events.removeAllListeners()
  resetScenario('happy-path')
})
afterAll(() => server.close())

/** 추천 탭처럼 — 탭(바깥)이 조회를 붙잡고, 안의 화면이 바뀌면 광고 영역이 다시 그려진다. */
function Tab({ screenKey, hide }: { screenKey: string; hide?: CandidateDto[] }) {
  useRecommendAds('map_1')
  return <AdArea key={screenKey} mapId="map_1" hide={hide} />
}

function renderTab() {
  const client = new QueryClient()
  const view = render(
    <QueryClientProvider client={client}>
      <Tab screenKey="a" />
    </QueryClientProvider>,
  )
  const rerender = (screenKey: string, hide?: CandidateDto[]) =>
    view.rerender(
      <QueryClientProvider client={client}>
        <Tab screenKey={screenKey} hide={hide} />
      </QueryClientProvider>,
    )
  return { rerender }
}

describe('추천 탭 광고(#649)', () => {
  it('탭을 연 동안 한 번만 조회하고, 안의 화면이 바뀌어도 다시 부르지 않는다', async () => {
    const { rerender } = renderTab()
    expect(await screen.findByText('바다정원 카페')).toBeInTheDocument()
    expect(screen.getByText('돌담 로스터리')).toBeInTheDocument()
    expect(screen.queryByText('서귀포 끝 카페')).not.toBeInTheDocument()

    rerender('b')
    expect(await screen.findByText('바다정원 카페')).toBeInTheDocument()
    expect(gets).toBe(1)
  })

  it('카테고리가 바뀌면 다시 조회한다', async () => {
    const { rerender } = renderTab()
    await screen.findByText('바다정원 카페')
    useAiStore.getState().setRun('map_1', { id: 'run_y', category: '음식점', attempt_no: 1, status: 'done' } as RecommendRunDto)
    rerender('a')
    expect(await screen.findByText('한라 국수')).toBeInTheDocument()
    expect(gets).toBe(2)
  })

  it('클릭 기록은 광고 하나당 한 번이고, 카카오맵 링크는 새 창이다', async () => {
    const user = userEvent.setup()
    renderTab()
    const link = await screen.findByRole('link', { name: /카카오맵에서 보기/ })
    expect(link).toHaveAttribute('target', '_blank')
    link.addEventListener('click', (e) => e.preventDefault())
    await user.click(link)
    await user.click(link)
    await waitFor(() => expect(clicks).toEqual(['/ads/ad_1/clicks']))
    // place_url 이 없는 광고는 링크가 없다.
    expect(screen.getAllByRole('link', { name: /카카오맵에서 보기/ })).toHaveLength(1)
  })

  it('지도에 올리면 그 칸은 「이미 지도에 있어요」로 바뀐다(광고 id는 싣지 않는다)', async () => {
    let body: Record<string, unknown> = {}
    server.use(
      http.post('*/maps/:mapId/pins', async ({ request }) => {
        body = (await request.json()) as Record<string, unknown>
        return HttpResponse.json({ id: 'pin_ad', place_name: '바다정원 카페' }, { status: 201 })
      }),
    )
    const user = userEvent.setup()
    renderTab()
    const [first] = await screen.findAllByRole('button', { name: '지도에 올리기' })
    await user.click(first)
    expect(await screen.findByRole('button', { name: '이미 지도에 있어요' })).toBeDisabled()
    expect(body).toEqual({ source: 'search', place_id: 'place_ad_cafe_1', place_name: '바다정원 카페', lat: 33.5146, lng: 126.5236, category: '카페' })
    await waitFor(() => expect(clicks).toEqual(['/ads/ad_1/clicks']))
  })

  it('새 추천 결과에 같은 장소가 나오면 그 칸만 숨기고 다시 조회하지 않는다', async () => {
    const { rerender } = renderTab()
    await screen.findByText('바다정원 카페')
    rerender('b', [{ place_name: '바다정원 카페', lat: 33.5146, lng: 126.5236 } as CandidateDto])
    await waitFor(() => expect(screen.queryByText('바다정원 카페')).not.toBeInTheDocument())
    expect(screen.getByText('돌담 로스터리')).toBeInTheDocument()
    expect(gets).toBe(1)
  })
})
