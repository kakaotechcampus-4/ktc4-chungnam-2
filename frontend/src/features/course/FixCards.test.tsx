import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { http, HttpResponse } from 'msw'
import { server, resetScenario } from '@pingo/contracts/mocks/node'
import { MemoryRouter } from 'react-router'
import { afterAll, afterEach, beforeAll, beforeEach, describe, expect, it } from 'vitest'

import CourseBody from './CourseBody'
import { useAppliedFixStore, useCourseViewStore } from './courseMapStore'
import { applyMoves } from './applyFix'

const BASE = 'http://localhost'

beforeAll(() => server.listen({ onUnhandledRequest: 'error' }))
afterEach(() => {
  server.resetHandlers()
  resetScenario('happy-path')
  useCourseViewStore.setState({ runs: {} })
  useAppliedFixStore.setState({ applied: {} })
})
afterAll(() => server.close())

beforeEach(async () => {
  for (const pin_id of ['pin_1', 'pin_2']) await fetch(`${BASE}/maps/map_1/shortlist`, { method: 'POST', body: JSON.stringify({ pin_id }) })
})

const days = ['2026-10-10', '2026-10-11', '2026-10-12']
const base = {
  id: 'run_fix', map_id: 'map_1', status: 'done', outcome: 'solved', failure_code: null, goals: [], unmatched: [], steps: [], violations: [], checks: [], excluded: [],
  days: days.map((date) => ({ date, slots: [], legs: [] })), snapshot_at: '2026-11-04T00:00:00Z', stale: false, created_at: '2026-11-04T00:00:00Z', finished_at: '2026-11-04T00:00:00Z',
}

function open(run: Record<string, unknown>) {
  server.use(http.get('*/maps/:mapId/courses/latest', () => HttpResponse.json({ ...base, ...run })))
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  render(
    <QueryClientProvider client={client}>
      <MemoryRouter>
        <CourseBody mapId="map_1" />
      </MemoryRouter>
    </QueryClientProvider>,
  )
}

const schedule = async () => (await (await fetch(`${BASE}/maps/map_1/shortlist/schedule`)).json()) as { items: { pin: { id: string }; scheduled_date: string | null }[] }

describe('AI 코스 — 모드별 결과(#1322)', () => {
  it('review: 서버 headline 그대로, 하드 카드가 먼저, 고치지 않는 카드는 「반영」 없이 이유만, 괜찮아요가 보인다', async () => {
    const user = userEvent.setup({ delay: null })
    open({
      mode: 'review', headline: '일정을 점검했어요. 고칠 점 2개',
      fixes: [
        { id: 'fix_2', kind: 'meal', strength: 'soft', text: '식당이 없어요', moves: [], resolved_text: null, remaining_text: null, not_fixed_reason: '고치려면 2곳을 옮겨야 해서 그대로 둬요' },
        { id: 'fix_1', kind: 'closed', strength: 'hard', text: '둘째 날에 쉬어요', moves: [{ pin_id: 'pin_1', from_date: days[0], to_date: days[1] }], resolved_text: '휴무가 풀려요', remaining_text: '도보 90분은 그대로예요', not_fixed_reason: null },
      ],
      checked: [{ kind: 'travel', text: '하루 이동 시간은 모두 괜찮아요' }],
    })
    await user.click(await screen.findByRole('button', { name: '최근 코스 보기' }))
    expect(await screen.findByText('일정을 점검했어요. 고칠 점 2개')).toBeInTheDocument()
    const cards = within(screen.getByRole('list', { name: '고칠 점' })).getAllByRole('article')
    expect(cards[0]).toHaveTextContent('꼭 고칠 것')
    expect(cards[0]).toHaveTextContent('휴무가 풀려요')
    expect(cards[0]).toHaveTextContent('도보 90분은 그대로예요')
    expect(within(cards[1]).queryByRole('button')).not.toBeInTheDocument()
    expect(cards[1]).toHaveTextContent('그대로 둬요')
    expect(screen.getByText(/하루 이동 시간은 모두 괜찮아요/)).toBeInTheDocument()
    expect(screen.queryByText('날짜별 순서')).not.toBeInTheDocument()
  })

  it('mode·fixes·checked 가 없으면 plan 으로 그린다', async () => {
    const user = userEvent.setup({ delay: null })
    open({ mode: undefined, headline: undefined, fixes: undefined, checked: undefined })
    await user.click(await screen.findByRole('button', { name: '최근 코스 보기' }))
    expect(await screen.findByText('날짜별 순서')).toBeInTheDocument()
    expect(screen.queryByRole('list', { name: '고칠 점' })).not.toBeInTheDocument()
  })

  it('fill: 「○일째에 넣기」를 누르면 일정에 저장되고 카드가 반영됨으로 바뀐다', async () => {
    const user = userEvent.setup({ delay: null })
    open({
      mode: 'fill', headline: '남은 1곳을 채워 봤어요',
      fixes: [{ id: 'fix_1', kind: 'unassigned', strength: 'soft', text: '아직 날짜에 넣지 않았어요', moves: [{ pin_id: 'pin_1', from_date: null, to_date: days[1] }], resolved_text: '이동이 가장 짧아요', remaining_text: null, not_fixed_reason: null }],
      checked: [],
    })
    await user.click(await screen.findByRole('button', { name: '최근 코스 보기' }))
    await user.click(await screen.findByRole('button', { name: '둘째 날에 넣기' }))
    expect(await screen.findByText('반영했어요')).toBeInTheDocument()
    expect((await schedule()).items.find((i) => i.pin.id === 'pin_1')?.scheduled_date).toBe(days[1])
  })

  it('409 SHORTLIST_STALE 이면 「일정이 바뀌었어요」로 알리고 반영하지 않는다', async () => {
    const user = userEvent.setup({ delay: null })
    server.use(http.put('*/maps/:mapId/shortlist/schedule', () => HttpResponse.json({ code: 'SHORTLIST_STALE', message: 'stale' }, { status: 409 })))
    open({
      mode: 'review', headline: '고칠 점 1개',
      fixes: [{ id: 'fix_1', kind: 'closed', strength: 'hard', text: '쉬어요', moves: [{ pin_id: 'pin_1', from_date: null, to_date: days[1] }], resolved_text: null, remaining_text: null, not_fixed_reason: null }],
      checked: [],
    })
    await user.click(await screen.findByRole('button', { name: '최근 코스 보기' }))
    await user.click(await screen.findByRole('button', { name: '둘째 날에 넣기' }))
    expect(await screen.findByRole('alert')).toHaveTextContent('일정이 바뀌었어요')
    expect(screen.getByRole('button', { name: '다시 점검' })).toBeInTheDocument()
    expect(screen.queryByText('반영했어요')).not.toBeInTheDocument()
  })
})

describe('한 카드를 반영한 뒤(#1322)', () => {
  it('다른 카드의 「반영」은 막히고 「다시 점검」으로 바뀐다', async () => {
    const user = userEvent.setup({ delay: null })
    const card = (id: string, pin_id: string) => ({ id, kind: 'closed', strength: 'hard', text: `${id} 문제`, moves: [{ pin_id, from_date: null, to_date: days[1] }], resolved_text: null, remaining_text: null, not_fixed_reason: null })
    open({ mode: 'review', headline: '고칠 점 3개', fixes: [card('fix_1', 'pin_1'), card('fix_2', 'pin_2'), { ...card('fix_3', 'pin_1'), moves: [], not_fixed_reason: '그대로 둬요' }], checked: [] })
    await user.click(await screen.findByRole('button', { name: '최근 코스 보기' }))
    expect(await screen.findAllByRole('button', { name: '둘째 날에 넣기' })).toHaveLength(2)

    await user.click(screen.getAllByRole('button', { name: '둘째 날에 넣기' })[0])
    expect(await screen.findByText('반영했어요')).toBeInTheDocument()

    expect(screen.queryByRole('button', { name: '둘째 날에 넣기' })).not.toBeInTheDocument() // 다른 카드 버튼 없음
    expect(screen.getByText('일정이 바뀌었어요. 다시 점검하면 이어서 고칠 수 있어요')).toBeInTheDocument()
    expect(screen.getAllByRole('button', { name: '다시 점검' })).toHaveLength(1) // 반영 안 한 카드 하나
  })
})

describe('stale run(#1322)', () => {
  it('run.stale 이면 모든 카드의 「반영」이 없고 「다시 점검」이 보인다', async () => {
    const user = userEvent.setup({ delay: null })
    const card = (id: string, pin_id: string) => ({ id, kind: 'closed', strength: 'hard', text: `${id} 문제`, moves: [{ pin_id, from_date: null, to_date: days[1] }], resolved_text: null, remaining_text: null, not_fixed_reason: null })
    open({ mode: 'review', stale: true, headline: '고칠 점 2개', fixes: [card('fix_1', 'pin_1'), card('fix_2', 'pin_2')], checked: [] })
    await user.click(await screen.findByRole('button', { name: '최근 코스 보기' }))
    expect(await screen.findAllByRole('button', { name: '다시 점검' })).toHaveLength(2)
    expect(screen.queryByRole('button', { name: /^(반영|.*에 넣기)$/ })).not.toBeInTheDocument()
    expect(screen.getAllByText('일정이 바뀌었어요. 다시 점검하면 이어서 고칠 수 있어요')).toHaveLength(2)
  })
})

describe('applyMoves', () => {
  it('옮겨 간 장소는 남는 장소 뒤에 원래 일정 순서대로 붙는다', () => {
    const next = applyMoves({ days: { a: ['p1', 'p2'], b: ['p3'] } }, [
      { pin_id: 'p2', from_date: 'a', to_date: 'b' },
      { pin_id: 'p1', from_date: 'a', to_date: 'b' },
    ])
    expect(next.days).toEqual({ b: ['p3', 'p1', 'p2'] })
  })
  it('날 맞바꾸기와 미배정 넣기', () => {
    expect(applyMoves({ days: { a: ['p1'], b: ['p2'] } }, [{ pin_id: 'p1', from_date: 'a', to_date: 'b' }, { pin_id: 'p2', from_date: 'b', to_date: 'a' }]).days).toEqual({ a: ['p2'], b: ['p1'] })
    expect(applyMoves({ days: { a: ['p1'] } }, [{ pin_id: 'p9', from_date: null, to_date: 'a' }]).days).toEqual({ a: ['p1', 'p9'] })
  })
})
