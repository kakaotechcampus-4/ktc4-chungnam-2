import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { server, resetScenario } from '@pingo/contracts/mocks/node'
import { useState, type ReactNode } from 'react'
import { MemoryRouter } from 'react-router'
import { afterAll, afterEach, beforeAll, describe, expect, it } from 'vitest'

import { useAiStore } from './aiStore'
import { createRun, fetchResult, retryRun } from './api'
import ConditionsCard from './ConditionsCard'
import type { RecommendResultDto, RecommendRunDto } from './model'
import { ReadinessBody } from './Readiness'

const MAP = 'map_1'

beforeAll(() => server.listen({ onUnhandledRequest: 'error' }))
afterEach(() => {
  server.resetHandlers()
  resetScenario('happy-path')
  useAiStore.setState({ runs: {} })
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

/** 펼침을 부르는 쪽이 갖는 것처럼 감싼다(RunResult). */
function Card({ run, result }: { run: RecommendRunDto; result: RecommendResultDto }) {
  const [open, setOpen] = useState(false)
  return <ConditionsCard run={run} applied={result.applied_evidence} noApplied={result.no_applied_conditions} open={open} onOpenChange={setOpen} />
}

async function doneRun() {
  const run = await createRun(MAP, '음식점', crypto.randomUUID())
  return { run, result: await fetchResult(run.id) }
}

describe('결과 먼저 — 「추천받기」 한 번에 결과까지(#849)', () => {
  it('근거 확인 없이 execute 로 시작하고, 시도마다 Idempotency-Key 를 싣는다', async () => {
    const sent: { body: unknown; key: string | null }[] = []
    server.events.on('request:start', async ({ request }) => {
      if (request.method === 'POST' && new URL(request.url).pathname === `/maps/${MAP}/runs`) {
        sent.push({ body: await request.clone().json(), key: request.headers.get('Idempotency-Key') })
      }
    })
    renderWithClient(<ReadinessBody mapId={MAP} />)
    await userEvent.click(await screen.findByRole('button', { name: '음식점 추천받기' }))

    await waitFor(() => expect(useAiStore.getState().runs[MAP]?.status).toBe('done'))
    expect(sent).toHaveLength(1)
    expect(sent[0].body).toEqual({ category: '음식점', execute: true })
    expect(sent[0].key).toMatch(/^[0-9a-f-]{36}$/)
    server.events.removeAllListeners()
  })

  it('조건 카드: 접힌 줄에 쓴 조건 수, 펼쳐서 × 하면 「고친 조건 1개」와 「뺀 조건」(다시 넣기)', async () => {
    const { run, result } = await doneRun()
    renderWithClient(<Card run={run} result={result} />)

    const toggle = screen.getByRole('button', { name: /이 조건으로 찾았어요/ })
    expect(toggle).toHaveTextContent(/조건 \d+개/)
    await userEvent.click(toggle)

    // 목 서버의 내 줄은 「매운맛 전문」(꼭 지켜야 하는 조건) — 빼기 전에 한 번 묻는다.
    await userEvent.click(await screen.findByRole('button', { name: '매운맛 전문 빼기' }))
    await userEvent.click(within(await screen.findByRole('alertdialog')).getByRole('button', { name: '빼기' }))

    expect(await screen.findByText('고친 조건 1개 · 다시 추천 때 반영')).toBeInTheDocument()
    const removed = screen.getByRole('heading', { name: '뺀 조건 · 다시 추천 때 반영' }).parentElement!
    expect(within(removed).getByRole('button', { name: '매운맛 전문 다시 넣기' })).toBeInTheDocument()
  })

  it('버튼 아래에 가격과 남은 크레딧을 응답 값으로 보이고, 추천을 받으면 다시 받는다', async () => {
    const credits = () => fetch(`http://localhost/credits/me`).then((r) => r.json())
    const before = await credits()
    renderWithClient(<ReadinessBody mapId={MAP} />)
    expect(await screen.findByText(`${before.prices.recommend_run} 크레딧 사용 · 남은 크레딧 ${before.balance}`)).toBeInTheDocument()

    await userEvent.click(screen.getByRole('button', { name: '음식점 추천받기' }))
    const left = before.balance - before.prices.recommend_run
    expect(await screen.findByText(`${before.prices.recommend_run} 크레딧 사용 · 남은 크레딧 ${left}`)).toBeInTheDocument()
  })

  it('402 는 크레딧 부족 안내와 「후기 쓰러 가기」(확정 탭) — run 은 생기지 않는다', async () => {
    resetScenario('credits-empty')
    const { review_reward } = await fetch(`http://localhost/credits/me`).then((r) => r.json())
    renderWithClient(<ReadinessBody mapId={MAP} />)
    await userEvent.click(await screen.findByRole('button', { name: '음식점 추천받기' }))

    expect(await screen.findByText(`크레딧이 부족해요. 후기를 쓰면 ${review_reward} 크레딧을 드려요`)).toBeInTheDocument()
    expect(screen.getByRole('link', { name: '후기 쓰러 가기' })).toHaveAttribute('href', `/maps/${MAP}/shortlist`)
    expect(screen.queryByText('추천을 시작하지 못했어요')).not.toBeInTheDocument()
    expect(useAiStore.getState().runs[MAP]).toBeUndefined()
  })

  it('게스트는 처음부터 버튼 대신 카카오 안내 — 숫자는 403 detail 에서', async () => {
    resetScenario('guest')
    const { detail } = await fetch(`http://localhost/credits/me`).then((r) => r.json())
    renderWithClient(<ReadinessBody mapId={MAP} />)

    expect(await screen.findByText(`카카오로 로그인하면 ${detail.initial_credits} 크레딧을 드려요`)).toBeInTheDocument()
    expect(screen.getByRole('link', { name: /카카오로 계정 만들기/ })).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: /추천받기$/ })).not.toBeInTheDocument()
  })

  it('다시 추천을 여러 번 해도 조건 카드는 고칠 수 있다 — 횟수 상한이 없다(#432 D5)', async () => {
    const { run } = await doneRun()
    let last = run
    for (let n = 0; n < 10; n++) last = await retryRun(run.id)
    renderWithClient(<Card run={last} result={await fetchResult(run.id)} />)

    await userEvent.click(screen.getByRole('button', { name: /이 조건으로 찾았어요/ }))
    expect(await screen.findByRole('button', { name: '매운맛 전문 빼기' })).toBeInTheDocument()
    expect(screen.getByRole('button', { name: '조건 더하기' })).toBeInTheDocument()
  })
})
