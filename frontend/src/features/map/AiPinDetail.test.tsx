import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen, within } from '@testing-library/react'
import { server, resetScenario } from '@pingo/contracts/mocks/node'
import type { ReactNode } from 'react'
import { MemoryRouter } from 'react-router'
import { afterAll, afterEach, beforeAll, describe, expect, it, vi } from 'vitest'

import { createRun, fetchResult, publishCandidate } from '@/features/recommend/api'

import type { Pin } from './model'
import { PinDetailBody, PinDetailHeader } from './PinDetail'

const MAP = 'map_1'

beforeAll(() => {
  server.listen({ onUnhandledRequest: 'error' })
  // jsdom 에는 matchMedia 가 없다(넓은 화면 판정·동작 줄이기에 쓴다).
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

function renderWithClient(ui: ReactNode) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return render(
    <QueryClientProvider client={client}>
      <MemoryRouter>{ui}</MemoryRouter>
    </QueryClientProvider>,
  )
}

/** 후보를 지도에 올린 핀. 서버는 올릴 때 근거 네 가지를 핀에 옮긴다(backend pins.api.create_ai_pin) — 목 서버는 checks 만 옮겨서 나머지는 서버처럼 채운다. */
async function publishedAiPin(): Promise<Pin> {
  const run = await createRun(MAP, '음식점', crypto.randomUUID())
  const c = (await fetchResult(run.id)).candidates[0]
  const pin = await publishCandidate(c.id)
  return { ...pin, reason: c.reason, member_fulfillment: c.member_fulfillment, place_source: c.place_source ?? { provider: 'kakao' } }
}

const members = [{ userId: 'u_me', name: '나', initial: '나', isMe: true, isOwner: true }]

describe('지도에 올린 AI 핀 상세(#1032, 가드레일 5)', () => {
  it('제목 옆 「AI」 배지와 추천 이유·조건 체크·구성원 충족·출처가 상세에 보인다', async () => {
    const pin = await publishedAiPin()
    renderWithClient(
      <>
        <PinDetailHeader pin={pin} mapId={MAP} onBack={() => {}} />
        <PinDetailBody pin={pin} mapId={MAP} members={members} onDone={() => {}} />
      </>,
    )

    expect(screen.getByText('AI', { selector: '.tag-ai' })).toBeInTheDocument()
    const evidence = screen.getByRole('region', { name: 'AI 추천 근거' })
    expect(within(evidence).getByText(pin.reason!)).toBeInTheDocument()
    expect(within(evidence).getByText(new RegExp(`${pin.checks![0].label}`))).toBeInTheDocument()
    expect(within(evidence).getByText(/명 조건 충족/)).toBeInTheDocument()
    expect(within(evidence).getByText(/출처/)).toBeInTheDocument()
  })

  it('근거가 없는 사람의 핀에는 「AI」 배지와 근거 구역이 없다', async () => {
    const pin = await publishedAiPin()
    const plain: Pin = { ...pin, kind: '일반', reason: undefined, checks: undefined, member_fulfillment: undefined, place_source: undefined }
    renderWithClient(
      <>
        <PinDetailHeader pin={plain} mapId={MAP} onBack={() => {}} />
        <PinDetailBody pin={plain} mapId={MAP} members={members} onDone={() => {}} />
      </>,
    )
    expect(screen.queryByText('AI', { selector: '.tag-ai' })).not.toBeInTheDocument()
    expect(screen.queryByRole('region', { name: 'AI 추천 근거' })).not.toBeInTheDocument()
  })
})
