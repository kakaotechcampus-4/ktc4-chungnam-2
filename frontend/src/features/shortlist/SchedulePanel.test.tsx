import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { cleanup, fireEvent, render, screen, within, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { server, resetScenario } from '@pingo/contracts/mocks/node'
import { MemoryRouter } from 'react-router'
import { afterAll, afterEach, beforeAll, beforeEach, describe, expect, it } from 'vitest'

import { EditMapDialog } from '@/features/maps/MapLifecycle'
import type { MapHeaderView } from '@/features/maps/model'
import { pickDate } from '@/test/date'
import { wholeText } from '@/test/text'

import SchedulePanel from './SchedulePanel'
import { seedSchedule, serverDays } from './__fixtures__/serverSchedule'
import { forgetSchedule } from './scheduleStore'

const BASE = 'http://localhost'
const MAP = 'map_1' // 목 서버 지도: 2026-10-10 ~ 10-12(3일)

beforeAll(() => server.listen({ onUnhandledRequest: 'error' }))
afterEach(() => {
  server.resetHandlers()
  resetScenario('happy-path')
  forgetSchedule()
})
afterAll(() => server.close())

// 목 서버의 확정 리스트에 핀 셋을 넣는다(흑돼지식당·우진해장국·카페 한라).
beforeEach(async () => {
  for (const pin_id of ['pin_1', 'pin_2', 'pin_3']) {
    await fetch(`${BASE}/maps/${MAP}/shortlist`, { method: 'POST', body: JSON.stringify({ pin_id }) })
  }
})

function renderPanel() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return render(
    <QueryClientProvider client={client}>
      <MemoryRouter>
        <SchedulePanel mapId={MAP} />
      </MemoryRouter>
    </QueryClientProvider>,
  )
}

describe('「일정 짜기」 패널(넓은 화면)', () => {
  it('날짜 칸만 있고(끌어올 장소 칸은 없다), 그날 순서대로 번호가 붙는다', async () => {
    await seedSchedule(MAP, { days: { '2026-10-11': ['pin_2', 'pin_1'] } })
    renderPanel()
    await screen.findByRole('region', { name: /^첫째 날/ })
    expect(screen.getAllByRole('region').map((r) => r.getAttribute('aria-label'))).toEqual(['첫째 날 · 10.10 (토)', '둘째 날 · 10.11 (일)', '셋째 날 · 10.12 (월)'])
    expect(screen.queryByText('아직 안 정한 곳')).not.toBeInTheDocument()
    const second = within(screen.getByRole('region', { name: /^둘째 날/ }))
    expect(second.getAllByRole('listitem').map((li) => li.textContent)).toEqual([expect.stringMatching(/^1우진해장국/), expect.stringMatching(/^2흑돼지식당/)])
  })

  it('≡ 에서 ↑↓ 로 그날 순서를 바꾸고, 「빼기」로 일정에서 뺀다 — 다시 열어도 남는다', async () => {
    await seedSchedule(MAP, { days: { '2026-10-10': ['pin_1', 'pin_2'] } })
    renderPanel()
    fireEvent.keyDown(await screen.findByRole('button', { name: '흑돼지식당 순서 바꾸기' }), { key: 'ArrowDown' })
    await waitFor(async () => expect((await serverDays(MAP))['2026-10-10']).toEqual(['pin_2', 'pin_1']))

    await userEvent.click(screen.getByRole('button', { name: '우진해장국 일정에서 빼기' }))
    await waitFor(async () => expect((await serverDays(MAP))['2026-10-10']).toEqual(['pin_1']))

    cleanup()
    renderPanel()
    const first = within(await screen.findByRole('region', { name: /^첫째 날/ }))
    expect(first.getByText('흑돼지식당')).toBeInTheDocument()
    expect(first.queryByText('우진해장국')).not.toBeInTheDocument()
  })

  it('일정이 비어 있으면 넣는 법을 한 줄로 알린다', async () => {
    renderPanel()
    expect(await screen.findByText(wholeText('확정된 장소를 날짜별 칸으로 끌어 오거나 「넣기」를 눌러 하루 일정을 완성해 보세요'))).toBeInTheDocument()
  })
})

describe('지도 정보 수정 — 빠지는 날의 일정 안내', () => {
  const map = { id: MAP, title: '제주도 여행', startDate: '2026-10-10', endDate: '2026-10-12', dates: '', memberCount: 4 } as MapHeaderView

  function renderEdit() {
    const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
    return render(
      <QueryClientProvider client={client}>
        <MemoryRouter>
          <EditMapDialog map={map} onCancel={() => {}} />
        </MemoryRouter>
      </QueryClientProvider>,
    )
  }

  it('빠지는 날에 넣은 장소가 있으면 몇 곳이 돌아가는지 알리고, 없으면 알리지 않는다', async () => {
    await seedSchedule(MAP, { days: { '2026-10-10': ['pin_1', 'pin_2'], '2026-10-12': ['pin_3'] } })
    renderEdit()
    expect(screen.queryByText(/확정된 장소로 돌아가요/)).not.toBeInTheDocument()

    // 서버 일정이 화면에 도착한 뒤(받는 동안은 일정이 비어 있다) 빠지는 날을 만든다.
    await pickDate(/^시작일/, '2026-10-11')
    expect(await screen.findByText('기간이 줄어 빠지는 날에 넣은 2곳은 확정된 장소로 돌아가요')).toBeInTheDocument()

    // 하루 늘리기만 하면 빠지는 날이 없다.
    await pickDate(/^시작일/, '2026-10-09')
    expect(screen.queryByText(/확정된 장소로 돌아가요/)).not.toBeInTheDocument()
  })

  it('저장하면 일정을 다시 받는다 — 서버가 뺀 장소와 바뀐 version을 화면이 들고 있게', async () => {
    await seedSchedule(MAP, { days: { '2026-10-10': ['pin_1'] } })
    const gets: string[] = []
    const listen = ({ request }: { request: Request }) => {
      if (request.method === 'GET' && request.url.endsWith(`/maps/${MAP}/shortlist/schedule`)) gets.push(request.url)
    }
    server.events.on('request:start', listen)
    renderEdit()
    await waitFor(() => expect(gets).toHaveLength(1))

    await pickDate(/^시작일/, '2026-10-11')
    await userEvent.click(await screen.findByRole('button', { name: '저장' }))
    await waitFor(() => expect(gets).toHaveLength(2))
    server.events.removeAllListeners()
  })
})
