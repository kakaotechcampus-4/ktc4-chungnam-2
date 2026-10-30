import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen, within } from '@testing-library/react'
import { server, resetScenario } from '@pingo/contracts/mocks/node'
import type { ReactNode } from 'react'
import { MemoryRouter } from 'react-router'
import { afterAll, afterEach, beforeAll, describe, expect, it } from 'vitest'

import { ApiError } from '@/api'

import { fetchResult } from './api'
import { noResultsExternalSearch, type RecommendRunDto } from './model'
import { ReadinessBody } from './Readiness'
import { NoResults, ResultsBody } from './Results'

const BASE = 'http://localhost'

beforeAll(() => server.listen({ onUnhandledRequest: 'error' }))
afterEach(() => {
  server.resetHandlers()
  resetScenario('happy-path')
})
afterAll(() => server.close())

function renderWithClient(ui: ReactNode) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return render(
    <QueryClientProvider client={client}>
      <MemoryRouter>{ui}</MemoryRouter>
    </QueryClientProvider>,
  )
}

const run = (id: string) => ({ id, category: '음식점', attempt_no: 1, status: 'done' }) as RecommendRunDto

async function noResultsError() {
  resetScenario('no-results')
  try {
    await fetchResult('run_no_results')
  } catch (err) {
    return err as ApiError
  }
  throw new Error('NO_RESULTS 가 오지 않았다')
}

/** 새 창으로 열고(앱 안 WebView 금지) 검색어를 함께 보여 준다. */
function expectExternalLink(query: string) {
  const link = screen.getByRole('link', { name: /카카오맵에서 더 찾아보기/ })
  expect(link).toHaveAttribute('href', expect.stringMatching(/^https:\/\/map\.kakao\.com\/link\/search\//))
  expect(link).toHaveAttribute('target', '_blank')
  expect(link).toHaveAttribute('rel', 'noopener noreferrer')
  expect(screen.getByText(`검색어 ‘${query}’`)).toBeInTheDocument()
}

describe('카카오맵에서 더 찾아보기(#798)', () => {
  it('추천 준비: 정예 장소가 없는 지역(춘천)이면 안내와 링크를 두고 추천 버튼은 막지 않는다', async () => {
    await fetch(`${BASE}/maps/map_1`, { method: 'PATCH', body: JSON.stringify({ region: { label: '춘천시', lat: 37.88, lng: 127.73 } }) })
    renderWithClient(<ReadinessBody mapId="map_1" />)

    expect(await screen.findByText('이 지역은 아직 핑고 추천 장소가 없어요')).toBeInTheDocument()
    expectExternalLink('춘천시 맛집')
    expect(screen.getByRole('button', { name: '음식점 추천받기' })).toBeEnabled()
  })

  it('추천 준비: 정예 장소가 있으면 링크가 없다', async () => {
    renderWithClient(<ReadinessBody mapId="map_1" />)
    expect(await screen.findByRole('button', { name: '음식점 추천받기' })).toBeEnabled()
    expect(screen.queryByRole('link', { name: /카카오맵에서 더 찾아보기/ })).not.toBeInTheDocument()
  })

  it('결과 0곳: 넓히기·근거 고치기와 같은 묶음에 링크', async () => {
    const error = await noResultsError()
    renderWithClient(<NoResults mapId="map_1" run={run('run_no_results')} error={error} onFixEvidence={() => {}} />)

    const group = screen.getByRole('button', { name: '근거 고치기' }).parentElement!
    expect(within(group).getByRole('button', { name: '반경 넓히기' })).toBeInTheDocument()
    expect(within(group).getByRole('link', { name: /카카오맵에서 더 찾아보기/ })).toBeInTheDocument()
    expectExternalLink(noResultsExternalSearch(error)!.query)
  })

  it('결과가 있으면 서버가 링크를 줄 때만 목록 아래에 두고, 카드는 place_url 로 카카오맵을 연다', async () => {
    resetScenario('retry-limit')
    const result = await fetchResult('run_retry_limit')
    const r = run('run_retry_limit')

    const view = renderWithClient(<ResultsBody mapId="map_1" run={r} result={result} members={[]} onHow={() => {}} />)
    expect(result.external_search).toBeUndefined() // 목 결과는 후보가 넉넉하다
    expect(screen.queryByRole('link', { name: /카카오맵에서 더 찾아보기/ })).not.toBeInTheDocument()
    const cardLinks = screen.getAllByRole('link', { name: '카카오맵에서 보기' })
    expect(cardLinks.map((a) => a.getAttribute('href'))).toEqual(result.candidates.map((c) => c.place_url))
    view.unmount()

    // 후보가 적은 결과 — 링크는 0곳 응답이 준 실제 목 링크를 싣는다.
    const search = noResultsExternalSearch(await noResultsError())!
    renderWithClient(<ResultsBody mapId="map_1" run={r} result={{ ...result, candidates: result.candidates.slice(0, 2), external_search: search }} members={[]} onHow={() => {}} />)
    expectExternalLink(search.query)
  })
})
