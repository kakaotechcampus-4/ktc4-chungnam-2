import type { ReactNode } from 'react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { http, HttpResponse } from 'msw'
import { server, resetScenario } from '@pingo/contracts/mocks/node'
import { afterAll, afterEach, beforeAll, describe, expect, it, vi } from 'vitest'

import { OnboardingBody } from '@/features/map/Onboarding'
import ProfileModal from '@/features/shell/ProfileModal'

beforeAll(() => server.listen({ onUnhandledRequest: 'error' }))
afterEach(() => {
  vi.unstubAllGlobals()
  server.resetHandlers()
  server.events.removeAllListeners()
  resetScenario('happy-path')
})
afterAll(() => server.close())

function renderWithClient(ui: ReactNode) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return render(<QueryClientProvider client={client}>{ui}</QueryClientProvider>)
}

// 첫 요청만 실패시키고, 그 뒤는 목 서버 기본 응답(링크 생성)으로 간다.
function failFirstInvite() {
  let calls = 0
  server.events.on('request:start', ({ request }) => {
    if (request.method === 'POST' && new URL(request.url).pathname === '/maps/map_1/invite') calls++
  })
  server.use(
    http.post('*/maps/:mapId/invite', () => HttpResponse.json({ code: 'INTERNAL', message: 'INTERNAL' }, { status: 500 }), { once: true }),
  )
  return () => calls
}

const SCREENS = [
  { name: '온보딩', ui: <OnboardingBody mapId="map_1" kind="owner" onDone={() => {}} />, shareButton: '친구 초대하기' },
  { name: '프로필 모달', ui: <ProfileModal mapId="map_1" onClose={() => {}} />, shareButton: '초대 링크 공유하기' },
]

describe.each(SCREENS)('$name 초대 링크', ({ ui, shareButton }) => {
  it('만들지 못하면 「다시 시도」가 보이고, 누르면 다시 만들고, 성공하면 공유 버튼이 켜진다', async () => {
    const share = vi.fn()
    vi.stubGlobal('navigator', { ...navigator, share })
    const calls = failFirstInvite()
    const user = userEvent.setup()
    renderWithClient(ui)

    expect(await screen.findByText('초대 링크를 만들지 못했어요')).toBeInTheDocument()
    expect(calls()).toBe(1)
    await user.click(screen.getByRole('button', { name: '다시 시도' }))

    // 다시 시도를 누른 클릭으로는 공유하지 않는다(iOS) — 버튼이 바뀌면 한 번 더 누른다.
    expect(await screen.findByRole('button', { name: shareButton })).toBeEnabled()
    expect(calls()).toBe(2)
    expect(share).not.toHaveBeenCalled()
    expect(screen.queryByText('초대 링크를 만들지 못했어요')).not.toBeInTheDocument()
    expect(screen.queryByRole('button', { name: '다시 시도' })).not.toBeInTheDocument()

    await user.click(screen.getByRole('button', { name: shareButton }))
    expect(share).toHaveBeenCalledWith(expect.objectContaining({ url: expect.any(String) }))
  })
})

describe('온보딩 초대 버튼', () => {
  it('만드는 중에는 꺼져 있고, 실패해도 「나중에 할게요」는 누를 수 있다', async () => {
    failFirstInvite()
    const onDone = vi.fn()
    const user = userEvent.setup()
    renderWithClient(<OnboardingBody mapId="map_1" kind="owner" onDone={onDone} />)

    expect(screen.getByRole('button', { name: '초대 링크를 만드는 중…' })).toBeDisabled()
    expect(await screen.findByRole('button', { name: '다시 시도' })).toBeEnabled()
    await user.click(screen.getByRole('button', { name: '나중에 할게요' }))
    expect(onDone).toHaveBeenCalled()
  })
})
