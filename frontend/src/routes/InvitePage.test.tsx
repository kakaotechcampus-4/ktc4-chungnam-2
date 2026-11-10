import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen } from '@testing-library/react'
import { server, resetScenario } from '@pingo/contracts/mocks/node'
import { http, HttpResponse } from 'msw'
import { MemoryRouter, Route, Routes } from 'react-router'
import { afterAll, afterEach, beforeAll, describe, expect, it } from 'vitest'

import InvitePage from './InvitePage'

beforeAll(() => server.listen({ onUnhandledRequest: 'error' }))
afterEach(() => {
  server.resetHandlers()
  resetScenario('happy-path')
})
afterAll(() => server.close())

const SUMMARY = {
  title: '부산 여행',
  start_date: '2026-12-01',
  end_date: '2026-12-03',
  member_count: 3,
  pin_count: 5,
  inviter_display_name: '박서영',
  expires_at: '2026-12-31T00:00:00Z',
}

function openInvite(summary: Record<string, unknown>) {
  server.use(http.get('*/invites/:token', () => HttpResponse.json(summary)))
  render(
    <QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}>
      <MemoryRouter initialEntries={['/invites/tok_1']}>
        <Routes>
          <Route path="/invites/:token" element={<InvitePage />} />
          <Route path="/maps/:mapId" element={<p>지도 화면</p>} />
        </Routes>
      </MemoryRouter>
    </QueryClientProvider>,
  )
}

describe('초대 링크 — 이미 구성원이면 수락 카드 없이 지도로(#1563)', () => {
  it('서버가 already_member_map_id 를 주면 그 지도로 간다', async () => {
    openInvite({ ...SUMMARY, already_member_map_id: 'map_9' })
    expect(await screen.findByText('지도 화면')).toBeInTheDocument()
  })

  it('구성원이 아니면 지금처럼 수락 카드를 보인다', async () => {
    openInvite(SUMMARY)
    expect(await screen.findByText('부산 여행')).toBeInTheDocument()
    expect(screen.queryByText('지도 화면')).not.toBeInTheDocument()
  })
})
