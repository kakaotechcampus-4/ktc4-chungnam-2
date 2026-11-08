import { useState } from 'react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { server, resetScenario } from '@pingo/contracts/mocks/node'
import { MemoryRouter } from 'react-router'
import { afterAll, afterEach, beforeAll, describe, expect, it, vi } from 'vitest'

import { ApiError } from '@/api'
import Toaster from '@/features/shell/Toaster'

import CreditGate from './CreditGate'
import { wholeText } from '@/test/text'

const BASE = 'http://localhost'

beforeAll(() => server.listen({ onUnhandledRequest: 'error' }))
afterEach(() => {
  vi.useRealTimers()
  server.resetHandlers()
  server.events.removeAllListeners()
  resetScenario('happy-path')
})
afterAll(() => server.close())

const credits = () => fetch(`${BASE}/credits/me`).then((r) => r.json())
const insufficient = () => new ApiError(402, { code: 'CREDIT_INSUFFICIENT', message: '크레딧이 부족해요', detail: { required: 1, balance: 0 } })

/** 실행 요청이 402 로 끝난 자리. onCharged 가 그 오류를 지운다(부르는 쪽의 create.reset 과 같다). */
function Harness() {
  const [error, setError] = useState<unknown>(insufficient)
  return (
    <CreditGate feature="recommend_run" mapId="map_1" error={error} onCharged={() => setError(null)}>
      <button type="button">추천받기</button>
    </CreditGate>
  )
}

function renderGate() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return render(
    <QueryClientProvider client={client}>
      <MemoryRouter>
        <Harness />
        <Toaster controlsVisible={false} />
      </MemoryRouter>
    </QueryClientProvider>,
  )
}

/** 목 서버가 돌려준 광고 세션(id·claim_after_s)과 받기 요청의 세션 id 를 모은다. 기다릴 초도 응답에서 읽는다. */
function watchAdSessions() {
  const opened: string[] = []
  const waits: number[] = []
  const claimed: string[] = []
  server.events.on('response:mocked', async ({ request, response }) => {
    const path = new URL(request.url).pathname
    if (path === '/credits/ad-sessions' && response.status === 201) {
      const body = await response.clone().json()
      opened.push(body.ad_session_id)
      waits.push(body.claim_after_s)
    }
    const m = path.match(/^\/credits\/ad-sessions\/([^/]+)\/claim$/)
    if (m) claimed.push(m[1])
  })
  return { opened, waits, claimed }
}

// 한 테스트가 버튼 → 광고 창(처음 쓸 때 불러옴) → 받기까지 여러 요청을 거친다. 전체 실행의 부하에서 기본 5초를 넘길 때가 있다.
describe('잔액 부족 안내의 광고 보고 충전(#1039)', { timeout: 20_000 }, () => {
  it('ad.available 이 false 면(기본 시드) 광고 버튼이 없다 — 후기 길만', async () => {
    const { ad } = await credits()
    expect(ad.available).toBe(false)
    renderGate()

    expect(await screen.findByRole('link', { name: '후기 쓰러 가기' })).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: /광고 보고/ })).not.toBeInTheDocument()
  })

  it('credits-empty: 버튼 → 테스트 광고 → 카운트다운 → 닫기 → 받기 → 토스트, 안내와 버튼이 사라진다', async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true })
    const user = userEvent.setup({ advanceTimers: (ms) => vi.advanceTimersByTime(ms) })
    resetScenario('credits-empty')
    const before = await credits()
    expect(before.ad.available).toBe(true)
    const seen = watchAdSessions()
    renderGate()

    // 고지 한 줄과 버튼 — 숫자는 응답 값
    const { reward, daily_max, used_today } = before.ad
    expect(await screen.findByText(wholeText(`광고를 끝까지 보면 ${reward} 크레딧을 드려요. 오늘 ${daily_max - used_today}번 남았어요`))).toBeInTheDocument()
    await user.click(screen.getByRole('button', { name: `광고 보고 ${reward} 크레딧 받기` }))

    // 테스트 광고 창: 다 보기 전에는 「보상 받고 닫기」가 없다
    const ad = await screen.findByRole('dialog', { name: '테스트 광고예요' })
    expect(ad).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: '보상 받고 닫기' })).not.toBeInTheDocument()
    expect(seen.waits[0]).toBeGreaterThan(0)

    await vi.advanceTimersByTimeAsync(seen.waits[0] * 1000)
    await user.click(await screen.findByRole('button', { name: '보상 받고 닫기' }))

    expect(await screen.findByText(`${reward} 크레딧을 받았어요`)).toBeInTheDocument()
    expect(screen.queryByRole('dialog', { name: '테스트 광고예요' })).not.toBeInTheDocument()
    await waitFor(() => expect(screen.queryByRole('link', { name: '후기 쓰러 가기' })).not.toBeInTheDocument())
    expect(screen.queryByRole('button', { name: /광고 보고/ })).not.toBeInTheDocument()

    const after = await credits()
    expect(after.balance).toBe(before.balance + reward)
    expect(seen.claimed).toEqual(seen.opened)
  })

  it('다 보기 전에 닫으면 안내 토스트, 다시 누르면 같은 세션으로 이어 받는다', async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true })
    const user = userEvent.setup({ advanceTimers: (ms) => vi.advanceTimersByTime(ms) })
    resetScenario('credits-empty')
    const { ad } = await credits()
    const seen = watchAdSessions()
    renderGate()

    const button = await screen.findByRole('button', { name: `광고 보고 ${ad.reward} 크레딧 받기` })
    await user.click(button)
    await user.click(await screen.findByRole('button', { name: '광고 닫기' }))

    expect(await screen.findByText('광고를 끝까지 봐야 크레딧을 받아요')).toBeInTheDocument()
    expect(seen.claimed).toEqual([]) // 다 보지 않았으면 받지 않는다

    // 광고를 다시 불러 둔 뒤 버튼이 다시 눌린다
    await user.click(await screen.findByRole('button', { name: `광고 보고 ${ad.reward} 크레딧 받기` }))
    await screen.findByRole('dialog', { name: '테스트 광고예요' })
    await vi.advanceTimersByTimeAsync(seen.waits[1] * 1000) // 이어 받은 세션은 남은 시간만 센다
    await user.click(await screen.findByRole('button', { name: '보상 받고 닫기' }))

    expect(await screen.findByText(`${ad.reward} 크레딧을 받았어요`)).toBeInTheDocument()
    expect(seen.opened).toHaveLength(2)
    expect(seen.opened[1]).toBe(seen.opened[0])
    expect(seen.claimed).toEqual([seen.opened[0]])
    // 이어 받은 세션은 하루 횟수를 쓰지 않는다
    expect((await credits()).ad.used_today).toBe(ad.used_today + 1)
  })
})
