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
import { EVIDENCE_LOCKED } from './EvidenceGroups'
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

  it('추천 받기 전에도 이 지도에서 남은 횟수가 보이고, 다 쓰면 버튼이 막힌다', async () => {
    const view = renderWithClient(<ReadinessBody mapId={MAP} />)
    expect(await screen.findByText('이 지도에서 추천 10번 남았어요 (10번까지)')).toBeInTheDocument()
    view.unmount()

    const { run } = await doneRun()
    const again = renderWithClient(<ReadinessBody mapId={MAP} />)
    expect(await screen.findByText('이 지도에서 추천 9번 남았어요 (10번까지)')).toBeInTheDocument()
    again.unmount()

    for (let n = 1; n < 10; n++) await retryRun(run.id)
    renderWithClient(<ReadinessBody mapId={MAP} />)
    expect(await screen.findByText('이 지도에서 추천을 10번 모두 받았어요')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: '음식점 추천받기' })).toBeDisabled()
  })

  it('상한(10회)을 다 쓰면 카드는 읽기 전용이다 — × 와 조건 더하기가 없다', async () => {
    const { run } = await doneRun()
    let last = run
    for (let n = 1; n < 10; n++) last = await retryRun(run.id)
    expect(last.attempt_no).toBe(10)
    renderWithClient(<Card run={last} result={await fetchResult(run.id)} />)

    expect(screen.getByText(EVIDENCE_LOCKED)).toBeInTheDocument()
    await userEvent.click(screen.getByRole('button', { name: /이 조건으로 찾았어요/ }))
    expect(await screen.findByRole('heading', { name: '꼭 지킬 조건' })).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: /빼기$/ })).not.toBeInTheDocument()
    expect(screen.queryByRole('button', { name: '조건 더하기' })).not.toBeInTheDocument()
  })
})
