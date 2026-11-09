import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { act, render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { server, resetScenario } from '@pingo/contracts/mocks/node'
import { http, HttpResponse } from 'msw'
import { useState, type ReactNode } from 'react'
import { MemoryRouter, Outlet, Route, Routes } from 'react-router'
import { afterAll, afterEach, beforeAll, describe, expect, it, vi } from 'vitest'

import { START_PARAM } from '@/features/agent/actions'

import { useSheetStore } from '@/features/shell/sheetStore'
import { useToastStore } from '@/features/shell/toast'

import { useAiStore } from './aiStore'
import { createRun, fetchResult, retryRun } from './api'
import { recommendKeys } from './queries'
import ConditionsCard from './ConditionsCard'
import type { RecommendResultDto, RecommendRunDto } from './model'
import { ReadinessBody } from './Readiness'
import { ResultsHeader } from './Results'
import { wholeText } from '@/test/text'

const MAP = 'map_1'

beforeAll(() => server.listen({ onUnhandledRequest: 'error' }))
afterEach(() => {
  server.resetHandlers()
  resetScenario('happy-path')
  useAiStore.setState({ runs: {}, radius: {} })
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

/** 크레딧을 쓰는 실행은 확인 창을 거친다(쓸 크레딧·남은 크레딧) — 그 창의 확인 버튼을 누른다. */
async function confirmCredit(ok = '추천받기') {
  await userEvent.click(within(await screen.findByRole('alertdialog')).getByRole('button', { name: ok }))
}

async function doneRun() {
  const run = await createRun(MAP, '음식점', crypto.randomUUID())
  return { run, result: await fetchResult(run.id) }
}

describe('결과 먼저 — 「추천받기」 한 번에 결과까지(#849)', () => {
  it('근거 확인 없이 execute 로 시작하고, 시도마다 Idempotency-Key 와 보고 있는 지도 가운데를 싣는다(#1331)', async () => {
    const center = { lat: 37.5665, lng: 126.978 }
    const sent: { body: unknown; key: string | null }[] = []
    const readinessQuery: string[] = []
    server.events.on('request:start', async ({ request }) => {
      const url = new URL(request.url)
      if (request.method === 'POST' && url.pathname === `/maps/${MAP}/runs`) {
        sent.push({ body: await request.clone().json(), key: request.headers.get('Idempotency-Key') })
      }
      if (url.pathname === `/maps/${MAP}/recommend/readiness`) readinessQuery.push(url.search)
    })
    // 지도 셸(MapLayout)이 Outlet 으로 getCenter 를 내린다.
    renderWithClient(
      <Routes>
        <Route element={<Outlet context={{ getCenter: () => center }} />}>
          <Route path="*" element={<ReadinessBody mapId={MAP} />} />
        </Route>
      </Routes>,
    )
    await userEvent.click(await screen.findByRole('button', { name: '음식점 추천받기' }))
    await confirmCredit()

    await waitFor(() => expect(useAiStore.getState().runs[MAP]?.status).toBe('done'))
    expect(readinessQuery[0]).toBe(`?center_lat=${center.lat}&center_lng=${center.lng}`)
    expect(sent).toHaveLength(1)
    expect(sent[0].body).toEqual({ category: '음식점', execute: true, center })
    expect(sent[0].key).toMatch(/^[0-9a-f-]{36}$/)
    server.events.removeAllListeners()
  })

  it('지도를 끌어 옮기고 멈추면 「근처 정예 수」를 새 가운데로 다시 센다(#1331)', async () => {
    let center = { lat: 37.5665, lng: 126.978 }
    const queries: string[] = []
    server.events.on('request:start', ({ request }) => {
      const url = new URL(request.url)
      if (url.pathname === `/maps/${MAP}/recommend/readiness`) queries.push(url.search)
    })
    renderWithClient(
      <Routes>
        <Route element={<Outlet context={{ getCenter: () => center }} />}>
          <Route path="*" element={<ReadinessBody mapId={MAP} />} />
        </Route>
      </Routes>,
    )
    await screen.findByRole('button', { name: '음식점 추천받기' })

    center = { lat: 35.1, lng: 129.04 }
    act(() => useSheetStore.getState().setMapMoving(true)) // 끌기 시작과 멈춤은 따로 오는 이벤트다
    act(() => useSheetStore.getState().setMapMoving(false))
    await waitFor(() => expect(queries.at(-1)).toBe('?center_lat=35.1&center_lng=129.04'))
    server.events.removeAllListeners()
  })

  it('조건 카드: 접힌 줄에 쓴 조건 수, 펼쳐서 × 하면 「고친 조건 1개」와 「뺀 조건」(다시 넣기)', async () => {
    const { run, result } = await doneRun()
    renderWithClient(<Card run={run} result={result} />)

    const toggle = screen.getByRole('button', { name: /조건 .*찾았어요/ })
    expect(toggle).toHaveTextContent(/조건 \d+개/)
    await userEvent.click(toggle)

    // 칩마다 쓴 사람 이름이 글자로 보이고, 내 줄은 「(나)」다(#1561 — 툴팁은 휴대폰에서 안 보인다).
    const mine = (await screen.findByRole('button', { name: '매운맛 전문 빼기' })).closest('li')!
    expect(mine).toHaveTextContent('황경(나)매운맛 전문')
    expect(mine).not.toHaveAttribute('title')

    // 목 서버의 내 줄은 「매운맛 전문」(꼭 지켜야 하는 조건) — 빼기 전에 한 번 묻는다.
    await userEvent.click(await screen.findByRole('button', { name: '매운맛 전문 빼기' }))
    await userEvent.click(within(await screen.findByRole('alertdialog')).getByRole('button', { name: '빼기' }))

    expect(await screen.findByText('고친 조건 1개는 다시 추천할 때 반영돼요')).toBeInTheDocument()
    const removed = screen.getByRole('heading', { name: '뺀 조건' }).parentElement!
    expect(within(removed).getByRole('button', { name: '매운맛 전문 다시 넣기' })).toBeInTheDocument()
  })

  it('버튼 아래에 가격과 남은 크레딧 N/상한을 응답 값으로 보이고, 추천을 받으면 다시 받는다', async () => {
    const credits = () => fetch(`http://localhost/credits/me`).then((r) => r.json())
    const before = await credits()
    renderWithClient(<ReadinessBody mapId={MAP} />)
    expect(await screen.findByText(`${before.prices.recommend_run} 크레딧 사용`)).toBeInTheDocument()
    expect(screen.getByText(`남은 크레딧 ${before.balance}/${before.max_balance}`)).toBeInTheDocument()

    await userEvent.click(screen.getByRole('button', { name: '음식점 추천받기' }))

    await confirmCredit()
    const left = before.balance - before.prices.recommend_run
    expect(await screen.findByText(`${before.prices.recommend_run} 크레딧 사용`)).toBeInTheDocument()
    expect(screen.getByText(`남은 크레딧 ${left}/${before.max_balance}`)).toBeInTheDocument()
  })

  it('402 는 크레딧 부족 안내와 「후기 쓰러 가기」(확정 탭) — run 은 생기지 않는다', async () => {
    resetScenario('credits-empty')
    const { review_reward } = await fetch(`http://localhost/credits/me`).then((r) => r.json())
    renderWithClient(<ReadinessBody mapId={MAP} />)
    await userEvent.click(await screen.findByRole('button', { name: '음식점 추천받기' }))
    await confirmCredit()

    expect(await screen.findByText(wholeText(`크레딧이 부족해요. 후기를 쓰면 ${review_reward} 크레딧을 드려요`))).toBeInTheDocument()
    expect(screen.getByRole('link', { name: '후기 쓰러 가기' })).toHaveAttribute('href', `/maps/${MAP}/shortlist`)
    expect(screen.queryByText('추천 장소를 찾지 못했어요')).not.toBeInTheDocument()
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

    await userEvent.click(screen.getByRole('button', { name: /조건 .*찾았어요/ }))
    expect(await screen.findByRole('button', { name: '매운맛 전문 빼기' })).toBeInTheDocument()
    expect(screen.getByRole('button', { name: '조건 더하기' })).toBeInTheDocument()
  })
})

describe('크레딧을 쓰기 전에 묻기, 다시 추천 버튼(#1363)', () => {
  it('「추천받기」는 확인 창에 쓸 크레딧과 남은 크레딧을 보이고, 취소하면 요청하지 않는다', async () => {
    let runs = 0
    server.events.on('request:start', ({ request }) => {
      if (request.method === 'POST' && new URL(request.url).pathname === `/maps/${MAP}/runs`) runs += 1
    })
    const before = await fetch(`http://localhost/credits/me`).then((r) => r.json())
    renderWithClient(<ReadinessBody mapId={MAP} />)
    await userEvent.click(await screen.findByRole('button', { name: '음식점 추천받기' }))

    const dialog = within(await screen.findByRole('alertdialog', { name: '음식점 추천을 받을까요?' }))
    expect(dialog.getByText(`${before.prices.recommend_run} 크레딧을 써요`)).toBeInTheDocument()
    expect(dialog.getByText(`남은 크레딧 ${before.balance}/${before.max_balance}`)).toBeInTheDocument()
    await userEvent.click(dialog.getByRole('button', { name: '취소' }))

    expect(screen.queryByRole('alertdialog')).not.toBeInTheDocument()
    expect(runs).toBe(0)
    expect(useAiStore.getState().runs[MAP]).toBeUndefined()
    server.events.removeAllListeners()
  })

  it('핑고 조언에서 「추천 받아 보기」로 들어와도 바로 시작하지 않고 확인 창을 먼저 띄운다', async () => {
    const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
    render(
      <QueryClientProvider client={client}>
        <MemoryRouter initialEntries={[`/maps/${MAP}/recommend?${START_PARAM}=${encodeURIComponent('음식점')}`]}>
          <ReadinessBody mapId={MAP} />
        </MemoryRouter>
      </QueryClientProvider>,
    )
    expect(await screen.findByRole('alertdialog', { name: '음식점 추천을 받을까요?' })).toBeInTheDocument()
    expect(useAiStore.getState().runs[MAP]).toBeUndefined()
    await confirmCredit()
    await waitFor(() => expect(useAiStore.getState().runs[MAP]?.status).toBe('done'))
  })

  it('캐시에 남은 준비 상태가 예전 것이면 새로 받은 값으로 고른다 — 방금 의견을 남겨 준비된 카테고리에 "상황이 바뀌었어요"를 띄우지 않는다(#1583)', async () => {
    useToastStore.setState({ toast: null })
    const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
    const fresh = await fetch(`http://localhost/maps/${MAP}/recommend/readiness`).then((r) => r.json())
    expect(fresh['음식점'].ready).toBe(true)
    // 지도 탭에 있는 동안 받아 둔 값: 그때는 음식점 의견이 없었다.
    client.setQueryData(recommendKeys.readiness(MAP), { ...fresh, 음식점: { ...fresh['음식점'], ready: false } })
    render(
      <QueryClientProvider client={client}>
        <MemoryRouter initialEntries={[`/maps/${MAP}/recommend?${START_PARAM}=${encodeURIComponent('음식점')}`]}>
          <ReadinessBody mapId={MAP} />
        </MemoryRouter>
      </QueryClientProvider>,
    )
    expect(await screen.findByRole('alertdialog', { name: '음식점 추천을 받을까요?' })).toBeInTheDocument()
    expect(useToastStore.getState().toast).toBeNull()
  })

  it('다시 추천은 크레딧을 쓰지 않아 확인 창 없이 바로 가고, 버튼 옆에 남은 크레딧을 보인다', async () => {
    let retries = 0
    server.events.on('request:start', ({ request }) => {
      if (request.method === 'POST' && new URL(request.url).pathname.endsWith('/retry')) retries += 1
    })
    // 머리의 「‹ AI 추천」이 넓은 화면인지 본다 — jsdom 에는 matchMedia 가 없다.
    vi.stubGlobal('matchMedia', (query: string) => ({ matches: false, media: query, addEventListener() {}, removeEventListener() {}, addListener() {}, removeListener() {} }))
    const { run } = await doneRun()
    const credits = await fetch(`http://localhost/credits/me`).then((r) => r.json())
    renderWithClient(<ResultsHeader mapId={MAP} run={run} count={3} />)

    expect(await screen.findByText(`남은 크레딧 ${credits.balance}/${credits.max_balance}`)).toBeInTheDocument()
    await userEvent.click(screen.getByRole('button', { name: '다시 추천' }))
    expect(screen.queryByRole('alertdialog')).not.toBeInTheDocument()
    await waitFor(() => expect(retries).toBe(1))
    server.events.removeAllListeners()
    vi.unstubAllGlobals()
  })
})

describe('추천 범위 — 지도 가운데 반경 원, 여행 지역 밖 안내(#1385)', () => {
  const SEOUL = { label: '서울특별시', lat: 37.5665, lng: 126.978 }

  /** 지도 셸처럼 getCenter·showRegion 을 내리고, 경계를 받을 때까지 기다린다(누를 때 판정한다). */
  async function renderInShell(center: { lat: number; lng: number }, showRegion = vi.fn()) {
    const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
    render(
      <QueryClientProvider client={client}>
        <MemoryRouter>
          <Routes>
            <Route element={<Outlet context={{ getCenter: () => center, showRegion }} />}>
              <Route path="*" element={<ReadinessBody mapId={MAP} />} />
            </Route>
          </Routes>
        </MemoryRouter>
      </QueryClientProvider>,
    )
    await screen.findByRole('button', { name: '음식점 추천받기' })
    return { client, showRegion }
  }

  async function setRegion(region: typeof SEOUL) {
    await fetch(`http://localhost/maps/${MAP}`, { method: 'PATCH', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ region }) })
  }

  it('원 전체가 여행 지역 밖이면 크레딧 창 대신 안내하고, 「여행 지역으로 가기」는 지도만 옮긴다', async () => {
    await setRegion(SEOUL)
    const posts: string[] = []
    server.events.on('request:start', ({ request }) => {
      if (request.method === 'POST') posts.push(new URL(request.url).pathname)
    })
    const { client, showRegion } = await renderInShell({ lat: 35.1796, lng: 129.0756 })
    await waitFor(() => expect(client.getQueryData(['region-boundary', '11'])).toBeDefined())

    await userEvent.click(screen.getByRole('button', { name: '음식점 추천받기' }))
    const dialog = await screen.findByRole('alertdialog', { name: '여행 지역 밖이에요' })
    expect(within(dialog).getByText('서울특별시로 돌아가서 추천받아 주세요')).toBeInTheDocument()
    await userEvent.click(within(dialog).getByRole('button', { name: '여행 지역으로 가기' }))

    expect(showRegion).toHaveBeenCalledTimes(1)
    expect(screen.queryByRole('alertdialog')).not.toBeInTheDocument()
    expect(posts).toEqual([])
    server.events.removeAllListeners()
  })

  it('지역 안이면 크레딧 창에 찾는 범위를 알린다', async () => {
    await setRegion(SEOUL)
    const { client } = await renderInShell(SEOUL)
    await waitFor(() => expect(client.getQueryData(['region-boundary', '11'])).toBeDefined())

    await userEvent.click(screen.getByRole('button', { name: '음식점 추천받기' }))
    const dialog = await screen.findByRole('alertdialog', { name: '음식점 추천을 받을까요?' })
    expect(within(dialog).getByText('지도 가운데 반경 3km 안에서 찾아요')).toBeInTheDocument()
  })

  /** 준비 판정·추천 요청에 실린 반경을 모은다. */
  function watchRadius() {
    const readinessQuery: string[] = []
    const sent: unknown[] = []
    server.events.on('request:start', async ({ request }) => {
      const url = new URL(request.url)
      if (url.pathname === `/maps/${MAP}/recommend/readiness`) readinessQuery.push(url.search)
      if (request.method === 'POST' && url.pathname === `/maps/${MAP}/runs`) sent.push(await request.clone().json())
    })
    return { readinessQuery, sent }
  }

  it('「찾는 범위」 칸에 km를 넣으면 근처 정예 수를 그 반경으로 다시 세고, 확인 창과 추천 요청도 그 반경이다(#1416)', async () => {
    const { readinessQuery, sent } = watchRadius()
    await renderInShell(SEOUL)
    // 처음 값과 범위는 서버(목 서버 = docs/constraints.md 값)가 준다.
    const slider = screen.getByRole('slider', { name: '찾는 범위' })
    const min = Number(slider.getAttribute('aria-valuemin'))
    const max = Number(slider.getAttribute('aria-valuemax'))
    // 처음 값은 서버 기본 반경이고, 화면 읽기도 「기본」이라고 읽는다.
    expect(slider).toHaveAttribute('aria-valuetext', expect.stringMatching(/km, 기본$/))
    const m = Math.round((min + max) / 2 / 100) * 100 + 100 // 범위 가운데에서 한 칸, 100m 단위(눈금이 아닌 값)
    const km = `${m / 1000}km`

    // 값 글자를 누르면 km 칸이 열린다.
    await userEvent.click(screen.getByRole('button', { name: /찾는 범위 직접 넣기/ }))
    const input = screen.getByRole('spinbutton', { name: '찾는 범위' })
    await userEvent.clear(input)
    await userEvent.type(input, `${m / 1000}{Enter}`)
    expect(slider).toHaveAttribute('aria-valuetext', km)
    await waitFor(() => expect(readinessQuery.at(-1)).toContain(`&radius_m=${m}`))

    await userEvent.click(screen.getByRole('button', { name: '음식점 추천받기' }))
    const dialog = await screen.findByRole('alertdialog', { name: '음식점 추천을 받을까요?' })
    expect(within(dialog).getByText(`지도 가운데 반경 ${km} 안에서 찾아요`)).toBeInTheDocument()
    await confirmCredit()
    await waitFor(() => expect(sent).toHaveLength(1))
    expect(sent[0]).toMatchObject({ category: '음식점', radius_m: m })
    await waitFor(() => expect(useAiStore.getState().runs[MAP]?.default_radius_m).toBe(m))
    server.events.removeAllListeners()
  })

  it('키보드로는 0.1km씩 옮기고(눈금에 붙지 않는다), 손을 떼면 다시 센다. 범위 밖 km는 안내만 하고 바꾸지 않는다', async () => {
    const { readinessQuery } = watchRadius()
    await renderInShell(SEOUL)
    const slider = screen.getByRole('slider', { name: '찾는 범위' })
    const start = Number(slider.getAttribute('aria-valuenow'))
    slider.focus()
    await userEvent.keyboard('{ArrowRight}')
    expect(slider).toHaveAttribute('aria-valuenow', String(start + 100))
    await waitFor(() => expect(readinessQuery.at(-1)).toContain(`&radius_m=${start + 100}`))

    const max = Number(slider.getAttribute('aria-valuemax'))
    // 값 글자를 누르면 km 칸이 열린다.
    await userEvent.click(screen.getByRole('button', { name: /찾는 범위 직접 넣기/ }))
    const input = screen.getByRole('spinbutton', { name: '찾는 범위' })
    await userEvent.clear(input)
    await userEvent.type(input, `${max / 1000 + 1}{Enter}`)
    expect(screen.getByText(/사이로 넣어 주세요/)).toBeInTheDocument()
    expect(slider).toHaveAttribute('aria-valuenow', String(start + 100))
    server.events.removeAllListeners()
  })

  it('추천 요청이 실패하면 「추천 장소를 찾지 못했어요」 한 줄', async () => {
    // 지역을 고르지 않은 지도라 지역 밖 안내는 없다. 서버가 요청을 거절한다(422).
    server.use(
      http.post('*/maps/:mapId/runs', () =>
        HttpResponse.json({ code: 'VALIDATION_ERROR', message: '추천을 받을 수 없는 위치예요' }, { status: 422 }),
      ),
    )
    await renderInShell(SEOUL)
    await userEvent.click(screen.getByRole('button', { name: '음식점 추천받기' }))
    await confirmCredit()

    expect(await screen.findByText('추천 장소를 찾지 못했어요')).toBeInTheDocument()
    expect(useAiStore.getState().runs[MAP]).toBeUndefined()
  })
})
