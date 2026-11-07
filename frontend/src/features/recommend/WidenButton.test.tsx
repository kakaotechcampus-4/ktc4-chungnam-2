import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { server, resetScenario } from '@pingo/contracts/mocks/node'
import type { ReactNode } from 'react'
import { MemoryRouter } from 'react-router'
import { afterAll, afterEach, beforeAll, describe, expect, it } from 'vitest'

import { ApiError } from '@/api'

import { createRun, widenRun } from './api'
import { radiusKm, WIDEN_LIMIT_MESSAGE } from './model'
import { NoResults } from './Results'

beforeAll(() => server.listen({ onUnhandledRequest: 'error' }))
afterEach(() => {
  server.resetHandlers()
  resetScenario('happy-path')
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

const noResults = new ApiError(404, { code: 'NO_RESULTS', message: 'NO_RESULTS', detail: { funnel: [] } })

/** 반경 숫자는 목 서버(docs/constraints.md 값)가 내린 것만 쓴다 — 테스트도 숫자를 다시 적지 않는다(#1468). */
describe('「반경 넓히기」는 서버가 내린 m 값으로 안내한다(#1468)', () => {
  it('확인 창: 지금 반경 → 넓힌 뒤 반경(km), 도보 분·「핀 주변」은 없다', async () => {
    const run = await createRun('map_1', '음식점', crypto.randomUUID())
    expect(run.default_radius_m).toBeDefined()
    expect(run.next_default_radius_m).toBeTruthy()
    renderWithClient(<NoResults mapId="map_1" run={run} error={noResults} onFixEvidence={() => {}} />)

    await userEvent.click(screen.getByRole('button', { name: '반경 넓히기' }))
    const dialog = await screen.findByRole('alertdialog', { name: '기본 반경만 넓혀서 다시 찾을까요?' })
    expect(
      within(dialog).getByText(`추천받은 지도 가운데 반경 ${radiusKm(run.default_radius_m!)}에서 ${radiusKm(run.next_default_radius_m!)}로`),
    ).toBeInTheDocument()
    expect(dialog).not.toHaveTextContent(/도보|핀 주변/)
  })

  it('서버가 상한이라고 알려 주면(next null) 누르기 전에 끄고 이유를 붙인다', async () => {
    let run = await createRun('map_1', '음식점', crypto.randomUUID())
    // 목 서버가 상한이라고 할 때까지 넓힌다(횟수를 적지 않는다).
    for (let i = 0; run.next_default_radius_m !== null; i++) {
      if (i > 10) throw new Error('상한에 닿지 않는다')
      run = await widenRun(run.id)
    }
    renderWithClient(<NoResults mapId="map_1" run={run} error={noResults} onFixEvidence={() => {}} />)

    const button = screen.getByRole('button', { name: '반경 넓히기' })
    expect(button).toBeDisabled()
    expect(button).toHaveAccessibleDescription(WIDEN_LIMIT_MESSAGE)
    await userEvent.click(button)
    expect(screen.queryByRole('alertdialog')).not.toBeInTheDocument()
  })
})
