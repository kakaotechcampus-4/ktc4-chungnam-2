import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { server } from '@pingo/contracts/mocks/node'
import { http, HttpResponse } from 'msw'
import { afterAll, afterEach, beforeAll, describe, expect, it, vi } from 'vitest'

import type { RecommendRunDto } from '@/features/recommend/model'

import RunAdvice from './RunAdvice'

beforeAll(() => server.listen({ onUnhandledRequest: 'error' }))
afterEach(() => server.resetHandlers())
afterAll(() => server.close())

const run = { id: 'run_x', category: '카페', attempt_no: 1, status: 'done' } as RecommendRunDto

function show(body: object | null, status = 200, onOpenEvidence = vi.fn()) {
  server.use(http.get('*/runs/run_x/advice', () => (status === 204 ? new HttpResponse(null, { status }) : HttpResponse.json(body, { status }))))
  const client = new QueryClient()
  return render(
    <QueryClientProvider client={client}>
      <RunAdvice mapId="map_1" run={run} widen={<button type="button">반경 넓히기</button>} onOpenEvidence={onOpenEvidence} />
    </QueryClientProvider>,
  )
}

describe('추천 막힘 조언(#589)', () => {
  it('200이면 문장과 버튼(반경 넓히기는 화면 버튼, 근거 버튼은 결과 위 조건 카드를 연다)', async () => {
    const open = vi.fn()
    show({
      run_id: 'run_x',
      kind: 'radius',
      advice: [{ segments: [{ kind: 'text', text: '반경 밖에서 빠진 곳이 많아요' }], is_guess: false }],
      actions: [
        { index: 0, type: 'widen_radius', label: '반경 넓히기', params: { run_id: 'run_x' } },
        { index: 1, type: 'open_evidence', label: '조건 확인하기', params: { run_id: 'run_x' } },
      ],
    }, 200, open)
    expect(await screen.findByText('반경 밖에서 빠진 곳이 많아요')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: '반경 넓히기' })).toBeInTheDocument()
    await userEvent.click(screen.getByRole('button', { name: '조건 확인하기' }))
    expect(open).toHaveBeenCalledOnce()
  })

  it('204면 아무것도 없다', async () => {
    const { container } = show(null, 204)
    // 기다리는 동안의 자리가 사라지고 빈 채로 남는다.
    await waitFor(() => expect(container).toBeEmptyDOMElement())
  })
})
