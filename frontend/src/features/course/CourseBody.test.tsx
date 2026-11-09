import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { http, HttpResponse } from 'msw'
import { server, resetScenario } from '@pingo/contracts/mocks/node'
import { MemoryRouter } from 'react-router'
import { afterAll, afterEach, beforeAll, beforeEach, describe, expect, it, vi } from 'vitest'

import { fetchSchedule } from '@/features/shortlist/api'
import { saveSchedule, scheduleKeys } from '@/features/shortlist/scheduleQueries'

import CourseBody from './CourseBody'
import { useCourseViewStore } from './courseMapStore'
import { wholeText } from '@/test/text'

const BASE = 'http://localhost'

beforeAll(() => server.listen({ onUnhandledRequest: 'error' }))
afterEach(() => {
  vi.useRealTimers()
  server.resetHandlers()
  server.events.removeAllListeners()
  resetScenario('happy-path')
  useCourseViewStore.setState({ runs: {}, failed: {} })
})
afterAll(() => server.close())

// 목 서버의 확정 리스트에 핀 둘을 넣는다(실서버의 「확정 리스트에 넣기」와 같은 경로).
beforeEach(async () => {
  for (const pin_id of ['pin_1', 'pin_2']) {
    await fetch(`${BASE}/maps/map_1/shortlist`, { method: 'POST', body: JSON.stringify({ pin_id }) })
  }
})

function renderSheet() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return render(
    <QueryClientProvider client={client}>
      <MemoryRouter>
        <CourseBody mapId="map_1" />
      </MemoryRouter>
    </QueryClientProvider>,
  )
}

/** 크레딧을 쓰는 실행은 확인 창을 거친다 — 그 창의 「코스 짜기」를 누른다. */
async function confirmCourse(user: ReturnType<typeof userEvent.setup> | typeof userEvent = userEvent) {
  await user.click(within(await screen.findByRole('alertdialog', { name: '코스를 짤까요?' })).getByRole('button', { name: '코스 짜기' }))
}

const error = (status: number, code: string, detail?: Record<string, unknown>) =>
  HttpResponse.json({ code, message: code, ...(detail ? { detail } : {}) }, { status })

describe('AI 코스 짜기 시트', () => {
  it('진입 → 진행(작업 기록이 늘어남) → 결과, 끝나면 조회를 멈춘다', async () => {
    // 실제 시간을 기다리지 않는다 — 시간은 우리가 앞으로 돌린다(shouldAdvanceTime 은 msw 의 비동기가 멈추지 않게).
    vi.useFakeTimers({ shouldAdvanceTime: true })
    const user = userEvent.setup({ advanceTimers: (ms) => vi.advanceTimersByTime(ms) })
    let polls = 0
    server.events.on('request:start', ({ request }) => {
      if (new URL(request.url).pathname.startsWith('/course-runs/')) polls++
    })
    renderSheet()

    expect(await screen.findByText(/10\.\d+ \(.\) ~ /)).toBeInTheDocument() // 지도 여행 날짜
    await user.type(screen.getByLabelText(/요청 사항/), '덜 걷게 해 주세요')
    await user.click(screen.getByRole('button', { name: '코스 짜기' }))
    await confirmCourse(user)

    // 진행: 첫 조회는 단계 2개 — 첫 줄 「이해」는 카드
    const log = await screen.findByRole('list', { name: '작업 기록' })
    expect(within(log).getAllByRole('listitem')).toHaveLength(2)
    expect(within(log).getByRole('heading', { name: /이렇게 이해했어요/ })).toBeInTheDocument()
    expect(within(log).getByText('코드')).toBeInTheDocument() // 누가 칩

    // 두 번째 조회에서 5개로 늘어난다(앞 줄은 그대로, 뒤에만 붙음)
    await vi.advanceTimersByTimeAsync(2000)
    await waitFor(() => expect(within(screen.getByRole('list', { name: '작업 기록' })).getAllByRole('listitem')).toHaveLength(5))

    // 결과
    await vi.advanceTimersByTimeAsync(2000)
    expect(await screen.findByText('요청 사항')).toBeInTheDocument()
    expect(screen.getByText('하루 걷는 시간 줄이기')).toBeInTheDocument()
    expect(screen.getByText('지킴')).toBeInTheDocument()
    expect(screen.getByRole('heading', { name: /첫째 날 · / })).toBeInTheDocument()
    // 영업시간을 모르는 장소(needs_check)에는 표시하지 않고, 아는 장소에만 「영업시간 확인됨」(2026-11-02)
    expect(screen.queryByText(wholeText('? 영업 확인 필요'))).not.toBeInTheDocument()
    expect(screen.queryByText('영업시간 확인됨')).not.toBeInTheDocument() // 목 서버는 모든 장소가 영업 여부를 모른다
    expect(screen.getByText(/^영업시간 정보가 없는 \d+곳은 방문 전에 확인해 주세요\.$/)).toBeInTheDocument()
    expect(screen.queryByText('다시 짜기')).not.toBeInTheDocument() // stale 아님
    expect(screen.queryAllByRole('link', { name: /길찾기/, hidden: true }).every((a) => a.getAttribute('href')?.startsWith('https://map.kakao.com/link/by/') && a.getAttribute('target') === '_blank')).toBe(true)
    // 장소 이름은 이미 받은 확정 리스트에서 찾는다
    expect(screen.queryByText('이 장소')).not.toBeInTheDocument()

    // 작업 기록을 다시 볼 수 있다
    await user.click(screen.getByRole('button', { name: '작업 기록 보기' }))
    expect(screen.getByRole('list', { name: '작업 기록' })).toBeInTheDocument()

    // done 이후엔 더 부르지 않는다
    const seen = polls
    await vi.advanceTimersByTimeAsync(6000)
    expect(polls).toBe(seen)
  })

  it('진행 중에 조회가 실패하면 진행 화면 밑에 「다시 불러오기」가 뜨고, 누르면 다시 이어진다', async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true })
    const user = userEvent.setup({ advanceTimers: (ms) => vi.advanceTimersByTime(ms) })
    let calls = 0
    const running = {
      id: 'run_p', map_id: 'map_1', status: 'running', outcome: null, failure_code: null, goals: [], unmatched: [], steps: [], days: [],
      violations: [], checks: [], excluded: [], snapshot_at: '2026-10-21T00:00:00Z', stale: false, created_at: '2026-10-21T00:00:00Z', finished_at: null,
    }
    server.use(
      http.post('*/maps/:mapId/courses', () => HttpResponse.json({ course_run_id: 'run_p' }, { status: 202 })),
      http.get('*/course-runs/run_p', () => {
        calls++
        if (calls === 1) return HttpResponse.json(running)
        if (calls <= 4) return error(500, 'INTERNAL') // 폴링 한 번 + 재시도 2번이 모두 실패
        return HttpResponse.json({ ...running, status: 'done', outcome: 'solved', finished_at: '2026-10-21T00:00:10Z' })
      }),
    )
    renderSheet()
    await user.click(await screen.findByRole('button', { name: '코스 짜기' }))
    await confirmCourse(user)
    expect(await screen.findByText('코스를 짜고 있어요')).toBeInTheDocument()

    await vi.advanceTimersByTimeAsync(2000 + 1000 + 2000) // 두 번째 조회와 재시도 둘이 실패
    const retry = await screen.findByRole('button', { name: '다시 불러오기' }, { timeout: 3000 })
    expect(screen.getByText('코스를 짜고 있어요')).toBeInTheDocument() // 진행 화면은 그대로
    const before = calls
    await vi.advanceTimersByTimeAsync(6000)
    expect(calls).toBe(before) // 폴링은 멈춰 있다

    await user.click(retry)
    expect(await screen.findByText('코스를 짰어요')).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: '다시 불러오기' })).not.toBeInTheDocument()
  })

  it('버튼 아래에 가격과 남은 크레딧 N/상한을 응답 값으로 보이고, 코스를 짜면 다시 받는다', async () => {
    const credits = () => fetch(`${BASE}/credits/me`).then((r) => r.json())
    const before = await credits()
    const user = userEvent.setup({ delay: null })
    renderSheet()
    expect(await screen.findByText(`${before.prices.course} 크레딧 사용`)).toBeInTheDocument()
    expect(screen.getByText(`남은 크레딧 ${before.balance}/${before.max_balance}`)).toBeInTheDocument()

    await user.click(screen.getByRole('button', { name: '코스 짜기' }))

    await confirmCourse(user)
    await screen.findByRole('list', { name: '작업 기록' })
    const after = await credits()
    expect(after.balance).toBe(before.balance - before.prices.course)
  })

  it('402 는 크레딧 부족 안내와 「후기 쓰러 가기」(확정 탭으로 간다)', async () => {
    resetScenario('credits-empty')
    for (const pin_id of ['pin_1', 'pin_2']) {
      await fetch(`${BASE}/maps/map_1/shortlist`, { method: 'POST', body: JSON.stringify({ pin_id }) })
    }
    const { review_reward } = await fetch(`${BASE}/credits/me`).then((r) => r.json())
    const user = userEvent.setup({ delay: null })
    renderSheet()
    await user.click(await screen.findByRole('button', { name: '코스 짜기' }))
    await confirmCourse(user)

    expect(await screen.findByText(wholeText(`크레딧이 부족해요. 후기를 쓰면 ${review_reward} 크레딧을 드려요`))).toBeInTheDocument()
    expect(screen.queryByText(/코스를 요청하지 못했어요/)).not.toBeInTheDocument()
    const link = screen.getByRole('link', { name: '후기 쓰러 가기' })
    expect(link).toHaveAttribute('href', '/maps/map_1/shortlist')
  })

  it('게스트는 처음부터 버튼 대신 카카오 안내 — 숫자는 403 detail 에서', async () => {
    resetScenario('guest')
    for (const pin_id of ['pin_1', 'pin_2']) {
      await fetch(`${BASE}/maps/map_1/shortlist`, { method: 'POST', body: JSON.stringify({ pin_id }) })
    }
    const { detail } = await fetch(`${BASE}/credits/me`).then((r) => r.json())
    renderSheet()

    expect(await screen.findByText(`카카오로 로그인하면 ${detail.initial_credits} 크레딧을 드려요`)).toBeInTheDocument()
    expect(screen.getByRole('link', { name: /카카오로 계정 만들기/ })).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: '코스 짜기' })).not.toBeInTheDocument()

    // 버튼이 없어도 요청 칸에서 Enter 를 누르면 제출된다 — 크레딧 확인 창을 띄우지 않는다.
    await userEvent.type(screen.getByLabelText(/요청 사항/), '덜 걷게{Enter}')
    expect(screen.queryByRole('alertdialog')).not.toBeInTheDocument()
  })

  it('422 는 장소 부족 안내', async () => {
    server.use(http.post('*/maps/:mapId/courses', () => error(422, 'COURSE_NOT_ENOUGH_PLACES', { min: 2, count: 1 })))
    const user = userEvent.setup({ delay: null })
    renderSheet()
    await user.click(await screen.findByRole('button', { name: '코스 짜기' }))
    await confirmCourse(user)
    expect(await screen.findByRole('alert')).toHaveTextContent('2곳 이상')
  })

  it('요청이 실패하면 당황한 핑고 화면 — 다른 탭에 다녀와도 남고, 「다시 시도」는 같은 글로 다시 보낸다', async () => {
    const sent: string[] = []
    let fail = true
    server.use(
      http.post('*/maps/:mapId/courses', async ({ request }) => {
        const body = (await request.json()) as { request_text?: string }
        sent.push(body.request_text ?? '')
        if (fail) return error(500, 'INTERNAL')
        return undefined // 목 서버 기본 처리로 넘긴다
      }),
    )
    const user = userEvent.setup({ delay: null })
    const view = renderSheet()
    await user.type(await screen.findByLabelText(/요청 사항/), '실내 위주로')
    await user.click(screen.getByRole('button', { name: '코스 짜기' }))
    await confirmCourse(user)
    expect(await screen.findByText('코스를 요청하지 못했어요')).toBeInTheDocument()

    // 탭을 떠났다 오면(화면이 새로 붙어도) 실패가 남는다.
    view.unmount()
    renderSheet()
    expect(await screen.findByText('코스를 요청하지 못했어요')).toBeInTheDocument()

    fail = false
    await user.click(screen.getByRole('button', { name: '다시 시도' }))
    await confirmCourse(user) // 다시 보내기도 크레딧을 쓰니 먼저 묻는다
    expect(await screen.findByRole('list', { name: '작업 기록' })).toBeInTheDocument()
    expect(sent).toEqual(['실내 위주로', '실내 위주로'])
  })

  it('「하루 걷기」를 고르면 모든 날의 도보 상한으로 보내고, 실패 뒤 「다시 시도」도 같은 상한이다(#1502)', async () => {
    const sent: unknown[] = []
    let fail = true
    server.use(
      http.post('*/maps/:mapId/courses', async ({ request }) => {
        sent.push(((await request.json()) as { member_constraints?: unknown }).member_constraints)
        if (fail) return error(500, 'INTERNAL')
        return undefined
      }),
    )
    const user = userEvent.setup({ delay: null })
    renderSheet()
    const group = await screen.findByRole('group', { name: /하루 걷기/ })
    expect(within(group).getByRole('button', { name: '상관없음' })).toHaveAttribute('aria-pressed', 'true')
    await user.click(within(group).getByRole('button', { name: '1시간 30분까지' }))
    await user.click(screen.getByRole('button', { name: '코스 짜기' }))
    await confirmCourse(user)
    expect(await screen.findByText('코스를 요청하지 못했어요')).toBeInTheDocument()

    fail = false
    await user.click(screen.getByRole('button', { name: '다시 시도' }))
    await confirmCourse(user)
    expect(await screen.findByRole('list', { name: '작업 기록' })).toBeInTheDocument()
    const walk = [{ kind: 'daily_walk_max', value: 90 }]
    expect(sent).toEqual([walk, walk])
  })

  it('「하루 걷기」를 안 고르면 상한을 보내지 않는다(서버 기본)', async () => {
    const sent: unknown[] = []
    server.use(
      http.post('*/maps/:mapId/courses', async ({ request }) => {
        sent.push(await request.json())
        return undefined
      }),
    )
    const user = userEvent.setup({ delay: null })
    renderSheet()
    await user.click(await screen.findByRole('button', { name: '코스 짜기' }))
    await confirmCourse(user)
    await waitFor(() => expect(sent).toHaveLength(1))
    expect(sent[0]).not.toHaveProperty('member_constraints')
  })

  it('실패 화면의 「요청 고치기」는 보냈던 글을 그대로 둔 입력 화면으로 돌아간다', async () => {
    server.use(http.post('*/maps/:mapId/courses', () => error(500, 'INTERNAL')))
    const user = userEvent.setup({ delay: null })
    renderSheet()
    await user.type(await screen.findByLabelText(/요청 사항/), '덜 걷게')
    await user.click(screen.getByRole('button', { name: '코스 짜기' }))
    await confirmCourse(user)
    await user.click(await screen.findByRole('button', { name: '요청 고치기' }))
    expect(screen.getByLabelText(/요청 사항/)).toHaveValue('덜 걷게')
  })

  it('409 는 진행 중인 run 으로 이동하고, 실패한 run 은 「다시 짜기」', async () => {
    server.use(
      http.post('*/maps/:mapId/courses', () => error(409, 'COURSE_IN_PROGRESS', { course_run_id: 'run_x' })),
      http.get('*/course-runs/run_x', () =>
        HttpResponse.json({
          id: 'run_x', map_id: 'map_1', status: 'failed', outcome: null, failure_code: 'INTERRUPTED', goals: [], unmatched: [],
          steps: [], days: [], violations: [], checks: [], excluded: [], snapshot_at: '2026-10-21T00:00:00Z', stale: false,
          created_at: '2026-10-21T00:00:00Z', finished_at: null,
        }),
      ),
    )
    const user = userEvent.setup({ delay: null })
    renderSheet()
    await user.type(await screen.findByRole('textbox'), '둘째 날은 실내 위주로')
    await user.click(await screen.findByRole('button', { name: '코스 짜기' }))
    await confirmCourse(user)
    expect(await screen.findByText('코스를 만들지 못했어요')).toBeInTheDocument()
    expect(screen.getByText(wholeText('코스를 짜다가 중간에 끊겼어요. 잠시 후 다시 시도해 주세요'))).toBeInTheDocument()
    expect(screen.getByText('이미 짜고 있는 코스를 보여 드려요')).toBeInTheDocument()
    await user.click(screen.getByRole('button', { name: '다시 짜기' }))
    expect(await screen.findByRole('button', { name: '코스 짜기' })).toBeInTheDocument() // 진입으로 돌아감
    expect(screen.getByRole('textbox')).toHaveValue('둘째 날은 실내 위주로') // 쓴 요청이 남는다
  })

  it('최근 코스가 없으면 링크가 없고, 있으면 결과를 바로 연다(stale 이면 「다시 짜기」)', async () => {
    const done = {
      id: 'run_old', map_id: 'map_1', status: 'done', outcome: 'solved', failure_code: null, goals: [], unmatched: ['아무거나'],
      steps: [], days: [{ date: '2026-10-10', slots: [{ pin_id: 'pin_1', order: 1, needs_check: false }, { pin_id: 'pin_2', order: 2, needs_check: true }], legs: [{ from_pin_id: 'pin_1', to_pin_id: 'pin_2', mode: 'walk', approx_minutes: 5 }] }],
      violations: [], checks: [], excluded: [], snapshot_at: '2026-10-21T00:00:00Z', stale: true,
      created_at: '2026-10-21T00:00:00Z', finished_at: '2026-10-21T00:00:00Z',
    }
    server.use(http.get('*/maps/:mapId/courses/latest', () => new HttpResponse(null, { status: 204 })))
    const first = renderSheet()
    await screen.findByRole('button', { name: '코스 짜기' })
    expect(screen.queryByRole('button', { name: '최근 코스 보기' })).not.toBeInTheDocument()
    first.unmount()

    server.use(http.get('*/maps/:mapId/courses/latest', () => HttpResponse.json(done)))
    const user = userEvent.setup({ delay: null })
    renderSheet()
    await user.click(await screen.findByRole('button', { name: '최근 코스 보기' }))
    expect(await screen.findByText(/일정이 바뀌었어요/)).toBeInTheDocument()
    expect(screen.getByRole('button', { name: '다시 짜기' })).toBeInTheDocument()
    expect(screen.getByText(/반영하지 못한 요청: 아무거나/)).toBeInTheDocument()
    expect(screen.getAllByText('도보 5분')).toHaveLength(2) // 구간 + 하루 합계
    expect(screen.queryByText(wholeText('? 영업 확인 필요'))).not.toBeInTheDocument()
    expect(screen.getAllByText('영업시간 확인됨')).toHaveLength(1) // pin_1 만 영업 여부를 안다
    expect(screen.queryByText(/영업시간 정보가 없는/)).not.toBeInTheDocument() // checks 가 비었다
  })

  it('위치를 아는 확정 장소가 2곳 미만이면 입력 대신 이유와 확정 탭으로 가는 길을 보인다', async () => {
    resetScenario('happy-path') // 확정 리스트가 빈 상태로
    renderSheet()
    expect(await screen.findByText(wholeText('코스를 짜려면 확정된 장소가 2곳 이상 필요해요'))).toBeInTheDocument()
    expect(screen.getByRole('link', { name: '장소 확정 탭 보기' })).toHaveAttribute('href', '/maps/map_1/shortlist')
    expect(screen.queryByRole('button', { name: '코스 짜기' })).not.toBeInTheDocument()
  })

  it('그날 쉬는 장소 위반이 있으면 「영업시간 확인됨」을 모두 숨기고, 모르는 곳은 한 줄로 센다(루트 검수 #1127)', async () => {
    const done = {
      id: 'run_closed', map_id: 'map_1', status: 'done', outcome: 'violated', failure_code: null, goals: [], unmatched: [],
      steps: [], days: [{ date: '2026-10-10', slots: [{ pin_id: 'pin_1', order: 1, needs_check: false }, { pin_id: 'pin_2', order: 2, needs_check: true }], legs: [{ from_pin_id: 'pin_1', to_pin_id: 'pin_2', mode: 'walk', approx_minutes: 5 }] }],
      violations: [{ kind: 'closed', text: '이 장소는 첫째 날에 쉬는 날이에요' }],
      checks: [{ pin_id: 'pin_2', text: '' }, { pin_id: 'pin_2', text: '' }],
      excluded: [], snapshot_at: '2026-10-21T00:00:00Z', stale: false, created_at: '2026-10-21T00:00:00Z', finished_at: '2026-10-21T00:00:00Z',
    }
    server.use(http.get('*/maps/:mapId/courses/latest', () => HttpResponse.json(done)))
    const user = userEvent.setup({ delay: null })
    renderSheet()
    await user.click(await screen.findByRole('button', { name: '최근 코스 보기' }))
    expect(await screen.findByText('이 장소는 첫째 날에 쉬는 날이에요')).toBeInTheDocument()
    expect(screen.queryByText('영업시간 확인됨')).not.toBeInTheDocument()
    expect(screen.getByText('영업시간 정보가 없는 1곳은 방문 전에 확인해 주세요.')).toBeInTheDocument()
  })

  it('확정 장소가 2곳 미만이어도 최근 코스가 있으면 입력 화면 — 회색 버튼 아래에 이유를 적는다(#1127 리뷰)', async () => {
    resetScenario('happy-path') // 확정 리스트가 빈 상태로
    const done = {
      id: 'run_old', map_id: 'map_1', status: 'done', outcome: 'solved', failure_code: null, goals: [], unmatched: [],
      steps: [], days: [], violations: [], checks: [], excluded: [], snapshot_at: '2026-10-21T00:00:00Z', stale: true,
      created_at: '2026-10-21T00:00:00Z', finished_at: '2026-10-21T00:00:00Z',
    }
    server.use(http.get('*/maps/:mapId/courses/latest', () => HttpResponse.json(done)))
    renderSheet()
    expect(await screen.findByRole('button', { name: '코스 짜기' })).toBeDisabled()
    expect(screen.getByText(wholeText('코스를 짜려면 확정된 장소가 2곳 이상 필요해요'))).toBeInTheDocument()
    expect(screen.getByRole('button', { name: '최근 코스 보기' })).toBeInTheDocument()
  })

  it('확정 장소가 모자랄 때 최근 코스를 받는 동안에는 안내 화면을 먼저 띄우지 않는다 — 「불러오는 중…」', async () => {
    resetScenario('happy-path')
    let release: () => void = () => {}
    const gate = new Promise<void>((r) => (release = r))
    server.use(
      http.get('*/maps/:mapId/courses/latest', async () => {
        await gate
        return new HttpResponse(null, { status: 204 })
      }),
    )
    renderSheet()
    expect(await screen.findByText('불러오는 중…')).toBeInTheDocument()
    expect(screen.queryByText(wholeText('코스를 짜려면 확정된 장소가 2곳 이상 필요해요'))).not.toBeInTheDocument()
    release()
    expect(await screen.findByText(wholeText('코스를 짜려면 확정된 장소가 2곳 이상 필요해요'))).toBeInTheDocument()
  })
})

describe('일정 저장이 가는 중에 코스를 짜면(#1424 e2e)', () => {
  it('저장이 끝난 뒤에 코스를 요청한다 — 서버가 날짜에 넣은 곳을 알고 모드를 정한다', async () => {
    const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
    const dto = await client.fetchQuery({ queryKey: scheduleKeys.one('map_1'), queryFn: () => fetchSchedule('map_1') })
    // 일정 저장(PUT)을 붙잡아 둔다. 처리기가 아무것도 돌려주지 않으면 목 서버의 원래 처리기가 저장한다.
    let release!: () => void
    const gate = new Promise<void>((r) => (release = r))
    const order: string[] = []
    server.use(
      http.put(`${BASE}/maps/map_1/shortlist/schedule`, async () => {
        await gate
        order.push('일정 저장')
      }),
    )
    server.events.on('request:start', ({ request }) => {
      if (request.method === 'POST' && new URL(request.url).pathname === '/maps/map_1/courses') order.push('코스 요청')
    })
    render(
      <QueryClientProvider client={client}>
        <MemoryRouter>
          <CourseBody mapId="map_1" />
        </MemoryRouter>
      </QueryClientProvider>,
    )

    saveSchedule(client, 'map_1', { days: { [dto.start_date]: ['pin_1'] } })
    await userEvent.click(await screen.findByRole('button', { name: '코스 짜기' }))
    await confirmCourse()
    await new Promise((r) => setTimeout(r, 50))
    expect(order).toEqual([])

    release()
    await waitFor(() => expect(order).toEqual(['일정 저장', '코스 요청']))
  })
})

describe('CourseBody — 확정 리스트 불러오기 실패', () => {
  it('실패하면 「장소가 모자라요」 안내 대신 오류와 「다시 불러오기」를 보인다', async () => {
    server.use(http.get('*/maps/:mapId/shortlist', () => error(500, 'INTERNAL')))
    renderSheet()
    expect(await screen.findByText(/확정 리스트를 불러오지 못했어요/)).toBeInTheDocument()
    expect(document.body).not.toHaveTextContent('2곳 이상 필요해요')
    expect(screen.getByRole('button', { name: '다시 불러오기' })).toBeInTheDocument()
  })
})
