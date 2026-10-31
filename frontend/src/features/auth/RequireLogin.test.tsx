import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { resetScenario, server } from '@pingo/contracts/mocks/node'
import { http, HttpResponse } from 'msw'
import { MemoryRouter, Route, Routes, useLocation } from 'react-router'
import { afterAll, afterEach, beforeAll, beforeEach, describe, expect, it } from 'vitest'

import RequireLogin from './RequireLogin'

beforeAll(() => server.listen({ onUnhandledRequest: 'error' }))
beforeEach(() => resetScenario('withdrawn-relogin'))
afterEach(() => server.resetHandlers())
afterAll(() => server.close())

const EXPIRED = '선택 시간이 지났어요. 카카오로 다시 시작해 주세요'

function Search() {
  return <span data-testid="search">{useLocation().search}</span>
}

function show(entry = '/?login_pending=withdrawn_account') {
  const client = new QueryClient()
  return render(
    <QueryClientProvider client={client}>
      <MemoryRouter initialEntries={[entry]}>
        <Search />
        <Routes>
          <Route element={<RequireLogin />}>
            <Route path="/" element={<p>내 지도 목록</p>} />
          </Route>
        </Routes>
      </MemoryRouter>
    </QueryClientProvider>,
  )
}

/** POST /auth/pending 이 받은 본문과 Content-Type 을 모은다 — 목 핸들러로 그대로 넘긴다. */
function recordChoices() {
  const sent: { choice: unknown; type: string | null }[] = []
  server.events.on('request:start', ({ request }) => {
    if (request.method !== 'POST' || !request.url.endsWith('/auth/pending')) return
    void request.clone().json().then((body: { choice?: unknown }) => sent.push({ choice: body.choice, type: request.headers.get('Content-Type') }))
  })
  return sent
}

afterEach(() => server.events.removeAllListeners())

describe('탈퇴 계정 재로그인 선택 화면(#858)', () => {
  it('콜백이 login_pending 으로 돌려보내면 로그인 대신 선택 화면을 띄우고 주소에서 지운다', async () => {
    show()
    expect(await screen.findByRole('heading', { name: '이전에 탈퇴한 계정이 있어요' })).toBeInTheDocument()
    // 목 서버는 이틀 전에 탈퇴했다 — 남은 날수는 응답의 days_left 그대로다.
    expect(screen.getByText('탈퇴했던 나')).toBeInTheDocument()
    expect(screen.getByText(/5일 안에는 기존 계정을 되살릴 수 있어요/)).toBeInTheDocument()
    expect(screen.getByText(/5일 남음/)).toBeInTheDocument()
    expect(screen.getByText('기존 계정은 바로 삭제돼요')).toBeInTheDocument()
    expect(screen.getByTestId('search')).toHaveTextContent(/^$/)
    expect(screen.queryByText('내 지도 목록')).not.toBeInTheDocument()
  })

  it('되살리기는 JSON 으로 restore 를 보내고 로그인된다', async () => {
    const sent = recordChoices()
    show()
    await userEvent.click(await screen.findByRole('button', { name: '기존 계정 되살리기' }))
    expect(await screen.findByText('내 지도 목록')).toBeInTheDocument()
    expect(sent).toEqual([{ choice: 'restore', type: 'application/json' }])
  })

  it('새 계정으로 시작은 한 번 더 묻고, 취소하면 보내지 않는다', async () => {
    const sent = recordChoices()
    show()
    await userEvent.click(await screen.findByRole('button', { name: '새 계정으로 시작' }))
    const dialog = await screen.findByRole('alertdialog')
    expect(within(dialog).getByText('기존 계정은 바로 삭제되고 되살릴 수 없어요.')).toBeInTheDocument()

    await userEvent.click(within(dialog).getByRole('button', { name: '취소' }))
    await waitFor(() => expect(screen.queryByRole('alertdialog')).not.toBeInTheDocument())
    expect(sent).toEqual([])

    await userEvent.click(screen.getByRole('button', { name: '새 계정으로 시작' }))
    await userEvent.click(within(await screen.findByRole('alertdialog')).getByRole('button', { name: '새로 시작' }))
    expect(await screen.findByText('내 지도 목록')).toBeInTheDocument()
    expect(sent).toEqual([{ choice: 'restart', type: 'application/json' }])
  })

  it('선택 시간이 지났으면(GET 404) 안내와 함께 로그인 화면으로', async () => {
    resetScenario('happy-path') // 고를 게 없다 — 쿠키 만료와 같다
    show()
    expect(await screen.findByRole('alert')).toHaveTextContent(EXPIRED)
    expect(screen.getByRole('link', { name: /카카오로 다시 시도하기/ })).toBeInTheDocument()
    // 게스트 세션이 남아 있어도 지도 목록으로 가지 않는다.
    expect(screen.queryByText('내 지도 목록')).not.toBeInTheDocument()
  })

  it('고르는 사이 만료됐으면(POST 404) 안내와 함께 로그인 화면으로', async () => {
    server.use(
      http.post('*/auth/pending', () =>
        HttpResponse.json({ code: 'NO_PENDING_LOGIN', message: EXPIRED }, { status: 404 }),
      ),
    )
    show()
    await userEvent.click(await screen.findByRole('button', { name: '기존 계정 되살리기' }))
    expect(await screen.findByRole('alert')).toHaveTextContent(EXPIRED)
    expect(screen.queryByText('내 지도 목록')).not.toBeInTheDocument()
  })

  it('그 밖의 실패는 화면에 남아 다시 고를 수 있다', async () => {
    server.use(
      http.post('*/auth/pending', () =>
        HttpResponse.json({ code: 'INTERNAL_ERROR', message: '서버 오류' }, { status: 500 }),
      ),
    )
    show()
    await userEvent.click(await screen.findByRole('button', { name: '기존 계정 되살리기' }))
    expect(await screen.findByText(/처리하지 못했어요/)).toBeInTheDocument()
    expect(screen.getByRole('button', { name: '기존 계정 되살리기' })).toBeEnabled()
  })

  it('login_pending 이 없으면 평소처럼 세션으로 판단한다', async () => {
    resetScenario('happy-path')
    show('/')
    expect(await screen.findByText('내 지도 목록')).toBeInTheDocument()
  })
})
