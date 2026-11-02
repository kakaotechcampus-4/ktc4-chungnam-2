import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { server, resetScenario } from '@pingo/contracts/mocks/node'
import { MemoryRouter } from 'react-router'
import { afterAll, afterEach, beforeAll, describe, expect, it, vi } from 'vitest'

import { MOCK_SAMPLE } from './__fixtures__/kakaotalkExport'
import ImportSheet from './ImportSheet'
import { resetImport } from './queries'

const MAP = 'map_1'

beforeAll(() => {
  server.listen({ onUnhandledRequest: 'error' })
  // jsdom 에는 matchMedia 가 없다(넓은 화면 판정·동작 줄이기에 쓴다).
  vi.stubGlobal('matchMedia', (query: string) => ({ matches: false, media: query, addEventListener() {}, removeEventListener() {}, addListener() {}, removeListener() {} }))
})
afterEach(() => {
  server.resetHandlers()
  server.events.removeAllListeners()
  resetScenario('happy-path')
  resetImport()
})
afterAll(() => {
  server.close()
  vi.unstubAllGlobals()
})

/** 보낸 요청 본문을 모은다 — 대화 원문이 서버로 가지 않는지, 힌트·link_ref 가 맞게 실리는지 본다. */
function capture(path: string) {
  const bodies: Record<string, unknown>[] = []
  server.events.on('request:start', async ({ request }) => {
    if (request.method === 'POST' && new URL(request.url).pathname === path) bodies.push(await request.clone().json())
  })
  return bodies
}

async function paste() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  render(
    <QueryClientProvider client={client}>
      <MemoryRouter>
        <ImportSheet mapId={MAP} onClose={() => {}} onOpenOne={() => {}} onSearchName={() => {}} />
      </MemoryRouter>
    </QueryClientProvider>,
  )
  await userEvent.click(screen.getByRole('textbox', { name: '카톡 대화' }))
  await userEvent.paste(MOCK_SAMPLE)
  await userEvent.click(screen.getByRole('button', { name: '지도 링크 찾기' }))
  // 이름으로 찾기까지 끝나면 후보 라디오가 뜬다.
  await screen.findByRole('radiogroup', { name: '성수 노포 곱창 후보' })
}

describe('카톡 대화에서 핀 가져오기 — 네이버·공유 글 힌트·후보(#1046)', () => {
  it('링크와 상호명·주소 힌트만 같은 길이로 보낸다 — 대화 원문·보낸 사람은 보내지 않는다', async () => {
    const previews = capture(`/maps/${MAP}/pins/link-preview`)
    await paste()

    expect(previews).toHaveLength(1)
    const body = previews[0] as { urls: string[]; hints: unknown[] }
    expect(Object.keys(body).sort()).toEqual(['hints', 'urls'])
    expect(body.urls).toHaveLength(5)
    expect(body.hints).toHaveLength(5)
    expect(body.urls.filter((u) => u.includes('naver.me'))).toHaveLength(4)
    expect(body.hints[0]).toEqual({ name: '해운대 밀면', address: '부산 해운대구 우동' })
    expect(body.hints[2]).toBeNull() // 구글은 이름만이라 힌트를 보내지 않는다
    const sent = JSON.stringify(body)
    for (const secret of ['친구A', '친구B', '오전 1:0', '여기', '이거']) expect(sent).not.toContain(secret)
  })

  it('링크 주소 대신 이름이 보이고, 찾은 방법·주소 후보·이름 후보·같은 곳 묶음이 각각 보인다', async () => {
    await paste()

    // 서버가 상호명·주소로 찾은 곳은 미리 체크
    const hinted = screen.getByRole('checkbox', { name: /해운대 밀면.*이름·주소가 같아서 찾았어요/ })
    expect(hinted).toBeChecked()
    // 번호표로 찾은 다른 링크도 같은 장소 — 한 곳으로 센다
    expect(screen.getByText('위와 같은 곳')).toBeInTheDocument()
    // 이름이 다른 같은 주소 후보는 사람이 확인한다 — 미리 체크하지 않는다
    expect(screen.getByRole('checkbox', { name: /해운대 바다 카페/ })).not.toBeChecked()
    // 이름은 아는데 짝이 없는 곳은 이름으로 찾은 후보에서 고른다 — 고르지 않은 채
    const group = screen.getByRole('radiogroup', { name: '성수 노포 곱창 후보' })
    expect(within(group).getByRole('radio', { name: /여기 없어요/ })).toBeChecked()
    // 번호만 든 링크는 이름을 지어내지 않고 하나씩 찍기로
    expect(screen.getByRole('button', { name: '하나씩 찍기' })).toBeInTheDocument()
    expect(screen.queryByText('https://naver.me/hintA')).not.toBeInTheDocument()
    expect(screen.getByRole('button', { name: '고른 1곳 지도에 찍기' })).toBeEnabled()
  })

  it('고른 곳을 한 번에 찍는다 — 같은 곳은 한 번, 링크 번호는 link_ref, 자체 DB에 없는 곳은 실시간 핀', async () => {
    const bulks = capture(`/maps/${MAP}/pins/bulk`)
    await paste()

    await userEvent.click(screen.getByRole('checkbox', { name: /해운대 바다 카페/ }))
    const group = screen.getByRole('radiogroup', { name: '성수 노포 곱창 후보' })
    await userEvent.click(within(group).getByRole('radio', { name: /성수 노포 곱창/ }))
    await userEvent.click(screen.getByRole('button', { name: '고른 3곳 지도에 찍기' }))

    await waitFor(() => expect(bulks).toHaveLength(1))
    const pins = (bulks[0] as { pins: Record<string, unknown>[] }).pins
    expect(pins).toHaveLength(3)
    expect(pins[0]).toMatchObject({ source: 'search', place_name: '해운대 밀면', link_ref: { provider: 'naver', external_id: 'naver:hintA' } })
    expect(pins.find((p) => p.place_name === '해운대 바다 카페')).toMatchObject({ link_ref: { provider: 'naver', external_id: 'naver:addrB' } })
    expect(pins.find((p) => p.source === 'live')).toEqual({ source: 'live', category: '음식점', kakao_place_id: 'kakao:mock-6', search_query: '성수 노포 곱창' })
    expect(await screen.findByText(/찍었어요 3곳/)).toBeInTheDocument()
  })
})
