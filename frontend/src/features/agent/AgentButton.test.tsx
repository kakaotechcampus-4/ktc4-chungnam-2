import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { server, resetScenario } from '@pingo/contracts/mocks/node'
import { MemoryRouter } from 'react-router'
import { afterAll, afterEach, beforeAll, beforeEach, describe, expect, it, vi } from 'vitest'

import AgentButton from './AgentButton'

beforeAll(() => {
  server.listen({ onUnhandledRequest: 'error' })
  // 움직임 줄이기면 시트가 효과 없이 바로 닫힌다(jsdom 에는 transitionend 가 없다).
  vi.stubGlobal('matchMedia', (query: string) => ({ matches: query.includes('reduce'), media: query, addEventListener() {}, removeEventListener() {} }))
})
beforeEach(() => localStorage.clear())
afterEach(() => {
  server.resetHandlers()
  resetScenario('happy-path')
})
afterAll(() => {
  server.close()
  vi.unstubAllGlobals()
})

function mount() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return render(
    <QueryClientProvider client={client}>
      <MemoryRouter>
        <AgentButton mapId="map_1" hidden={false} fading={false} />
      </MemoryRouter>
    </QueryClientProvider>,
  )
}

describe('「핑고 AI 조언」 말풍선(#1433)', () => {
  it('두 번 열어 보면 말풍선을 숨기고 핑고만 남는다 — 다시 열어도 그대로다', async () => {
    const user = userEvent.setup({ delay: null })
    const { unmount } = mount()
    const button = () => screen.getByRole('button', { name: /^핑고 AI 조언/ })
    // 목 서버에 안 본 제안이 있어 첫 번째는 제안 문장으로 뜨고, 보고 나면 기능 이름으로 돌아온다.
    await user.click(await screen.findByRole('button', { name: /새 제안/ }))
    await user.keyboard('{Escape}')
    expect(await within(button()).findByText('핑고 AI 조언')).toBeInTheDocument()
    await user.click(button())
    await user.keyboard('{Escape}')
    expect(within(button()).queryByText('핑고 AI 조언')).not.toBeInTheDocument()
    unmount()
    mount()
    expect(within(button()).queryByText('핑고 AI 조언')).not.toBeInTheDocument()
  })

  it('안 본 새 제안은 열어 본 횟수와 상관없이 제목을 말하고, 열어 보면 사라진다', async () => {
    localStorage.setItem('pingo-advice-opens', '2')
    const user = userEvent.setup({ delay: null })
    mount()
    const title = '확정 리스트에 카페가 아직 없어요'
    const button = await screen.findByRole('button', { name: `핑고 AI 조언, 새 제안: ${title}` })
    expect(within(button).getByText(title)).toBeInTheDocument()
    await user.click(button)
    await user.keyboard('{Escape}')
    await waitFor(() => expect(screen.getByRole('button', { name: '핑고 AI 조언' })).toBeInTheDocument())
    expect(screen.queryByText(title)).not.toBeInTheDocument()
  })
})
