import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { server, resetScenario } from '@pingo/contracts/mocks/node'
import { StrictMode } from 'react'
import { MemoryRouter, Route, Routes, useLocation } from 'react-router'
import { afterAll, afterEach, beforeAll, describe, expect, it } from 'vitest'

import CourseBody from '@/features/course/CourseBody'
import { useCourseViewStore } from '@/features/course/courseMapStore'
import { usePinsQuery } from '@/features/map/queries'
import { useToastStore } from '@/features/shell/toast'

import { CHANGED, START_PARAM, useRunAgentAction } from './actions'
import AgentSheet from './AgentSheet'
import type { AgentActionDto } from './model'

const MAP = 'map_1'
const BASE = 'http://localhost'

beforeAll(() => server.listen({ onUnhandledRequest: 'error' }))
afterEach(() => {
  server.resetHandlers()
  server.events.removeAllListeners()
  resetScenario('happy-path')
  useToastStore.setState({ toast: null })
  useCourseViewStore.setState({ runs: {} })
})
afterAll(() => server.close())

function Where() {
  const { pathname, search } = useLocation()
  return <output data-testid="where">{pathname + search}</output>
}

function renderAt(ui: React.ReactNode, entry = `/maps/${MAP}`) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return render(
    <QueryClientProvider client={client}>
      <MemoryRouter initialEntries={[entry]}>
        <Routes>
          <Route path="*" element={ui} />
        </Routes>
        <Where />
      </MemoryRouter>
    </QueryClientProvider>,
  )
}

const where = () => screen.getByTestId('where').textContent

/** 핀 목록을 받은 뒤에 버튼을 그린다 — 지도 화면에서는 핀 목록이 이미 와 있다. */
function RunButton({ action }: { action: AgentActionDto }) {
  const run = useRunAgentAction(MAP)
  const loaded = usePinsQuery(MAP).isSuccess
  return loaded ? (
    <button type="button" onClick={() => run(action)}>
      실행
    </button>
  ) : null
}

const openPin = (pin_ids?: string[]): AgentActionDto => ({ index: 0, type: 'open_pin', label: '이 핀 보기', params: { pin_ids } })

describe('조언 버튼 open_pin·open_course(#1359)', () => {
  it('카테고리 공백(agent-linked)의 「이 핀 보기」는 수락 뒤 지도 탭에서 그 핀 카드를 연다', async () => {
    resetScenario('agent-linked')
    renderAt(<AgentSheet mapId={MAP} onClose={() => {}} />)
    expect(await screen.findByText('은 ♥ 2이고, 2일차 동선에 넣으면 이동이 6분 늘어요', { exact: false })).toBeInTheDocument()
    // 작업 기록의 조사 줄(일정에 끼워 봄)은 공용 줄 그대로다.
    await userEvent.click(screen.getByRole('button', { name: '핑고가 한 일 보기' }))
    expect(screen.getByText('AI 코스 엔진으로 핀 2개를 일정에 끼워 봤어요')).toBeInTheDocument()

    await userEvent.click(screen.getByRole('button', { name: '이 핀 보기' }))
    await waitFor(() => expect(where()).toBe(`/maps/${MAP}?pin=pin_3`))
  })

  it.each([
    ['pin_ids가 비었으면', openPin([])],
    ['pin_ids가 없으면', openPin()],
    ['그 핀이 지워졌으면', openPin(['pin_gone'])],
  ])('open_pin: %s 「상황이 바뀌었어요」 — 이동하지 않는다', async (_, action) => {
    renderAt(<RunButton action={action} />, `/maps/${MAP}/recommend`)
    await userEvent.click(await screen.findByRole('button', { name: '실행' }))
    expect(useToastStore.getState().toast?.message).toBe(CHANGED)
    expect(where()).toBe(`/maps/${MAP}/recommend`)
  })

  it('일정 점검(agent-schedule)은 category 없이도 시트가 그려지고, 버튼은 AI 코스 탭으로 가서 보던 코스를 닫는다', async () => {
    resetScenario('agent-schedule')
    useCourseViewStore.getState().open(MAP, 'course_old')
    renderAt(<AgentSheet mapId={MAP} onClose={() => {}} />)
    expect(await screen.findByText('일정에 다시 볼 곳이 있어요')).toBeInTheDocument()
    expect(screen.getByText('카페 한라')).toBeInTheDocument()

    await userEvent.click(screen.getByRole('button', { name: 'AI 코스로 고쳐 보기' }))
    await waitFor(() => expect(where()).toBe(`/maps/${MAP}/course?${START_PARAM}=1`))
    expect(useCourseViewStore.getState().runs[MAP]).toBeUndefined()
  })

  describe('AI 코스 탭이 ?start 로 열리면', () => {
    async function shortlist(pinIds: string[]) {
      for (const pin_id of pinIds) await fetch(`${BASE}/maps/${MAP}/shortlist`, { method: 'POST', body: JSON.stringify({ pin_id }) })
    }

    it('손으로 누를 때와 같은 확인 창을 한 번 띄우고, 확인하면 코스를 한 번만 요청한다(StrictMode)', async () => {
      await shortlist(['pin_1', 'pin_2'])
      let posts = 0
      server.events.on('request:start', ({ request }) => {
        if (request.method === 'POST' && new URL(request.url).pathname === `/maps/${MAP}/courses`) posts += 1
      })
      renderAt(
        <StrictMode>
          <CourseBody mapId={MAP} />
        </StrictMode>,
        `/maps/${MAP}/course?${START_PARAM}=1`,
      )
      const dialogs = await screen.findAllByRole('alertdialog', { name: '코스를 짤까요?' })
      expect(dialogs).toHaveLength(1)
      // 파라미터는 지운다 — 새로고침·뒤로가기로 다시 시작하지 않는다.
      await waitFor(() => expect(where()).toBe(`/maps/${MAP}/course`))
      expect(posts).toBe(0)

      await userEvent.click(within(dialogs[0]).getByRole('button', { name: '코스 짜기' }))
      await waitFor(() => expect(useCourseViewStore.getState().runs[MAP]).toBeDefined())
      expect(posts).toBe(1)
    })

    it('그새 확정 장소가 모자라졌으면 시작하지 않고 「상황이 바뀌었어요」', async () => {
      renderAt(<CourseBody mapId={MAP} />, `/maps/${MAP}/course?${START_PARAM}=1`)
      await waitFor(() => expect(useToastStore.getState().toast?.message).toBe(CHANGED))
      expect(screen.queryByRole('alertdialog')).not.toBeInTheDocument()
      await waitFor(() => expect(where()).toBe(`/maps/${MAP}/course`))
    })
  })
})
