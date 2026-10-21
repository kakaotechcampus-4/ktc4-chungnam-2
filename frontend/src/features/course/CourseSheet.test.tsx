import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { http, HttpResponse } from 'msw'
import { server, resetScenario } from '@pingo/contracts/mocks/node'
import { afterAll, afterEach, beforeAll, beforeEach, describe, expect, it } from 'vitest'

import CourseSheet from './CourseSheet'

const BASE = 'http://localhost'

beforeAll(() => server.listen({ onUnhandledRequest: 'error' }))
afterEach(() => {
  server.resetHandlers()
  server.events.removeAllListeners()
  resetScenario('happy-path')
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
      <CourseSheet mapId="map_1" onClose={() => {}} />
    </QueryClientProvider>,
  )
}

const error = (status: number, code: string, detail?: Record<string, unknown>) =>
  HttpResponse.json({ code, message: code, ...(detail ? { detail } : {}) }, { status })

describe('AI 코스 짜기 시트', () => {
  it('진입 → 진행(작업 기록이 늘어남) → 결과, 끝나면 조회를 멈춘다', async () => {
    const user = userEvent.setup()
    let polls = 0
    server.events.on('request:start', ({ request }) => {
      if (new URL(request.url).pathname.startsWith('/course-runs/')) polls++
    })
    renderSheet()

    expect(await screen.findByText(/10\.\d+ \(.\) ~ /)).toBeInTheDocument() // 지도 여행 날짜
    await user.type(screen.getByLabelText(/요청 한 줄/), '덜 걷게 해 주세요')
    await user.click(screen.getByRole('button', { name: '코스 짜기' }))

    // 진행: 첫 조회는 단계 2개 — 첫 줄 「이해」는 카드
    const log = await screen.findByRole('list', { name: '작업 기록' })
    expect(within(log).getAllByRole('listitem')).toHaveLength(2)
    expect(within(log).getByRole('heading', { name: /이렇게 이해했어요/ })).toBeInTheDocument()
    expect(within(log).getByText('코드')).toBeInTheDocument() // 누가 칩

    // 두 번째 조회에서 5개로 늘어난다(앞 줄은 그대로, 뒤에만 붙음)
    await waitFor(() => expect(within(screen.getByRole('list', { name: '작업 기록' })).getAllByRole('listitem')).toHaveLength(5), { timeout: 5000 })

    // 결과
    expect(await screen.findByText('요청한 것', undefined, { timeout: 6000 })).toBeInTheDocument()
    expect(screen.getByText('하루 걷는 시간 줄이기')).toBeInTheDocument()
    expect(screen.getByText('지킴')).toBeInTheDocument()
    expect(screen.getByRole('heading', { name: /첫째 날 · / })).toBeInTheDocument()
    expect(screen.getAllByText('? 영업 확인 필요').length).toBeGreaterThan(0)
    expect(screen.queryByText('다시 짜기')).not.toBeInTheDocument() // stale 아님
    expect(screen.queryAllByRole('link', { name: /길찾기/, hidden: true }).every((a) => a.getAttribute('href')?.startsWith('https://map.kakao.com/link/by/') && a.getAttribute('target') === '_blank')).toBe(true)
    // 장소 이름은 이미 받은 확정 리스트에서 찾는다
    expect(screen.queryByText('이 장소')).not.toBeInTheDocument()

    // 작업 기록을 다시 볼 수 있다
    await user.click(screen.getByRole('button', { name: '작업 기록 보기' }))
    expect(screen.getByRole('list', { name: '작업 기록' })).toBeInTheDocument()

    // done 이후엔 더 부르지 않는다
    const seen = polls
    await new Promise((r) => setTimeout(r, 2500))
    expect(polls).toBe(seen)
  }, 20000)

  it('429 는 「오늘은 다 썼어요」', async () => {
    server.use(http.post('*/maps/:mapId/courses', () => error(429, 'COURSE_LIMIT', { limit: 5, used: 5 })))
    const user = userEvent.setup()
    renderSheet()
    await user.click(await screen.findByRole('button', { name: '코스 짜기' }))
    expect(await screen.findByRole('alert')).toHaveTextContent('오늘은 다 썼어요')
  })

  it('422 는 장소 부족 안내', async () => {
    server.use(http.post('*/maps/:mapId/courses', () => error(422, 'COURSE_NOT_ENOUGH_PLACES', { min: 2, count: 1 })))
    const user = userEvent.setup()
    renderSheet()
    await user.click(await screen.findByRole('button', { name: '코스 짜기' }))
    expect(await screen.findByRole('alert')).toHaveTextContent('2곳 이상')
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
    const user = userEvent.setup()
    renderSheet()
    await user.click(await screen.findByRole('button', { name: '코스 짜기' }))
    expect(await screen.findByText('코스를 만들지 못했어요')).toBeInTheDocument()
    expect(screen.getByText(/서버가 다시 켜지면서/)).toBeInTheDocument()
    await user.click(screen.getByRole('button', { name: '다시 짜기' }))
    expect(await screen.findByRole('button', { name: '코스 짜기' })).toBeInTheDocument() // 진입으로 돌아감
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
    const user = userEvent.setup()
    renderSheet()
    await user.click(await screen.findByRole('button', { name: '최근 코스 보기' }))
    expect(await screen.findByText(/확정 리스트가 바뀌었어요/)).toBeInTheDocument()
    expect(screen.getByRole('button', { name: '다시 짜기' })).toBeInTheDocument()
    expect(screen.getByText(/반영하지 못했어요: 「아무거나」/)).toBeInTheDocument()
    expect(screen.getAllByText('도보 5분')).toHaveLength(2) // 구간 + 하루 합계
    expect(screen.getAllByText('? 영업 확인 필요')).toHaveLength(1)
  })
})
