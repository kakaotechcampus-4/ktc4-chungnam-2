import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { server, resetScenario } from '@pingo/contracts/mocks/node'
import type { ReactNode } from 'react'
import { MemoryRouter } from 'react-router'
import { afterAll, afterEach, beforeAll, describe, expect, it } from 'vitest'

import type { Pin } from '@/features/map/model'
import { PinDetailBody } from '@/features/map/PinDetail'
import { useToastStore } from '@/features/shell/toast'

import type { ReviewPageDto } from './model'
import PlaceReviews from './PlaceReviews'

const BASE = 'http://localhost'
const get = <T,>(path: string) => fetch(`${BASE}${path}`).then((r) => r.json() as Promise<T>)

beforeAll(() => server.listen({ onUnhandledRequest: 'error' }))
afterEach(() => {
  server.resetHandlers()
  resetScenario('happy-path')
  useToastStore.setState({ toast: null })
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

/** 목 서버 시드: pin_1(자체 DB 장소)에 다른 사람 후기 2개. */
const pin1 = async () => (await get<Pin[]>('/maps/map_1/pins')).find((p) => p.id === 'pin_1')!
const toast = () => useToastStore.getState().toast?.message

async function writeReview(user: ReturnType<typeof userEvent.setup>, stars: string, text: string) {
  const sheet = await screen.findByRole('dialog')
  await user.click(within(sheet).getByRole('radio', { name: stars }))
  const box = within(sheet).getByRole('textbox', { name: '후기' })
  await user.clear(box)
  await user.type(box, text)
  await user.click(within(sheet).getByRole('button', { name: '저장' }))
}

describe('장소 후기(#953)', () => {
  it('평균·개수와 최신순 목록 — 작성자는 「핑고 사용자」, 남의 후기에는 신고', async () => {
    const page = await get<ReviewPageDto>('/pins/pin_1/reviews')
    renderWithClient(<PlaceReviews pin={await pin1()} />)

    expect(await screen.findByText(`${page.summary.average_rating} · 후기 ${page.summary.count}개`)).toBeInTheDocument()
    const rows = within(screen.getByRole('list')).getAllByRole('listitem')
    expect(rows.map((r) => within(r).getByText(/국물|줄이/).textContent)).toEqual(page.items.map((i) => i.body))
    for (const row of rows) {
      expect(within(row).getByText('핑고 사용자')).toBeInTheDocument()
      expect(within(row).getByRole('button', { name: '신고' })).toBeInTheDocument()
    }
    expect(screen.queryByRole('button', { name: '더 보기' })).not.toBeInTheDocument()
  })

  it('첫 저장은 크레딧을 받고(credited) 수정은 받지 않는다 — 내 후기는 「나」, 신고 대신 삭제', async () => {
    const before = await get<{ balance: number; review_reward: number }>('/credits/me')
    const user = userEvent.setup()
    renderWithClient(<PlaceReviews pin={await pin1()} />)

    await user.click(await screen.findByRole('button', { name: '후기 쓰기' }))
    expect(screen.getByText('후기를 쓰면 크레딧을 드려요. 별점과 상관없이 같아요.')).toBeInTheDocument()
    await writeReview(user, '5점', '아침에 가기 좋아요')
    await waitFor(() => expect(toast()).toBe(`${before.review_reward} 크레딧을 받았어요`))
    expect((await get<{ balance: number }>('/credits/me')).balance).toBe(before.balance + before.review_reward)

    const mine = (await screen.findByText('나')).closest('li')!
    expect(within(mine).getByText('아침에 가기 좋아요')).toBeInTheDocument()
    expect(within(mine).getByRole('button', { name: '삭제' })).toBeInTheDocument()
    expect(within(mine).queryByRole('button', { name: '신고' })).not.toBeInTheDocument()

    // 수정 — 내 후기 값으로 열린다
    await user.click(screen.getByRole('button', { name: '내 후기 고치기' }))
    expect(within(await screen.findByRole('dialog')).getByRole('radio', { name: '5점' })).toHaveAttribute('aria-checked', 'true')
    await writeReview(user, '3점', '줄이 길어졌어요')
    await waitFor(() => expect(toast()).toBe('후기를 저장했어요'))
    expect(await screen.findByText('줄이 길어졌어요')).toBeInTheDocument()
  })

  it('글 상한은 응답의 limits.body_max — 별점과 글이 있어야 저장할 수 있다', async () => {
    const { limits } = await get<ReviewPageDto>('/pins/pin_1/reviews')
    const user = userEvent.setup()
    renderWithClient(<PlaceReviews pin={await pin1()} />)
    await user.click(await screen.findByRole('button', { name: '후기 쓰기' }))

    const sheet = await screen.findByRole('dialog')
    const box = within(sheet).getByRole('textbox', { name: '후기' })
    expect(box).toHaveAttribute('maxLength', String(limits.body_max))
    const save = within(sheet).getByRole('button', { name: '저장' })
    await user.type(box, '   ')
    await user.click(within(sheet).getByRole('radio', { name: '4점' }))
    expect(save).toBeDisabled()
    await user.type(box, '좋아요')
    expect(save).toBeEnabled()
  })

  it('내 후기 삭제는 한 번 묻고 지운다', async () => {
    await fetch(`${BASE}/pins/pin_1/reviews/me`, { method: 'PUT', body: JSON.stringify({ rating: 4, body: '지울 후기' }) })
    const user = userEvent.setup()
    renderWithClient(<PlaceReviews pin={await pin1()} />)

    await user.click(within((await screen.findByText('지울 후기')).closest('li')!).getByRole('button', { name: '삭제' }))
    await user.click(within(await screen.findByRole('alertdialog')).getByRole('button', { name: '삭제' }))
    await waitFor(() => expect(screen.queryByText('지울 후기')).not.toBeInTheDocument())
    expect(screen.getByRole('button', { name: '후기 쓰기' })).toBeInTheDocument()
  })

  it('신고는 한 번 묻고, 보내면 「신고했어요」 뒤 그 줄은 「신고함」', async () => {
    const user = userEvent.setup()
    renderWithClient(<PlaceReviews pin={await pin1()} />)

    const row = within(await screen.findByRole('list')).getAllByRole('listitem')[0]
    await user.click(within(row).getByRole('button', { name: '신고' }))
    await user.click(within(await screen.findByRole('alertdialog')).getByRole('button', { name: '신고' }))
    await waitFor(() => expect(toast()).toBe('신고했어요'))
    expect(within(row).getByRole('button', { name: '신고함' })).toBeDisabled()
  })

  it('게스트는 목록만 — 쓰기·신고 대신 카카오 안내(숫자는 403 detail 에서)', async () => {
    resetScenario('guest')
    const { detail } = await get<{ detail: { initial_credits: number } }>('/credits/me')
    renderWithClient(<PlaceReviews pin={await pin1()} />)

    expect(await screen.findByText(`카카오로 로그인하면 ${detail.initial_credits} 크레딧을 드려요`)).toBeInTheDocument()
    expect(screen.getAllByText('핑고 사용자')).toHaveLength(2)
    expect(screen.queryByRole('button', { name: '후기 쓰기' })).not.toBeInTheDocument()
    expect(screen.queryByRole('button', { name: '신고' })).not.toBeInTheDocument()
  })

  it('핀 상세: 자체 DB 핀에만 후기 영역이 있고 실시간 핀에는 없다', async () => {
    const pin = await pin1()
    const view = renderWithClient(<PinDetailBody pin={pin} mapId="map_1" members={[]} onDone={() => {}} />)
    expect(await screen.findByRole('heading', { name: '장소 후기' })).toBeInTheDocument()
    view.unmount()

    // 실시간 핀은 영역 자체를 두지 않는다 — 목록 요청도 보내지 않는다.
    const asked: string[] = []
    server.events.on('request:start', ({ request }) => void asked.push(new URL(request.url).pathname))
    renderWithClient(<PinDetailBody pin={{ ...pin, source: 'live' }} mapId="map_1" members={[]} onDone={() => {}} />)
    await waitFor(() => expect(asked.length).toBeGreaterThan(0))
    expect(screen.queryByRole('heading', { name: '장소 후기' })).not.toBeInTheDocument()
    expect(asked).not.toContain('/pins/pin_1/reviews')
    server.events.removeAllListeners()
  })
})
